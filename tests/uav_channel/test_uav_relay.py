import os
import socket
import sys
import threading
import time
from pathlib import Path

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))

from uav_channel.channel import ChannelModel, RoundChannel
from secure_fl.common import messages as M
from uav_channel.uav.relay import UavRelay

TOL = 0.05
BS_PORT = 6200
DEVICE_PORTS = [7201, 7202]


class FixedChannel:
    mode = 'fixed'

    def __init__(self, rates_bytes_per_s):
        self.rates = list(rates_bytes_per_s)

    def round(self, t):
        r = self.rates[(t - 1) % len(self.rates)]
        return RoundChannel(t, self.mode, (1.0, 1.0), (r[0] * 8.0, r[1] * 8.0))


def connect_retry(port, timeout=10.0):
    t0 = time.monotonic()
    while True:
        try:
            s = socket.create_connection(('127.0.0.1', port), timeout=5.0)
            s.settimeout(None)
            return s
        except OSError:
            if time.monotonic() - t0 > timeout:
                raise
            time.sleep(0.05)


def scenario(channel, uav_cfg, payload_sizes):
    rounds = len(payload_sizes)
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(('127.0.0.1', BS_PORT))
    srv.listen(8)
    errors = []

    def uav():
        try:
            UavRelay('127.0.0.1', BS_PORT, '127.0.0.1', DEVICE_PORTS, channel, uav_cfg).run(rounds, log=lambda *_: None)
        except Exception as e:
            errors.append(e)

    threading.Thread(target=uav, daemon=True).start()
    control, _ = srv.accept()
    hello, _ = M.recv_msg(control)
    assert hello['type'] == M.HELLO and hello['role'] == 'uav'
    devices, pipes = [], []
    for port in DEVICE_PORTS:
        devices.append(connect_retry(port))
        p, _ = srv.accept()
        pipes.append(p)
    rows = []
    for t, sizes in enumerate(payload_sizes, 1):
        report, _ = M.recv_msg(control)
        assert report['type'] == M.CHANNEL_REPORT and report['t'] == t
        start = [None, None]
        end = [None, None]
        nbytes = [None, None]

        def send(k):
            start[k] = time.monotonic()
            M.send_msg(devices[k], M.UPLOAD, {'data': os.urandom(int(sizes[k]))})

        def recv(k):
            msg, n = M.recv_msg(pipes[k])
            end[k] = time.monotonic()
            nbytes[k] = n

        ths = [threading.Thread(target=f, args=(k,)) for k in (0, 1) for f in (recv, send)]
        for th in ths:
            th.start()
        for th in ths:
            th.join()
        M.send_msg(control, M.ROUND_DONE, {'t': t})
        stats, _ = M.recv_msg(control)
        assert stats['type'] == M.UAV_STATS and stats['t'] == t
        for k, key in enumerate(('dev1', 'dev2')):
            item = [i for i in stats[key] if i['type'] == M.UPLOAD][0]
            rows.append({'t': t, 'dev': k + 1, 'elapsed': end[k] - start[k], 'frame': nbytes[k],
                         'tx_s': item['tx_s'], 'wall_s': item['wall_s'], 'rate': report['rate_bytes_per_s'][k],
                         'virtual': item['virtual']})
    for s in devices + pipes + [control, srv]:
        s.close()
    assert not errors, errors
    return rows


def rel(a, b):
    return abs(a - b) / b


def test_five_megabytes_at_one_megabit():
    rate = 1e6 / 8
    rows = scenario(FixedChannel([(rate, rate)]), {}, [(5_000_000, 5_000_000)])
    for r in rows:
        want = r['frame'] / rate
        assert rel(r['elapsed'], want) < TOL, f'thiết bị {r["dev"]}: {r["elapsed"]:.2f}s so với {want:.2f}s'
        assert rel(r['tx_s'], want) < TOL
    print(f'[TEST] A. 5 MB ở 1 Mbit/s, hai thiết bị cùng lúc: ' + ', '.join(
        f'thiết bị {r["dev"]} {r["elapsed"]:.2f}s (kỳ vọng {r["frame"] / rate:.2f}s)' for r in rows))


def test_different_rates_per_device():
    rates = (150_000.0, 60_000.0)
    rows = scenario(FixedChannel([rates]), {}, [(600_000, 240_000)])
    for r in rows:
        want = r['frame'] / rates[r['dev'] - 1]
        assert rel(r['elapsed'], want) < TOL, f'thiết bị {r["dev"]}: {r["elapsed"]:.2f}s so với {want:.2f}s'
    print('[TEST] B. Hai tốc độ khác nhau: ' + ', '.join(f'thiết bị {r["dev"]} {r["elapsed"]:.2f}s' for r in rows))


def test_virtual_time():
    rate = 20_000.0
    rows = scenario(FixedChannel([(rate, rate)]), {'time_mode': 'virtual'}, [(200_000, 200_000)])
    for r in rows:
        want = r['frame'] / rate
        assert r['virtual'], 'phải đánh dấu thời gian ảo'
        assert rel(r['tx_s'], want) < 1e-9, f'tx_s {r["tx_s"]:.4f} so với {want:.4f}'
        assert r['wall_s'] < 1.0, f'thời gian máy {r["wall_s"]:.3f}s phải nhỏ trong thời gian ảo'
    print(f'[TEST] C. Thời gian ảo: báo cáo {rows[0]["tx_s"]:.2f}s đúng bằng byte/R ({rows[0]["frame"] / rate:.2f}s), '
          f'thời gian máy {rows[0]["wall_s"]:.3f}s')


def test_real_channel_with_and_without_uav():
    with open(ROOT / 'src' / 'uav_channel' / 'config.yaml', encoding='utf-8') as f:
        cfg = yaml.safe_load(f)
    out = []
    for mode, uav_cfg, label in (('uav_noma_pc', {}, 'có UAV'),
                                 ('direct_noma', {'time_mode': 'auto', 'virtual_below_bps': 1e6}, 'không UAV')):
        model = ChannelModel.from_config(dict(cfg, channel=dict(cfg['channel'], mode=mode)))
        rounds = (1, 2)
        sizes = []
        for t in rounds:
            r = model.round(t).rate_bytes_per_s
            sizes.append((int(r[0] * 3), int(r[1] * 3)))
        rows = scenario(model, uav_cfg, sizes)
        for r in rows:
            want = r['frame'] / r['rate']
            assert rel(r['tx_s'], want) < TOL, f'{label} vòng {r["t"]} thiết bị {r["dev"]}: {r["tx_s"]:.2f}s so với {want:.2f}s'
            if mode == 'direct_noma':
                assert r['virtual'] and r['wall_s'] < 1.0
        out.append((label, rows))
    for label, rows in out:
        print(f'[TEST] D. Kênh thật, {label}: ' + '; '.join(
            f'vòng {r["t"]} thiết bị {r["dev"]}: R={r["rate"] * 8 / 1e6:.4f} Mbit/s, tx {r["tx_s"]:.2f}s, ảo={r["virtual"]}, máy {r["wall_s"]:.2f}s'
            for r in rows))


if __name__ == '__main__':
    only = sys.argv[1:] or ['B', 'C', 'D', 'A']
    table = {'A': test_five_megabytes_at_one_megabit, 'B': test_different_rates_per_device,
             'C': test_virtual_time, 'D': test_real_channel_with_and_without_uav}
    for key in only:
        table[key]()
        time.sleep(0.5)
    print('[TEST] uav_relay: ĐẠT')
