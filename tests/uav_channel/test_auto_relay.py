"""Kiểm thử ống kênh tự theo vòng (auto_relay): BS giả, tốc độ cố định, đo thời gian giữ thật — chạy: python tests/uav_channel/test_auto_relay.py"""
import json
import math
import os
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))

from secure_fl.common import messages as M
from uav_channel.channel import RoundChannel
from uav_channel.uav.auto_relay import AutoRelay, HELD_TYPES, peek_type_round

CHUNK = 1460
TOL_REL, TOL_ABS = 0.05, 0.03                     # sai số cho phép: max(5%, 30 ms)


class FixedChannel:
    """Tốc độ cố định theo vòng: rates[(t-1) % len] = (R1, R2) byte/s."""
    mode = 'fixed'

    def __init__(self, rates):
        self.rates = list(rates)

    def round(self, t):
        r = self.rates[(t - 1) % len(self.rates)]
        return RoundChannel(t, self.mode, (1.0, 1.0), (r[0] * 8.0, r[1] * 8.0))


def free_port():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


def ok_time(measured, want):
    return abs(measured - want) <= max(TOL_REL * want, TOL_ABS)


def scenario(channel, plan, stats_path, bad_tin=False):
    """plan[dev] = danh sách (loại tin, vòng, số byte tải) gửi lần lượt. Trả (kết quả đo ở BS, lỗi của ống)."""
    bs_port, ports = free_port(), [free_port(), free_port()]
    bs = socket.socket()
    bs.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    bs.bind(('127.0.0.1', bs_port))
    bs.listen(4)
    relay = AutoRelay(channel, '127.0.0.1', bs_port, '127.0.0.1', ports, stats_path, chunk=CHUNK, log=lambda *_: None)
    relay_err = []

    def run_relay():
        try:
            relay.run()
        except Exception as e:                      # noqa: BLE001
            relay_err.append(repr(e))

    threading.Thread(target=run_relay, daemon=True).start()
    assert relay.ready.wait(10)
    got = []                                        # (thiết bị, loại, vòng, byte khung, giờ nhận đủ tại BS)
    lock = threading.Lock()
    delivered = {}                                  # (thiết bị, loại, vòng) -> Event: BS đã nhận đủ tin đó

    def event(key):
        with lock:
            return delivered.setdefault(key, threading.Event())

    def bs_reader(conn):
        dev = None
        try:
            while True:
                msg, n = M.recv_msg(conn)
                if msg['type'] == M.HELLO:
                    dev = msg['dev']
                with lock:
                    got.append((dev, msg['type'], msg.get('t'), n, time.monotonic()))
                event((dev, msg['type'], msg.get('t'))).set()
        except (ConnectionError, OSError):
            pass

    def bs_acceptor():
        for _ in range(2):
            c, _ = bs.accept()
            threading.Thread(target=bs_reader, args=(c,), daemon=True).start()

    threading.Thread(target=bs_acceptor, daemon=True).start()
    sent = {}                                       # (thiết bị, loại, vòng) -> giờ bắt đầu gửi

    def device(dev):
        s = socket.create_connection(('127.0.0.1', ports[dev - 1]), timeout=10)
        s.settimeout(None)
        M.send_msg(s, M.HELLO, {'dev': dev})
        time.sleep(0.2)
        for mtype, t, nbytes in plan[dev]:
            payload = {'t': t, 'data': os.urandom(nbytes)} if not bad_tin else {'data': os.urandom(nbytes)}
            sent[(dev, mtype, t)] = time.monotonic()
            M.send_msg(s, mtype, payload)
            if not bad_tin:                           # như FL thật: chỉ gửi tin kế tiếp sau khi BS đã nhận tin này
                assert event((dev, mtype, t)).wait(60), f'BS không nhận được {mtype} vòng {t} của thiết bị {dev}'
            time.sleep(0.05)
        time.sleep(0.3)
        s.close()

    ths = [threading.Thread(target=device, args=(d,)) for d in (1, 2)]
    for th in ths:
        th.start()
    for th in ths:
        th.join()
    time.sleep(1.0)
    bs.close()
    return got, sent, relay_err


def read_stats(path):
    return [json.loads(x) for x in Path(path).read_text(encoding='utf-8').splitlines() if x.strip()]


def test_peek():
    up = M.encode(M.UPLOAD, {'t': 7, 'payload': os.urandom(5000)})
    assert peek_type_round(up[:CHUNK]) == ('UPLOAD', 7)
    assert peek_type_round(M.encode(M.HELLO, {'dev': 1, 'n_k': 10, 'M': 5})[:CHUNK]) == ('HELLO', None)
    assert peek_type_round(M.encode(M.UPLOAD, {'payload': b'x' * 100})[:CHUNK]) == ('UPLOAD', None)
    assert peek_type_round(b'\xff\xfe garbage') == (None, None)
    print('[TEST] A. peek_type_round đọc đúng (type, t) từ đầu tin; thiếu t thì trả None; rác thì (None, None)')


def test_hold_time_and_rounds():
    """Hai thiết bị hai tốc độ khác nhau, hai vòng có tốc độ khác nhau, tin không thuộc UPLOAD/PARTIAL_DEC không bị giữ."""
    rates = [(800_000.0, 300_000.0), (600_000.0, 900_000.0)]
    plan = {1: [(M.METRICS, 0, 100_000), (M.UPLOAD, 1, 300_000), (M.PARTIAL_DEC, 1, 100_000), (M.UPLOAD, 2, 150_000)],   # METRICS đứng đầu: tránh xếp hàng sau tin đang bị giữ
            2: [(M.UPLOAD, 1, 300_000), (M.PARTIAL_DEC, 1, 100_000), (M.UPLOAD, 2, 150_000)]}
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / 'uav_stats.jsonl'
        got, sent, err = scenario(FixedChannel(rates), plan, path)
        assert not err, err
        recv = {(g[0], g[1], g[2]): g for g in got}
        lines = []
        for (dev, mtype, t), t0 in sorted(sent.items()):
            frame = recv[(dev, mtype, t)][3]
            elapsed = recv[(dev, mtype, t)][4] - t0
            if mtype in HELD_TYPES:
                want = frame / rates[(t - 1) % 2][dev - 1]
                assert ok_time(elapsed, want), f'thiết bị {dev} {mtype} vòng {t}: đo {elapsed:.3f}s, kỳ vọng {want:.3f}s'
                lines.append(f'tb{dev} {mtype} v{t}: {elapsed:.2f}s (kỳ vọng {want:.2f}s)')
            else:
                assert elapsed < 0.15, f'tin {mtype} không được giữ nhưng mất {elapsed:.3f}s'
        stats = read_stats(path)
        msgs = [r for r in stats if r['kind'] == 'msg']
        chans = {r['t']: r for r in stats if r['kind'] == 'channel'}
        assert set(chans) == {1, 2} and len(msgs) == 6, (set(chans), len(msgs))          # mỗi thiết bị 3 tin bị giữ (UPLOAD v1, PARTIAL_DEC v1, UPLOAD v2)
        for r in msgs:
            assert r['n_packets'] == math.ceil((r['frame'] - 4) / CHUNK), r
            assert ok_time(r['hold_s'], r['frame'] / r['rate_Bps']), r
            assert abs(r['rate_Bps'] - rates[(r['t'] - 1) % 2][r['dev'] - 1]) < 1e-6
        assert not [r for r in stats if r['kind'] == 'pass' and r['type'] in HELD_TYPES]
        # hai thiết bị bị giữ song song: pha UPLOAD vòng 1 tốn thời gian của thiết bị chậm hơn, không phải tổng
        a, b = (recv[(k, M.UPLOAD, 1)][4] for k in (1, 2))
        t_start = min(sent[(1, M.UPLOAD, 1)], sent[(2, M.UPLOAD, 1)])
        slow = max(recv[(k, M.UPLOAD, 1)][3] / rates[0][k - 1] for k in (1, 2))
        both = max(a, b) - t_start
        assert both < 1.2 * slow + 0.1, f'hai thiết bị không chạy song song: {both:.2f}s so với {slow:.2f}s'
    print('[TEST] B. Giữ đúng byte/R theo từng thiết bị và từng vòng (sai số ≤ max(5%, 30 ms)): ' + '; '.join(lines[:4]) + ' ...')
    print(f'[TEST] B. METRICS và HELLO đi thẳng; hai thiết bị song song: pha UPLOAD vòng 1 mất {both:.2f}s (thiết bị chậm hơn {slow:.2f}s)')


def test_missing_round_is_error():
    plan = {1: [(M.UPLOAD, 1, 5_000)], 2: []}
    with tempfile.TemporaryDirectory() as d:
        got, sent, err = scenario(FixedChannel([(1e6, 1e6)]), plan, Path(d) / 'uav_stats.jsonl', bad_tin=True)
    assert err and 'không có số vòng' in err[0], err
    assert not [g for g in got if g[1] == M.UPLOAD], 'tin thiếu t không được chuyển tiếp'
    print(f'[TEST] C. Tin UPLOAD thiếu số vòng t: ống báo lỗi rõ ràng và không chuyển tiếp ({err[0][:80]}...)')


if __name__ == '__main__':
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith('test_'):
            try:
                fn()
                print(f'ĐẠT  {name}')
            except AssertionError as e:
                fails += 1
                print(f'LỖI  {name}: {e}')
    print('[TEST] auto_relay: ' + ('ĐẠT' if not fails else f'LỖI ({fails})'))
    sys.exit(1 if fails else 0)
