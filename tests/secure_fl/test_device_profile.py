"""Kiểm thử cấu hình giả lập Pi 4 (mục `device` trong config.yaml) nối đúng vào docker-compose — chạy: python tests/secure_fl/test_device_profile.py"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))

from secure_fl import settings

COMPOSE = yaml.safe_load(open(ROOT / 'docker' / 'docker-compose.yml', encoding='utf-8'))


def test_device_section():
    dev = settings.load()['device']
    assert dev['profile'] == 'raspberry_pi_4b'
    assert float(dev['cpus']) <= 4                      # Pi 4 có 4 nhân
    from secure_fl.devicelimit import parse_mem
    assert 0 < parse_mem(dev['mem_limit']) <= 8 * 2**30                                         # Pi 4 tối đa 8 GB; '512m', '4g' đều hợp lệ


def test_compose_reads_device_values():
    for c in ('client1', 'client2'):
        svc = COMPOSE['services'][c]
        assert '${CLIENT_CPUS' in str(svc['cpus']) and '${CLIENT_MEM' in str(svc['mem_limit']), c      # không hard-code trong compose
    assert 'cpus' not in COMPOSE['services']['bs']                                                     # BS không phải thiết bị biên: không giới hạn


def test_compose_commands_well_formed():
    """Lỗi từng gặp: sửa compose làm mất dấu cách -> `--dev 1--arm` (container client thoát mã 2)."""
    import re
    for i, c in ((1, 'client1'), (2, 'client2')):
        cmd = COMPOSE['services'][c]['command']
        assert f'--dev {i} --arm ${{ARM}}' in cmd, cmd
        assert not re.search(r'\d--[a-z]', cmd), cmd


def test_compose_defaults_match_config():
    dev = settings.load()['device']
    for c in ('client1', 'client2'):
        svc = COMPOSE['services'][c]
        assert f':-{dev["cpus"]}}}' in svc['cpus'] and f':-{dev["mem_limit"]}}}' in svc['mem_limit'], c    # mặc định trong compose = config, chạy compose tay vẫn đúng


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
