"""Giao diện chung của ba chế độ bảo vệ (docs/kien_truc_testbed_moi.md mục 4), chia theo VAI TRÒ để chạy qua mạng.

Client (có khóa bí mật, K):  protect(x, t, dev, rng) -> payload ; client_share(csum, party) -> share ; client_finish(agg, t) -> tổng (mô hình toàn cục mới)
BS (không có khóa, không có K): aggregate(payloads) -> csum ; bs_fuse(csum, shares) -> agg ; bs_view(payload, t) -> thứ BS đọc được
x = vector cần bảo vệ của client (trọng số mô hình) đã nhân n_k/n, nên tổng của hai client chính là FedAvg. Tin nhắn trên dây: to_wire / from_wire.
`finish(csum, t)` ghép cả ba bước trong MỘT tiến trình (dùng cho test).
"""
import numpy as np

from secure_fl.common.messages import pack_array, unpack_array


def priority_order(block_sizes):
    """Thứ tự ưu tiên mã hóa: các khối tham số (weight, bias, ...) từ khối CUỐI về khối đầu, mỗi khối theo chỉ số tăng.
    Lớp phân loại 1.539 tham số = [weight 1.536, bias 3] -> bias trước rồi weight. Giả định cố định, không theo độ lớn."""
    starts = np.cumsum([0] + list(block_sizes))
    return np.concatenate([np.arange(starts[i], starts[i + 1]) for i in reversed(range(len(block_sizes)))])


def to_wire(d, he):
    """dict -> dict chỉ gồm bytes/số để msgpack: 'he' = ciphertext, 'share' = phần giải mã (do backend HE), còn lại mảng float32."""
    out = {}
    for k, v in d.items():
        if v is None:
            out[k] = None
        elif k == 'he':
            out[k] = he.ct_to_bytes(v)
        elif k == 'share':
            out[k] = he.share_to_bytes(v)
        else:
            out[k] = pack_array(v, np.float32)
    return out


def from_wire(d, he):
    out = {}
    for k, v in d.items():
        if v is None:
            out[k] = None
        elif k == 'he':
            out[k] = he.ct_from_bytes(v)
        elif k == 'share':
            out[k] = he.share_from_bytes(v)
        else:
            out[k] = np.array(unpack_array(v))
    return out


class Scheme:
    name = ''
    needs_decrypt = False               # có lượt CSUM -> PARTIAL_DEC -> AGGREGATE không

    def __init__(self, M, he=None, **kw):
        self.M = int(M)
        self.he = he
        self.info = {}                  # thông tin CỤC BỘ của client (vd. độ lệch chuẩn nhiễu), KHÔNG gửi lên dây

    def protect(self, x, t, dev, rng):
        raise NotImplementedError

    def aggregate(self, payloads):
        raise NotImplementedError

    def client_share(self, csum, party):
        return None

    def bs_fuse(self, csum, shares):
        raise NotImplementedError

    def client_finish(self, agg, t):
        raise NotImplementedError

    def bs_view(self, payload, t):
        """(values, idx): giá trị BS đọc được và vị trí mà BS TIN là của chúng (None nếu BS không đọc được gì)."""
        raise NotImplementedError

    def sizes(self):
        """Byte tải trọng mỗi vòng cho MỘT client: upload, csum (xuống), share (PARTIAL_DEC lên), aggregate (xuống)."""
        raise NotImplementedError

    def finish(self, csum, t):
        shares = [self.client_share(csum, p) for p in (0, 1)] if self.needs_decrypt else []
        return self.client_finish(self.bs_fuse(csum, shares), t)
