"""Hai backend cho xMK-CKKS, cùng giao diện: encrypt / add / partial_decrypt / fuse (+ đóng gói bytes để đi qua mạng + thiết lập khóa).

- `EmulatedHE`: KHÔNG mã hóa gì, chỉ mô hình hóa sai số CKKS (nhiễu Gauss nhỏ ở mã hóa và ở giải mã) và ĐỆM gói đúng cỡ
  ciphertext/phần giải mã đã đo (config `he.ct_bytes`, `he.share_bytes`) để byte trên dây sát thật. Chạy được trên Windows.
  Bản "ciphertext" chứa giá trị ĐỌC ĐƯỢC, nên mọi đánh giá bảo mật phải bỏ qua nó (chỉ tin vào `bs_view`).
  Chỉ trả lời "sai số CKKS ảnh hưởng độ chính xác FL thế nào"; KHÔNG chứng minh mã hóa đúng, KHÔNG chứng minh bảo mật.
- `OpenFheHE`: OpenFHE thật, đa khóa 2-of-2, mỗi tiến trình một vai trò (docs: CLAUDE.md mục 3):
    role='bs'     : tạo CryptoContext, cộng ciphertext (EvalAdd), ghép 2 phần giải mã (Fusion). KHÔNG có khóa bí mật.
    role='client' : giữ khóa bí mật của mình (không bao giờ rời tiến trình), mã hóa bằng khóa công khai chung, giải mã từng phần.
  Chỉ chạy được trên Linux x86_64 có `openfhe` (container docker/). Thiết lập khóa một lần (setup_bs / setup_client):
    BS tạo context -> HE_CONTEXT cho 2 client; client1 KeyGen -> pk1 (HE_PK1, qua BS) -> client2 MultipartyKeyGen(pk1)
    -> pk chung (HE_PK, qua BS về client1). Port từ mã cũ đã từng test trong container (git 823282b: src/common/crypto_setup.py).
  CHƯA chạy thử trên máy này (không có OpenFHE); test: tests/secure_fl/test_openfhe.py chạy trong container.
"""
import math
import struct

import msgpack
import numpy as np


class EmulatedHE:
    real = False

    def __init__(self, he_cfg, seed=0, role='bs', dev=None):
        self.slots = int(he_cfg['slots'])
        self.ct_bytes = int(he_cfg['ct_bytes'])
        self.share_bytes = int(he_cfg['share_bytes'])
        # sai số tổng sau giải mã = sqrt(2·σ_enc² + σ_dec²) = error_sigma
        self.sigma = float(he_cfg['error_sigma']) / math.sqrt(3)
        self.rng = np.random.default_rng([int(seed), 7])

    def setup_bs(self, conns):
        pass

    def setup_client(self, sock, dev):
        pass

    def n_ct(self, n):
        return math.ceil(n / self.slots) if n > 0 else 0

    def encrypt(self, x):
        x = np.asarray(x, np.float64)
        return {'v': x + self.rng.normal(0.0, self.sigma, x.shape), 'n': len(x)}

    def add(self, a, b):
        return {'v': a['v'] + b['v'], 'n': a['n']}

    def partial_decrypt(self, ct, party):
        return {'n': ct['n'], 'party': party}

    def fuse(self, ct, shares, n):
        return ct['v'] + self.rng.normal(0.0, self.sigma, ct['v'].shape)

    def sizes(self, n):
        k = self.n_ct(n)
        return {'ct': k * self.ct_bytes, 'share': k * self.share_bytes, 'n_ct': k}

    # --- đóng gói để gửi qua mạng: dữ liệu thật + đệm 0 cho đủ cỡ ciphertext/phần giải mã đã đo ---
    def ct_to_bytes(self, ct):
        body = struct.pack('>I', ct['n']) + np.ascontiguousarray(ct['v'], '<f8').tobytes()
        return body.ljust(max(len(body), self.n_ct(ct['n']) * self.ct_bytes), b'\0')

    def ct_from_bytes(self, b):
        n = struct.unpack('>I', b[:4])[0]
        return {'v': np.frombuffer(b[4:4 + 8 * n], '<f8').copy(), 'n': n}

    def share_to_bytes(self, sh):
        body = struct.pack('>II', sh['n'], sh['party'])
        return body.ljust(self.n_ct(sh['n']) * self.share_bytes, b'\0')

    def share_from_bytes(self, b):
        n, party = struct.unpack('>II', b[:8])
        return {'n': n, 'party': party}


def _first(r):
    """Một số bản openfhe-python trả (đối tượng, ok), số khác trả đối tượng."""
    return r[0] if isinstance(r, tuple) else r


class OpenFheHE:
    real = True

    def __init__(self, he_cfg, seed=0, role='bs', dev=None):
        from . import mkckks as mod            # import muộn: chỉ máy có OpenFHE mới import được
        import openfhe as of
        self.mod, self.of = mod, of
        self.he_cfg = he_cfg
        self.slots = int(he_cfg['slots'])
        self.role, self.dev = role, dev
        self.cc = None
        self._sk = None                        # khóa bí mật — chỉ ở client
        self.pk = None                         # khóa công khai chung

    # ---------- serialize ----------
    def _ser(self, obj):
        return self.of.Serialize(obj, self.of.BINARY)

    def _load_ct(self, b):
        return _first(self.of.DeserializeCiphertextString(b, self.of.BINARY))

    # ---------- thiết lập khóa phân tán ----------
    def setup_bs(self, conns):
        """BS: tạo context, phát cho 2 client, chuyển tiếp pk1 (client1 -> client2) và pk chung (client2 -> client1)."""
        from secure_fl.common import messages as Msg
        self.cc = self.mod.make_context(self.he_cfg)
        cc_bytes = self._ser(self.cc)
        for d in (1, 2):
            Msg.send_msg(conns[d], Msg.HE_CONTEXT, {'cc': cc_bytes})
        m, _ = Msg.recv_msg(conns[1])
        assert m['type'] == Msg.HE_PK1
        Msg.send_msg(conns[2], Msg.HE_PK1, {'pk': m['pk']})
        m, _ = Msg.recv_msg(conns[2])
        assert m['type'] == Msg.HE_PK
        Msg.send_msg(conns[1], Msg.HE_PK, {'pk': m['pk']})

    def setup_client(self, sock, dev):
        """Client: nhận context; client1 KeyGen và gửi pk1; client2 MultipartyKeyGen(pk1) và gửi pk chung."""
        from secure_fl.common import messages as Msg
        of = self.of
        m, _ = Msg.recv_msg(sock)
        assert m['type'] == Msg.HE_CONTEXT
        self.cc = _first(of.DeserializeCryptoContextString(m['cc'], of.BINARY))
        if dev == 1:
            kp = self.cc.KeyGen()
            self._sk = kp.secretKey
            Msg.send_msg(sock, Msg.HE_PK1, {'pk': self._ser(kp.publicKey)})
            m, _ = Msg.recv_msg(sock)
            assert m['type'] == Msg.HE_PK
            self.pk = _first(of.DeserializePublicKeyString(m['pk'], of.BINARY))
        else:
            m, _ = Msg.recv_msg(sock)
            assert m['type'] == Msg.HE_PK1
            pk1 = _first(of.DeserializePublicKeyString(m['pk'], of.BINARY))
            kp = self.cc.MultipartyKeyGen(pk1)
            self._sk = kp.secretKey
            self.pk = kp.publicKey
            Msg.send_msg(sock, Msg.HE_PK, {'pk': self._ser(kp.publicKey)})

    # ---------- phép toán ----------
    def n_ct(self, n):
        return self.mod.n_ct(n, self.slots)

    def encrypt(self, x):
        cc, S = self.cc, self.slots
        x = np.asarray(x, np.float64)
        cts = [cc.Encrypt(self.pk, cc.MakeCKKSPackedPlaintext([float(v) for v in x[i:i + S]])) for i in range(0, len(x), S)]
        return {'cts': cts, 'n': len(x)}

    def add(self, a, b):
        return {'cts': [self.cc.EvalAdd(x, y) for x, y in zip(a['cts'], b['cts'])], 'n': a['n']}

    def partial_decrypt(self, ct, party):
        f = self.cc.MultipartyDecryptLead if party == 0 else self.cc.MultipartyDecryptMain
        return {'sh': f(ct['cts'], self._sk), 'n': ct['n']}

    def fuse(self, ct, shares, n):
        out = []
        for j in range(len(shares[0]['sh'])):
            pt = self.cc.MultipartyDecryptFusion([s['sh'][j] for s in shares])
            pt.SetLength(self.slots)
            out.extend(pt.GetRealPackedValue())
        return np.array(out[:n], dtype=np.float64)

    def sizes(self, n):
        """Chỉ số ciphertext (byte thật lấy từ tin nhắn trên dây, không ước lượng ở đây)."""
        return {'ct': 0, 'share': 0, 'n_ct': self.n_ct(n)}

    # ---------- đóng gói bytes ----------
    def ct_to_bytes(self, ct):
        return msgpack.packb({'n': ct['n'], 'c': [self._ser(c) for c in ct['cts']]}, use_bin_type=True)

    def ct_from_bytes(self, b):
        d = msgpack.unpackb(b, raw=False)
        return {'cts': [self._load_ct(x) for x in d['c']], 'n': d['n']}

    def share_to_bytes(self, sh):
        return msgpack.packb({'n': sh['n'], 'c': [self._ser(c) for c in sh['sh']]}, use_bin_type=True)

    def share_from_bytes(self, b):
        d = msgpack.unpackb(b, raw=False)
        return {'sh': [self._load_ct(x) for x in d['c']], 'n': d['n']}


def make_backend(name, he_cfg, seed=0, role='bs', dev=None):
    if name == 'openfhe':
        return OpenFheHE(he_cfg, seed, role, dev)
    if name == 'emulated':
        return EmulatedHE(he_cfg, seed, role, dev)
    raise ValueError(f'backend phải là emulated | openfhe, nhận {name}')
