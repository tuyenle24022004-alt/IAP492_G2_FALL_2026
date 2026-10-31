"""Kiểm thử công tắc lock.attack_enabled (đánh giá tấn công tạm tắt) và hàm chọn phương án — chạy: python tests/secure_fl/test_attack_switch.py"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))

from secure_fl.experiments import analyze as AN

CFG = yaml.safe_load(open(ROOT / 'src' / 'secure_fl' / 'config.yaml', encoding='utf-8'))

FL_ROWS = [{'arm': 'none', 'gate1': '—'}, {'arm': 'ckks_full', 'gate1': 'có'}, {'arm': 'fas_lam0.1', 'gate1': 'có'},
           {'arm': 'fas_lam1', 'gate1': 'không'}, {'arm': 'fasbs_lam0.1', 'gate1': 'có'}]
COST = {a: {'up_total': up, 'round': 1.0} for a, up in
        {'none': 6156, 'ckks_full': 132500, 'fas_lam0.1': 138000, 'fas_lam1': 138000, 'fasbs_lam0.1': 138000}.items()}


def test_default_is_off():
    assert CFG['lock']['attack_enabled'] is False
    assert AN.attack_on(CFG['lock']) is False
    assert AN.attack_on({}) is False                       # file kết quả/cấu hình cũ không có cờ: coi như tắt
    assert AN.attack_on({'attack_enabled': True}) is True


def test_select_without_attack_uses_gate1_only():
    rows, best = AN.select_best(FL_ROWS, None, COST)
    assert [r[0] for r in rows] == ['ckks_full', 'fas_lam0.1', 'fas_lam1']      # none, fasbs không phải ứng viên
    assert all(r[2] is None for r in rows)                                       # không có cổng 2
    assert [r[4] for r in rows] == [True, True, False]
    assert best == 'ckks_full'                                                   # ít byte nhất trong các phương án qua cổng 1


def test_select_with_attack_still_works():
    att = {'ckks_full': {'gate2': 'không'}, 'fas_lam0.1': {'gate2': 'có'}, 'fas_lam1': {'gate2': 'có'}}
    rows, best = AN.select_best(FL_ROWS, att, COST)
    assert [r[4] for r in rows] == [False, True, False]
    assert best == 'fas_lam0.1'


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
