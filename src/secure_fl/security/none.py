import numpy as np

from .base import Scheme


class NoneScheme(Scheme):
    """Không lock: gửi trọng số rõ (float32). BS thấy trọng số từng client; không có lượt giải mã."""
    name = 'none'

    def protect(self, x, t, dev, rng):
        return {'plain': np.asarray(x, np.float32)}

    def aggregate(self, payloads):
        s = payloads[0]['plain'].copy()
        for p in payloads[1:]:
            s += p['plain']
        return {'plain': s}

    def bs_fuse(self, csum, shares):
        return csum

    def client_finish(self, agg, t):
        return agg['plain'].astype(np.float64)

    def bs_view(self, payload, t):
        return payload['plain'].astype(np.float64), np.arange(self.M)

    def sizes(self):
        b = 4 * self.M
        return {'upload': b, 'csum': 0, 'share': 0, 'aggregate': b, 'n_ct': 0}
