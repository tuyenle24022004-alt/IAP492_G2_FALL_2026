"""Công thức MỘT NGUỒN: số tham số -> byte gửi lên -> số gói -> thời gian theo tốc độ kênh. Hàm thuần (chỉ math và numpy).

Dùng để DỰ KIẾN trước khi chạy thật (đặt hạn chờ, ước thời gian) và để ĐỐI CHIẾU với số đo; kết quả báo cáo là số ĐO, không phải số ở đây.

    UPLOAD, PARTIAL_DEC (byte khung)   không mã hóa: 4*M + tiêu đề ;  CKKS: n_ct*ct_bytes + tiêu đề, n_ct*share_bytes   (n_ct = ceil(M/slots))
    t_k = byte_k / R_k(t)   (R_k tính bằng byte/s)      T_pha = max(t_1, t_2)      T_lên = T_UPLOAD + T_PARTIAL_DEC
"""
import math

import numpy as np


def n_ct(n_params, slots):
    """Số ciphertext cần để chứa n_params giá trị (mỗi ciphertext chứa `slots` ô)."""
    return math.ceil(n_params / slots)


def frame_bytes(arm, n_params, he, overhead):
    """(UPLOAD, PARTIAL_DEC): byte KHUNG một client gửi lên trong một vòng. PARTIAL_DEC = 0 nếu arm không có giải mã."""
    if arm == 'none':
        return 4 * n_params + overhead['none'], 0
    if arm == 'ckks_full':
        k = n_ct(n_params, he['slots'])
        return k * he['ct_bytes'] + overhead['ckks_full'], k * he['share_bytes']
    raise ValueError(f'arm không biết: {arm} (chỉ có none, ckks_full)')


def packets(frame, mss):
    """Số gói TCP để chở một khung."""
    return math.ceil(frame / mss)


def channel_rates(channel, n):
    """Mảng (n, 2) tốc độ byte/s của hai thiết bị ở các vòng 0..n-1 (một mẫu kênh mỗi vòng)."""
    return np.array([channel.round(t).rate_bytes_per_s for t in range(n)], float)


def phase_time(rates, frame):
    """Thời gian một lần gửi mỗi vòng (thiết bị chậm hơn quyết định); frame = 0 -> 0."""
    if not frame:
        return np.zeros(len(rates))
    return (frame / rates).max(axis=1)


def phase_spread(rates, frame):
    """Chênh lệch thời gian gửi giữa hai thiết bị mỗi vòng = thời gian thiết bị nhanh hơn phải đứng chờ."""
    if not frame:
        return np.zeros(len(rates))
    t = frame / rates
    return t.max(axis=1) - t.min(axis=1)


def predict(channel, upload, share, n_transmissions):
    """Dự kiến cho một lượt chạy gồm n_transmissions lần truyền (= vòng 0 + số vòng)."""
    r = channel_rates(channel, n_transmissions)
    t_up, t_pd = phase_time(r, upload), phase_time(r, share)
    wait = np.maximum(phase_spread(r, upload), phase_spread(r, share))
    return {'t_upload': t_up, 't_partial_dec': t_pd, 't_len': t_up + t_pd, 'total_s': float((t_up + t_pd).sum()),
            'wait_s': wait, 'max_wait_s': float(wait.max()), 'min_rate_Bps': float(r.min())}


def timeout_for(max_wait_s, margin, minimum_s):
    """Hạn chờ một tin (lock.timeout_s) cho lượt chạy: lớn hơn thời gian chờ dài nhất nhân hệ số an toàn, cộng 10 phút cho phần tính toán."""
    return int(math.ceil(max(float(minimum_s), margin * max_wait_s + 600.0)))
