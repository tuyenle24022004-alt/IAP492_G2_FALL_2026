"""BS thật (tiến trình riêng) + 2 client GIẢ (luồng) qua TCP, không cần mô hình hay dữ liệu: kiểm tra giao thức một vòng.
Chạy: python tests/secure_fl/test_protocol.py"""
import json
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

from secure_fl.arms import resolve                                               # noqa: E402
from secure_fl.common import messages as Msg                                     # noqa: E402
from secure_fl.security import make_backend, make_scheme, priority_order         # noqa: E402
from secure_fl.security.base import from_wire, to_wire                           # noqa: E402

CFG = yaml.safe_load(open(ROOT / 'src' / 'secure_fl' / 'config.yaml', encoding='utf-8'))
M, ROUNDS, N_K = 1539, 3, {1: 2620, 2: 2414}
W = {d: n / sum(N_K.values()) for d, n in N_K.items()}


def fake_client(dev, arm, port, xs, K, results):
    """Giống client.py nhưng Δ lấy sẵn (xs[t][dev]) thay vì huấn luyện."""
    lock = CFG['lock']
    kind, kw = resolve(arm, lock)
    he = make_backend('emulated', CFG['he'], seed=100 + dev)
    s = make_scheme(kind, M, he=he, order=priority_order([1536, 3]), K=K, **kw)
    sock = socket.create_connection((lock['host'], port), timeout=30)
    Msg.send_msg(sock, Msg.HELLO, {'dev': dev, 'n_k': N_K[dev], 'M': M})
    got = []
    for t in range(0, ROUNDS + 1):                  # vòng 0 = tổng hợp trọng số huấn luyện cục bộ
        m, _ = Msg.recv_msg(sock)
        assert m['type'] == Msg.ROUND_START and abs(m['w'] - W[dev]) < 1e-12
        pay = s.protect(m['w'] * xs[t][dev], t, dev - 1, np.random.default_rng([dev, t]))
        Msg.send_msg(sock, Msg.UPLOAD, {'t': t, 'payload': to_wire(pay, he)})
        if s.needs_decrypt:
            m, _ = Msg.recv_msg(sock)
            share = s.client_share(from_wire(m['csum'], he), dev - 1)
            Msg.send_msg(sock, Msg.PARTIAL_DEC, {'t': t, 'share': to_wire(share, he) if share else None})
        m, _ = Msg.recv_msg(sock)
        got.append(s.client_finish(from_wire(m['agg'], he), t))
        if dev == 1:
            Msg.send_msg(sock, Msg.METRICS, {'t': t, 'acc': 0.5})
    results[dev] = got
    sock.close()


def run(arm, port, with_k_for_bs=False):
    lock = CFG['lock']
    rng = np.random.default_rng(0)
    xs = {t: {1: rng.normal(0, 0.05, M), 2: rng.normal(0, 0.05, M)} for t in range(0, ROUNDS + 1)}   # như trọng số
    K = bytes(range(32))
    with tempfile.TemporaryDirectory() as d:
        kf = Path(d) / 'K'
        kf.write_bytes(K)
        args = [sys.executable, str(ROOT / 'src' / 'secure_fl' / 'bs' / 'server.py'), '--arm', arm, '--port', str(port),
                '--out', d, '--rounds', str(ROUNDS)] + (['--k-file', str(kf)] if with_k_for_bs else [])
        bs = subprocess.Popen(args, env=dict(os.environ, PYTHONIOENCODING='utf-8'), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        time.sleep(1.0)
        results = {}
        ts = [threading.Thread(target=fake_client, args=(dev, arm, port, xs, K, results)) for dev in (1, 2)]
        [t.start() for t in ts]
        [t.join(120) for t in ts]
        out = bs.communicate(timeout=60)[0].decode('utf-8', 'replace')
        assert bs.returncode == 0, out
        log = json.load(open(Path(d) / 'bs_log.json', encoding='utf-8'))
        cap = sorted(p.name for p in (Path(d) / 'capture').glob('*.npy'))
    worst = 0.0
    for t in range(0, ROUNDS + 1):
        exact = W[1] * xs[t][1] + W[2] * xs[t][2]
        for dev in (1, 2):
            worst = max(worst, np.abs(results[dev][t] - exact).max())
    return log, cap, worst, results


def check(arm, port, with_k=False):
    log, cap, worst, res = run(arm, port, with_k)
    assert worst < 1e-6, f'{arm}: tổng sai {worst:.2e}'
    for t in range(ROUNDS + 1):
        assert np.array_equal(res[1][t], res[2][t]), f'{arm}: hai client có tổng khác nhau'
    sz = log['sizes']
    r = log['rounds'][0]['bytes']
    up = r['UPLOAD']['1']
    assert sz['upload'] <= up <= sz['upload'] + 400, (arm, up, sz['upload'])
    if 'PARTIAL_DEC' in r:
        assert sz['share'] <= r['PARTIAL_DEC']['1'] <= sz['share'] + 400
    print(f'[TEST] {arm:<10} sai số tổng {worst:.1e}; UPLOAD {up:,} B (dự báo {sz["upload"]:,}); '
          f'PARTIAL_DEC {r.get("PARTIAL_DEC", {}).get("1", 0):,} B; capture {len(cap)} file')
    return cap


def test_none():
    check('none', 7701)


def test_ckks_full():
    cap = check('ckks_full', 7702)
    assert cap == [], 'ckks_full: BS không có phần rõ nào để lưu'


def test_fas():
    cap = check('fas_lam0', 7703)
    assert len(cap) == 2 * (ROUNDS + 1)


def test_bs_refuses_key_unless_fasbs():
    try:
        run('fas_lam1', 7704, with_k_for_bs=True)
    except AssertionError as e:
        assert 'không được cấp khóa xáo' in str(e)
        print('[TEST] BS từ chối khóa xáo ở arm fas_lam1 (chỉ fasbs_* mới được cấp)')
        return
    raise AssertionError('BS phải từ chối --k-file ở arm fas_lam1')


if __name__ == '__main__':
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith('test_'):
            try:
                fn()
                print(f'ĐẠT  {name}')
            except Exception as e:                                                  # noqa: BLE001
                fails += 1
                print(f'LỖI  {name}: {e}')
    sys.exit(1 if fails else 0)
