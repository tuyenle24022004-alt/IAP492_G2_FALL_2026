"""CKKS đa bên của OpenFHE (threshold 2-of-2) dùng làm xMK-CKKS. Chỉ import được trên Linux x86_64 có `openfhe` (chạy trong container docker/).

Tham số CKKS lấy từ src/secure_fl/config.yaml mục `he`: ring 8192, 4096 slot, độ sâu nhân 0 (hệ thống chỉ CỘNG), scale 2^50,
firstMod 60, HEStd_128_classic. Hai bên trong cùng một tiến trình: dùng cho kiểm thử và đo chi phí; trong bản 4 container
mỗi thiết bị giữ khóa bí mật của mình và BS chỉ có khóa công khai (phần dựng sau).

GIỚI HẠN đã biết: không đặt SetMultipartyMode nên OpenFHE dùng nhiễu mặc định FIXED_NOISE_MULTIPARTY ở phần giải mã từng bên
(nhiễu nhỏ). NOISE_FLOODING_MULTIPARTY che khóa bí mật tốt hơn trước BS tò mò nhưng cần modulus lớn hơn (ciphertext to hơn,
đổi tham số CKKS) nên không dùng — phải nêu trong phần hạn chế của báo cáo.
"""
import math
import os
import tempfile

import numpy as np


def n_ct(n_values, slots):
    """Số ciphertext cần để mã hóa n_values số thực (mỗi ciphertext chứa `slots` giá trị)."""
    return math.ceil(n_values / slots) if n_values > 0 else 0


def make_context(he):
    from openfhe import CCParamsCKKSRNS, FIXEDMANUAL, GenCryptoContext, PKESchemeFeature, SecurityLevel
    p = CCParamsCKKSRNS()
    p.SetMultiplicativeDepth(0)
    p.SetScalingModSize(int(he['scale_bits']))
    p.SetFirstModSize(int(he['first_mod_bits']))
    p.SetRingDim(int(he['ring_dim']))
    p.SetBatchSize(int(he['slots']))
    p.SetSecurityLevel(SecurityLevel.HEStd_128_classic)
    p.SetScalingTechnique(FIXEDMANUAL)
    cc = GenCryptoContext(p)
    for f in (PKESchemeFeature.PKE, PKESchemeFeature.KEYSWITCH, PKESchemeFeature.LEVELEDSHE, PKESchemeFeature.MULTIPARTY):
        cc.Enable(f)
    return cc


def ser_size(obj):
    """Số byte khi Serialize (BINARY) một đối tượng OpenFHE (ciphertext, phần giải mã, khóa)."""
    from openfhe import BINARY, SerializeToFile
    with tempfile.TemporaryDirectory() as d:
        fn = os.path.join(d, 'o.bin')
        SerializeToFile(fn, obj, BINARY)
        return os.path.getsize(fn)


class MKCKKS:
    def __init__(self, he, n_parties=2):
        """Bên 0 KeyGen; mỗi bên sau MultipartyKeyGen nối tiếp trên khóa công khai của bên trước.
        Khóa công khai của bên cuối là khóa CHUNG: mã hóa bằng nó thì phải đủ mọi bên mới giải mã được."""
        self.slots = int(he['slots'])
        self.cc = make_context(he)
        self.keys = [self.cc.KeyGen()]
        for _ in range(1, n_parties):
            self.keys.append(self.cc.MultipartyKeyGen(self.keys[-1].publicKey))
        self.pk = self.keys[-1].publicKey

    def encrypt(self, x):
        """Cắt x thành từng đoạn `slots` giá trị, mã hóa bằng khóa chung -> danh sách ciphertext."""
        S = self.slots
        return [self.cc.Encrypt(self.pk, self.cc.MakeCKKSPackedPlaintext(list(x[i:i + S]))) for i in range(0, len(x), S)]

    def add(self, a, b):
        """Cộng đồng cấu từng cặp ciphertext, không cần khóa bí mật (việc của BS)."""
        return [self.cc.EvalAdd(x, y) for x, y in zip(a, b)]

    def partial_decrypt(self, cts, party):
        """Phần giải mã của một bên (bên 0 = Lead, còn lại = Main). Một phần đơn lẻ không lộ bản rõ."""
        f = self.cc.MultipartyDecryptLead if party == 0 else self.cc.MultipartyDecryptMain
        return f(cts, self.keys[party].secretKey)

    def fuse(self, shares, n):
        """Ghép phần giải mã của mọi bên -> n giá trị thực đầu tiên (bỏ slot đệm)."""
        out = []
        for j in range(len(shares[0])):
            pt = self.cc.MultipartyDecryptFusion([s[j] for s in shares])
            pt.SetLength(self.slots)
            out.extend(pt.GetRealPackedValue())
        return np.array(out[:n])
