import numpy as np

from .base import Scheme


class CkksFull(Scheme):
    """Lock A: mã hóa 100% bằng xMK-CKKS. BS chỉ thấy ciphertext; sau khi ghép phần giải mã BS biết tổng."""
    name = 'ckks_full'
    needs_decrypt = True

    def protect(self, x, t, dev, rng):
        return {'he': self.he.encrypt(x)}

    def aggregate(self, payloads):
        s = payloads[0]['he']
        for p in payloads[1:]:
            s = self.he.add(s, p['he'])
        return {'he': s}

    def client_share(self, csum, party):
        return {'share': self.he.partial_decrypt(csum['he'], party)}

    def bs_fuse(self, csum, shares):
        return {'dec': np.asarray(self.he.fuse(csum['he'], [s['share'] for s in shares], self.M))}

    def client_finish(self, agg, t):
        return agg['dec'].astype(np.float64)

    def bs_view(self, payload, t):
        return None, None

    def sizes(self):
        s = self.he.sizes(self.M)
        return {'upload': s['ct'], 'csum': s['ct'], 'share': s['share'], 'aggregate': 4 * self.M, 'n_ct': s['n_ct']}
