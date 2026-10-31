"""Danh sách "arm": mỗi arm là MỘT lượt FL hoàn chỉnh với một cấu hình bảo vệ cố định.
Dùng chung cho tiến trình BS, client và bộ điều phối để cả ba hiểu cùng một tên arm."""


def arm_list(lock):
    # none_rerun = chạy lại none y hệt: mốc nhiễu nền (PyTorch không tất định) để đọc "ảnh dự đoán khác none"
    arms = [('none', 'none', {}), ('none_rerun', 'none', {}), ('ckks_full', 'ckks_full', {})]
    arms += [(f'fas_lam{lam:g}', 'fas', {'p': lock['fas_p'], 'lam': lam}) for lam in lock['fas_lams']]
    # mốc yếu về bảo mật: FAS gốc, BS cũng giữ khóa xáo K
    arms += [(f'fasbs_lam{lam:g}', 'fas', {'p': lock['fas_p'], 'lam': lam, 'key_holder': 'bs'})
             for lam in lock.get('fas_bs_lams', [])]
    return arms


def resolve(name, lock):
    """name -> (kind, kwargs); lỗi nếu tên không có trong cấu hình."""
    for n, kind, kw in arm_list(lock):
        if n == name:
            return kind, kw
    raise ValueError(f'arm {name} không có trong config lock (có: {[a[0] for a in arm_list(lock)]})')


def bs_has_key(name, lock):
    """Chỉ biến thể FAS gốc (fasbs_*) cho BS giữ khóa xáo K; mọi arm khác BS KHÔNG có K."""
    kind, kw = resolve(name, lock)
    return kind == 'fas' and kw.get('key_holder') == 'bs'
