"""Hoán vị bí mật π_t = PCG64(HKDF-SHA256(K, "perm" ‖ t))."""
import hashlib
import hmac

import numpy as np


def hkdf_sha256(key, info, length=32, salt=b''):
    prk = hmac.new(salt or b'\0' * 32, key, hashlib.sha256).digest()
    out, block = b'', b''
    for i in range((length + 31) // 32):
        block = hmac.new(prk, block + info + bytes([i + 1]), hashlib.sha256).digest()
        out += block
    return out[:length]


def perm_for(K, t, n):
    seed = hkdf_sha256(K, b'perm' + int(t).to_bytes(8, 'big'))
    return np.random.default_rng(int.from_bytes(seed, 'big')).permutation(n)


def unshuffle(shuffled, pi):
    out = np.empty_like(shuffled)
    out[pi] = shuffled
    return out
