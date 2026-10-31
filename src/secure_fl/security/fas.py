import numpy as np

from .base import Scheme
from .perm import perm_for, unshuffle


class Fas(Scheme):
    """Lock B (FAS): p đầu theo thứ tự ưu tiên -> xMK-CKKS; phần còn lại + nhiễu N(0,(λ·RMS)²) rồi xáo bằng π_t.
    key_holder='devices': K chỉ ở 2 thiết bị, BS cộng mù. 'bs': BS cũng có K (FAS gốc) nên giải xáo từng payload."""
    name = 'fas'
    needs_decrypt = True

    def __init__(self, M, he=None, p=0.1, lam=3.0, order=None, K=b'\0' * 32, key_holder='devices', **kw):
        super().__init__(M, he)
        self.p, self.lam, self.K, self.key_holder = float(p), float(lam), K, key_holder
        order = np.arange(self.M) if order is None else np.asarray(order)
        m = int(round(self.p * self.M))
        self.idx_he, self.idx_plain = order[:m], order[m:]

    def protect(self, x, t, dev, rng):
        x = np.asarray(x, np.float64)
        he = self.he.encrypt(x[self.idx_he]) if len(self.idx_he) else None
        plain = x[self.idx_plain].copy()
        sd = self.lam * float(np.sqrt(np.mean(plain ** 2))) if self.lam > 0 and len(plain) else 0.0
        if sd > 0:
            plain += rng.normal(0.0, sd, len(plain))
        self.info = {'sd': sd}                      # chỉ ở client; gói gửi đi KHÔNG có sd (sẽ lộ RMS của cập nhật)
        pi = perm_for(self.K, t, len(plain))
        return {'he': he, 'plain': plain[pi].astype(np.float32)}

    def aggregate(self, payloads):
        s = payloads[0]['plain'].copy()
        for p in payloads[1:]:
            s += p['plain']
        he = payloads[0]['he']
        for p in payloads[1:]:
            he = self.he.add(he, p['he']) if he is not None else None
        return {'he': he, 'plain': s}

    def client_share(self, csum, party):
        if csum['he'] is None:
            return None
        return {'share': self.he.partial_decrypt(csum['he'], party)}

    def bs_fuse(self, csum, shares):
        dec = None
        if csum['he'] is not None:
            dec = np.asarray(self.he.fuse(csum['he'], [s['share'] for s in shares], len(self.idx_he)))
        return {'dec': dec, 'plain': csum['plain']}

    def client_finish(self, agg, t):
        out = np.zeros(self.M)
        if agg['dec'] is not None:
            out[self.idx_he] = agg['dec']
        out[self.idx_plain] = unshuffle(agg['plain'], perm_for(self.K, t, len(self.idx_plain))).astype(np.float64)
        return out

    def bs_view(self, payload, t):
        v = payload['plain'].astype(np.float64)
        if self.key_holder == 'bs':
            v = unshuffle(payload['plain'], perm_for(self.K, t, len(self.idx_plain))).astype(np.float64)
        # không có K: BS không biết vị trí, chỉ có thể đặt theo thứ tự nhận được
        return v, self.idx_plain

    def sizes(self):
        s = self.he.sizes(len(self.idx_he))
        pl = 4 * len(self.idx_plain)
        return {'upload': s['ct'] + pl, 'csum': s['ct'] + pl, 'share': s['share'], 'aggregate': 4 * self.M, 'n_ct': s['n_ct']}
