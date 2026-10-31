"""Kiểm thử công thức byte -> thời gian (tx_plan) và file chạy ống run_relay.py (tiến trình thật, BS giả) — chạy: python tests/uav_channel/test_tx_plan.py"""
import json
import math
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import numpy as np
import yaml

sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))

from secure_fl.common import messages as M
from uav_channel import tx_plan as TP
from uav_channel.channel import ChannelModel, RoundChannel

CFG = yaml.safe_load(open(ROOT / 'src' / 'uav_channel' / 'config.yaml', encoding='utf-8'))
FLQ = CFG['fl_qua_kenh']
HE = yaml.safe_load(open(ROOT / 'src' / 'secure_fl' / 'config.yaml', encoding='utf-8'))['he']


class FixedChannel:
    mode = 'fixed'

    def __init__(self, rates):
        self.rates = list(rates)

    def round(self, t):
        r = self.rates[t % len(self.rates)]
        return RoundChannel(t, self.mode, (1.0, 1.0), (r[0] * 8.0, r[1] * 8.0))


def test_frame_bytes():
    n_params = json.load(open(ROOT / FLQ['model_metrics'], encoding='utf-8'))['n_params']
    assert n_params == 1539
    ov = FLQ['frame_overhead_B']
    assert TP.frame_bytes('none', n_params, HE, ov) == (4 * 1539 + ov['none'], 0)
    up, sh = TP.frame_bytes('ckks_full', n_params, HE, ov)
    assert (up, sh) == (HE['ct_bytes'] + ov['ckks_full'], HE['share_bytes']), (up, sh)
    assert TP.n_ct(1539, HE['slots']) == 1 and TP.n_ct(198723, HE['slots']) == 49 and TP.n_ct(4096, 4096) == 1 and TP.n_ct(4097, 4096) == 2
    assert TP.frame_bytes('ckks_full', 198723, HE, ov) == (49 * HE['ct_bytes'] + ov['ckks_full'], 49 * HE['share_bytes'])
    assert TP.packets(6220, 1460) == 5 and TP.packets(HE['ct_bytes'], 1460) == 91 and TP.packets(HE['share_bytes'], 1460) == 46
    try:
        TP.frame_bytes('fas', 10, HE, ov)
        raise AssertionError('arm lạ phải báo lỗi')
    except ValueError:
        pass
    print(f'[TEST] A. Byte theo công thức: không mã hóa {4 * 1539 + ov["none"]} B; CKKS {up} + {sh} B; n_ct lớp cuối 1, fire9 49; '
          f'gói TCP 5, 91 + 46')


def test_predict_and_timeout():
    rates = [(100_000.0, 50_000.0), (20_000.0, 80_000.0), (10_000.0, 10_000.0)]      # byte/s mỗi vòng cho hai thiết bị
    ch = FixedChannel(rates)
    up, sh = 200_000, 100_000
    p = TP.predict(ch, up, sh, 3)
    t_up = [max(up / a, up / b) for a, b in rates]
    t_pd = [max(sh / a, sh / b) for a, b in rates]
    assert np.allclose(p['t_upload'], t_up) and np.allclose(p['t_partial_dec'], t_pd)
    assert abs(p['total_s'] - (sum(t_up) + sum(t_pd))) < 1e-9
    spread = [max(abs(up / a - up / b), abs(sh / a - sh / b)) for a, b in rates]
    assert abs(p['max_wait_s'] - max(spread)) < 1e-9 and np.allclose(p['wait_s'], spread)
    p0 = TP.predict(ch, 6000, 0, 3)                                                    # không mã hóa: không có PARTIAL_DEC
    assert np.all(p0['t_partial_dec'] == 0)
    assert TP.timeout_for(100.0, 2.0, 900) == 900 and TP.timeout_for(17_280.0, 2.0, 900) == int(2 * 17_280 + 600)
    print(f'[TEST] B. Dự kiến: tổng {p["total_s"]:.1f}s, chờ lệch lớn nhất {p["max_wait_s"]:.1f}s; hạn chờ 4,8 giờ -> {TP.timeout_for(17_280.0, 2.0, 900)}s, '
          f'không bao giờ thấp hơn 900s')


def test_run_relay_process():
    """Chạy run_relay.py như tiến trình thật với kênh thật (có UAV), BS giả; đo thời gian giữ một UPLOAD so với byte/R của vòng 0."""
    free = []
    for _ in range(3):
        s = socket.socket()
        s.bind(('127.0.0.1', 0))
        free.append(s.getsockname()[1])
        s.close()
    bs_port, p1, p2 = free
    bs = socket.socket()
    bs.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    bs.bind(('127.0.0.1', bs_port))
    bs.listen(4)
    cfg = dict(CFG, channel=dict(CFG['channel'], mode='uav_noma_pc'))
    want_rate = ChannelModel.from_config(cfg).round(0).rate_bytes_per_s[0]
    nbytes = int(want_rate * 0.8)                                                      # kỳ vọng giữ khoảng 0,8 s
    with tempfile.TemporaryDirectory() as d:
        proc = subprocess.Popen([sys.executable, str(ROOT / 'src' / 'uav_channel' / 'uav' / 'run_relay.py'), '--channel', 'uav_noma_pc',
                                 '--bs-host', '127.0.0.1', '--bs-port', str(bs_port), '--ports', str(p1), str(p2), '--listen-host', '127.0.0.1',
                                 '--out', d], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8',
                                env=dict(os.environ, PYTHONIOENCODING='utf-8'))
        try:
            conns = []

            def acceptor():
                for _ in range(2):
                    conns.append(bs.accept()[0])

            threading.Thread(target=acceptor, daemon=True).start()
            socks = []
            for port in (p1, p2):
                t0 = time.monotonic()
                while True:
                    try:
                        socks.append(socket.create_connection(('127.0.0.1', port), timeout=5))
                        break
                    except OSError:
                        assert time.monotonic() - t0 < 30, 'run_relay không lắng nghe'
                        time.sleep(0.1)
            while len(conns) < 2:
                time.sleep(0.05)
            got = {}

            def read_bs(c):
                msg, n = M.recv_msg(c)
                got[n] = time.monotonic()

            rd = threading.Thread(target=read_bs, args=(conns[0],))
            rd.start()
            t_send = time.monotonic()
            M.send_msg(socks[0], M.UPLOAD, {'t': 0, 'payload': os.urandom(nbytes)})
            rd.join(timeout=30)
            (frame, t_recv), = got.items()
            hold = t_recv - t_send
            want = frame / want_rate
            assert abs(hold - want) <= max(0.05 * want, 0.03), f'giữ {hold:.3f}s, kỳ vọng {want:.3f}s'
            for s in socks:
                s.close()
            proc.wait(timeout=30)
        finally:
            if proc.poll() is None:
                proc.kill()
            out = proc.stdout.read()
        assert proc.returncode == 0, out
        meta = json.loads((Path(d) / 'uav_channel.json').read_text(encoding='utf-8'))
        assert meta['mode'] == 'uav_noma_pc' and 'link_budget' in meta and meta['chunk_bytes'] == FLQ['chunk_bytes']
        stats = [json.loads(x) for x in (Path(d) / 'uav_stats.jsonl').read_text(encoding='utf-8').splitlines()]
        msg = [r for r in stats if r['kind'] == 'msg']
        assert len(msg) == 1 and msg[0]['t'] == 0 and abs(msg[0]['rate_Bps'] - want_rate) < 1e-6
    bs.close()
    print(f'[TEST] C. run_relay.py (tiến trình thật, kênh có UAV): R vòng 0 = {want_rate * 8 / 1e6:.3f} Mbit/s, giữ {frame} B mất {hold:.2f}s '
          f'(kỳ vọng {want:.2f}s); uav_stats.jsonl và uav_channel.json được ghi')


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
    print('[TEST] tx_plan, run_relay: ' + ('ĐẠT' if not fails else f'LỖI ({fails})'))
    sys.exit(1 if fails else 0)
