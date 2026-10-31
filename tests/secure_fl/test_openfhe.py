"""Mã hóa THẬT bằng OpenFHE, đủ ba vai trò (BS, client1, client2) qua socket: thiết lập khóa đa bên, mã hóa, cộng, giải mã từng phần, ghép.
Chỉ chạy được trong container Linux (docker/); trên Windows tự bỏ qua.  Chạy: python tests/secure_fl/test_openfhe.py"""
import socket
import sys
import threading
from pathlib import Path

import numpy as np
import yaml

sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))

CFG = yaml.safe_load(open(ROOT / 'src' / 'secure_fl' / 'config.yaml', encoding='utf-8'))
M = 1539


def have_openfhe():
    try:
        import openfhe  # noqa: F401
        return True
    except ImportError:
        print('  (bỏ qua: không có OpenFHE trên máy này; chạy trong container docker/)')
        return False


def setup_three():
    """BS + 2 client trong một tiến trình, nối bằng socket thật; trả (bs, c1, c2)."""
    from secure_fl.security.he_backend import make_backend
    bs = make_backend('openfhe', CFG['he'], role='bs')
    c1 = make_backend('openfhe', CFG['he'], role='client', dev=1)
    c2 = make_backend('openfhe', CFG['he'], role='client', dev=2)
    (b1, k1), (b2, k2) = socket.socketpair(), socket.socketpair()
    ts = [threading.Thread(target=c1.setup_client, args=(k1, 1)), threading.Thread(target=c2.setup_client, args=(k2, 2))]
    [t.start() for t in ts]
    bs.setup_bs({1: b1, 2: b2})
    [t.join(120) for t in ts]
    return bs, c1, c2


def test_distributed_roundtrip():
    if not have_openfhe():
        return
    bs, c1, c2 = setup_three()
    assert bs._sk is None and c1._sk is not None and c2._sk is not None, 'BS không được có khóa bí mật'
    rng = np.random.default_rng(0)
    x1, x2 = rng.normal(0, 0.05, M) * 0.52, rng.normal(0, 0.05, M) * 0.48
    # client mã hóa -> bytes -> BS
    ct1 = bs.ct_from_bytes(c1.ct_to_bytes(c1.encrypt(x1)))
    ct2 = bs.ct_from_bytes(c2.ct_to_bytes(c2.encrypt(x2)))
    csum = bs.add(ct1, ct2)
    # BS -> bytes -> client giải mã từng phần -> bytes -> BS
    s1 = bs.share_from_bytes(c1.share_to_bytes(c1.partial_decrypt(c1.ct_from_bytes(bs.ct_to_bytes(csum)), 0)))
    s2 = bs.share_from_bytes(c2.share_to_bytes(c2.partial_decrypt(c2.ct_from_bytes(bs.ct_to_bytes(csum)), 1)))
    out = bs.fuse(csum, [s1, s2], M)
    err = np.abs(out - (x1 + x2)).max()
    assert err < 1e-6, f'sai số giải mã {err:.2e}'
    nbytes = len(bs.ct_to_bytes(csum)), len(c1.share_to_bytes(c1.partial_decrypt(csum, 0)))
    print(f'[TEST] OpenFHE đa khóa qua mạng: sai số {err:.1e}; ciphertext {nbytes[0]:,} B, phần giải mã {nbytes[1]:,} B')


def test_single_share_is_not_enough():
    if not have_openfhe():
        return
    bs, c1, c2 = setup_three()
    x = np.random.default_rng(1).normal(0, 0.05, M)
    ct = c1.encrypt(x)
    only1 = c1.partial_decrypt(ct, 0)
    try:
        out = bs.fuse(ct, [only1], M)
        ok = np.abs(out - x).max() > 1e-3
    except Exception:                                    # noqa: BLE001  ghép thiếu phần có thể báo lỗi
        ok = True
    assert ok, 'chỉ một phần giải mã mà vẫn khôi phục được bản rõ'
    print('[TEST] một phần giải mã đơn lẻ không đủ để giải mã')


if __name__ == '__main__':
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith('test_'):
            try:
                fn()
                print(f'ĐẠT  {name}')
            except Exception as e:                                                  # noqa: BLE001
                fails += 1
                print(f'LỖI  {name}: {e!r}')
    sys.exit(1 if fails else 0)
