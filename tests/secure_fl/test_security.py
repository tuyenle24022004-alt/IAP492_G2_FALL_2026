"""Kiểm thử gói security/ (none, ckks_full, fas) — chạy: python tests/secure_fl/test_security.py"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
from pathlib import Path

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))

from secure_fl.security import make_backend, make_scheme, priority_order
from secure_fl.security.perm import perm_for

CFG = yaml.safe_load(open(ROOT / 'src' / 'secure_fl' / 'config.yaml', encoding='utf-8'))
M = 1539
K = bytes(range(32))


def system(name, xs, t=1, **kw):
    """Một vòng trong một tiến trình: 2 client protect -> BS cộng -> finish."""
    he = make_backend('emulated', CFG['he'], seed=1)
    s = make_scheme(name, M, he=he, order=priority_order([1536, 3]), K=K, **kw)
    pays = [s.protect(x, t, d, np.random.default_rng(100 + d)) for d, x in enumerate(xs)]
    return s, pays, s.finish(s.aggregate(pays), t)


def data():
    rng = np.random.default_rng(0)
    return [rng.normal(0, 0.02, M) * w for w in (0.52, 0.48)]


def test_none_exact():
    xs = data()
    _, _, out = system('none', xs)
    assert np.abs(out - sum(xs)).max() < 1e-7


def test_ckks_error_small():
    xs = data()
    _, _, out = system('ckks_full', xs)
    err = np.abs(out - sum(xs)).max()
    assert err < 1e-6, err


def test_fas_lambda0_matches_sum():
    xs = data()
    _, _, out = system('fas', xs, p=0.1, lam=0.0)
    err = np.abs(out - sum(xs)).max()
    assert err < 1e-6, err


def test_fas_noise_scale():
    xs = data()
    s, pays, _ = system('fas', xs, p=0.1, lam=3.0)
    rms = np.sqrt(np.mean(xs[1][154:] ** 2))   # info giữ thiết bị gọi protect sau cùng
    assert 0.8 * 3 * rms < s.info['sd'] < 1.2 * 3 * rms


def test_pi_same_across_devices_and_changes_across_rounds():
    assert (perm_for(K, 5, 100) == perm_for(K, 5, 100)).all()
    assert not (perm_for(K, 5, 100) == perm_for(K, 6, 100)).all()
    assert not (perm_for(b'\1' * 32, 5, 100) == perm_for(K, 5, 100)).all()


def test_fas_bs_cannot_locate_plain_values():
    xs = data()
    s, pays, _ = system('fas', xs, p=0.1, lam=0.0)
    v, idx = s.bs_view(pays[0], 1)
    true = xs[0][idx]
    c = np.corrcoef(v, true)[0, 1]
    assert abs(c) < 0.1, c
    sb = make_scheme('fas', M, he=make_backend('emulated', CFG['he']), order=priority_order([1536, 3]), K=K,
                     p=0.1, lam=0.0, key_holder='bs')
    p = sb.protect(xs[0], 1, 0, np.random.default_rng(1))
    v2, idx2 = sb.bs_view(p, 1)
    assert np.abs(v2 - xs[0][idx2]).max() < 1e-6          # BS giữ K thì đọc được phần rõ


def test_wire_roundtrip_and_split_roles_match_in_process():
    from secure_fl.security.base import from_wire, to_wire
    xs = data()
    for name, kw in (('none', {}), ('ckks_full', {}), ('fas', dict(p=0.1, lam=0.0))):
        he = make_backend('emulated', CFG['he'], seed=3)
        s = make_scheme(name, M, he=he, order=priority_order([1536, 3]), K=K, **kw)
        pays = [from_wire(to_wire(s.protect(x, 1, d, np.random.default_rng(d)), he), he) for d, x in enumerate(xs)]
        csum = from_wire(to_wire(s.aggregate(pays), he), he)
        shares = [from_wire(to_wire(s.client_share(csum, p), he), he) if s.client_share(csum, p) else None for p in (0, 1)]             if s.needs_decrypt else []
        agg = from_wire(to_wire(s.bs_fuse(csum, [x for x in shares if x]), he), he)
        out = s.client_finish(agg, 1)
        assert np.abs(out - sum(xs)).max() < 1e-6, (name, np.abs(out - sum(xs)).max())


def test_wire_bytes_match_sizes():
    import msgpack
    from secure_fl.security.base import to_wire
    xs = data()
    for name, kw in (('none', {}), ('ckks_full', {}), ('fas', dict(p=0.1, lam=1.0))):
        he = make_backend('emulated', CFG['he'], seed=3)
        s = make_scheme(name, M, he=he, order=priority_order([1536, 3]), K=K, **kw)
        up = len(msgpack.packb(to_wire(s.protect(xs[0], 1, 0, np.random.default_rng(0)), he), use_bin_type=True))
        want = s.sizes()['upload']
        assert want <= up <= want + 400, (name, up, want)      # chênh lệch chỉ là tiêu đề msgpack


def test_payload_does_not_leak_noise_sd():
    xs = data()
    _, pays, _ = system('fas', xs, p=0.1, lam=3.0)
    assert 'sd' not in pays[0] and set(pays[0]) == {'he', 'plain'}


def test_ciphertext_counts():
    he = make_backend('emulated', CFG['he'])
    assert make_scheme('ckks_full', M, he=he).sizes()['n_ct'] == 1
    assert make_scheme('fas', M, he=he, p=0.5).sizes()['n_ct'] == 1       # 770 giá trị vẫn 1 ciphertext
    big = 198723
    assert make_scheme('ckks_full', big, he=he).sizes()['n_ct'] == 49
    assert make_scheme('fas', big, he=he, p=0.1).sizes()['n_ct'] == 5


def test_priority_order_bias_first():
    o = priority_order([1536, 3])
    assert list(o[:3]) == [1536, 1537, 1538] and sorted(o) == list(range(1539))


def test_openfhe_if_available():
    """OpenFHE thật, hai bên trong MỘT tiến trình (MKCKKS). Phần qua mạng: tests/secure_fl/test_openfhe.py."""
    try:
        import openfhe  # noqa: F401
    except ImportError:
        print('  (bỏ qua: không có OpenFHE trên máy này)')
        return
    from secure_fl.security.mkckks import MKCKKS
    xs = data()
    m = MKCKKS(CFG['he'])
    a, b = m.encrypt(list(xs[0])), m.encrypt(list(xs[1]))
    ct = m.add(a, b)
    out = m.fuse([m.partial_decrypt(ct, 0), m.partial_decrypt(ct, 1)], M)
    assert np.abs(out - sum(xs)).max() < 1e-6, np.abs(out - sum(xs)).max()


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
    sys.exit(1 if fails else 0)
