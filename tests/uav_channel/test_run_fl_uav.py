"""Kiểm thử bộ điều phối run_fl_uav.py và docker-compose.uav.yml KHÔNG cần Docker: bản sao config, biến môi trường, kế hoạch, cú pháp compose, dry-run.
Chạy: python tests/uav_channel/test_run_fl_uav.py   (nếu có Docker thì kiểm thêm `docker compose config` để bắt lỗi cú pháp/biến thật)"""
import copy
import hashlib
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))

from uav_channel import run_fl_uav as R

CFG = yaml.safe_load(open(R.CONFIG, encoding='utf-8'))
FLQ = CFG['fl_qua_kenh']
COMPOSE = yaml.safe_load(open(R.COMPOSE, encoding='utf-8'))
MODEL_CFG = ROOT / 'src' / 'model' / 'config.yaml'
SFL_CFG = ROOT / 'src' / 'secure_fl' / 'config.yaml'


def digest(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def test_config_copies():
    before = (digest(MODEL_CFG), digest(SFL_CFG))
    with tempfile.TemporaryDirectory() as d:
        flq = dict(FLQ, local_epochs=3)
        cdir = R.write_config_copies(d, flq, rounds=7, timeout_s=12345)
        model = yaml.safe_load(open(cdir / 'model_config.yaml', encoding='utf-8'))
        sfl = yaml.safe_load(open(cdir / 'secure_fl_config.yaml', encoding='utf-8'))
    want_model = yaml.safe_load(open(MODEL_CFG, encoding='utf-8'))
    want_model['fl']['rounds'], want_model['fl']['local_epochs'] = 7, 3
    want_sfl = yaml.safe_load(open(SFL_CFG, encoding='utf-8'))
    want_sfl['lock']['timeout_s'] = 12345
    assert model == want_model, 'bản sao config model chỉ được khác fl.rounds và fl.local_epochs'
    assert sfl == want_sfl, 'bản sao config secure_fl chỉ được khác lock.timeout_s'
    assert (digest(MODEL_CFG), digest(SFL_CFG)) == before, 'file config thật bị đổi'
    print('[TEST] A. Bản sao config: model chỉ đổi fl.rounds (7) và fl.local_epochs (3); secure_fl chỉ đổi lock.timeout_s (12345); file thật không đổi')


def test_build_env():
    dev = {'cpus': 1.6, 'mem_limit': '4g'}
    env = R.build_env('C:\\x\\run', 'direct_noma', 'ckks_full', FLQ, 4, dev)
    assert env['ARM'] == 'ckks_full' and env['CHANNEL'] == 'direct_noma' and env['ROUNDS'] == '4' and env['SEED'] == str(FLQ['seed'])
    assert env['BACKEND'] == 'openfhe' and env['MODEL'] == FLQ['model'] and env['RUN_DIR'] == 'C:/x/run'
    assert (env['PORT1'], env['PORT2'], env['BS_PORT']) == (str(FLQ['ports'][0]), str(FLQ['ports'][1]), str(FLQ['bs_port']))
    assert env['CLIENT_CPUS'] == '1.6' and env['CLIENT_MEM'] == '4g'
    print('[TEST] B. Biến môi trường cho compose đúng (ARM, CHANNEL, ROUNDS, BACKEND=openfhe, cổng, giới hạn Pi 4)')


def test_plan_relations():
    he = yaml.safe_load(open(SFL_CFG, encoding='utf-8'))['he']
    plans = {(c, a): R.plan_run(c, a, CFG, FLQ, he, 1539, 4) for c in ('uav_noma_pc', 'direct_noma') for a in ('none', 'ckks_full')}
    for (c, a), p in plans.items():
        assert p['n_transmissions'] == 5 and p['timeout_s'] >= FLQ['timeout_min_s'] and p['limit_s'] > p['predicted_total_s']
        assert (p['share_B'] == 0) == (a == 'none')
    assert plans[('direct_noma', 'ckks_full')]['predicted_total_s'] > 100 * plans[('uav_noma_pc', 'ckks_full')]['predicted_total_s']
    assert plans[('direct_noma', 'ckks_full')]['timeout_s'] >= plans[('direct_noma', 'none')]['timeout_s']
    print('[TEST] C. Kế hoạch: 5 lần truyền cho rounds=4; hạn chờ không thấp hơn mặc định; không UAV + CKKS dài gấp trăm lần có UAV; none không có PARTIAL_DEC. '
          + '; '.join(f'{c}/{a}: dự kiến {p["predicted_total_s"] / 3600:.2f} giờ, hạn chờ {p["timeout_s"]}s' for (c, a), p in plans.items()))


def test_compose_static():
    sv = COMPOSE['services']
    assert set(sv) == {'bs', 'uav', 'client1', 'client2'}
    assert len({s['container_name'] for s in sv.values()}) == 4 and {s['container_name'] for s in sv.values()} == set(R.CONTAINERS)
    for name, s in sv.items():
        assert s['image'] == R.IMAGE
        cmd = s['command']
        assert cmd.startswith('sh -c "python ') and cmd.endswith('"'), f'{name}: lệnh sai dạng'
        for flag in re.finditer(r'(\S)--[a-z]', cmd):                  # mỗi cờ -- phải đứng sau khoảng trắng (lỗi cũ: `--dev 1--arm`)
            assert flag.group(1) == ' ', f'{name}: thiếu khoảng trắng trước cờ: ...{cmd[max(0, flag.start() - 10):flag.end() + 5]}...'
    assert '--host uav' in sv['client1']['command'] and '--port ${PORT1:-%d}' % FLQ['ports'][0] in sv['client1']['command']
    assert '--host uav' in sv['client2']['command'] and '--port ${PORT2:-%d}' % FLQ['ports'][1] in sv['client2']['command']
    assert '--port ${BS_PORT:-%d}' % FLQ['bs_port'] in sv['bs']['command']
    assert '--bs-host bs' in sv['uav']['command'] and '--channel ${CHANNEL}' in sv['uav']['command']
    for k in ('client1', 'client2'):
        assert sv[k]['cpus'] == '${CLIENT_CPUS:-1.6}' and sv[k]['mem_limit'] == '${CLIENT_MEM:-4g}'
        assert sv[k]['environment']['DEVICE_LIMIT_BY'] == 'docker'
        vols = ' '.join(sv[k]['volumes'])
        assert 'config/secure_fl_config.yaml:/app/src/secure_fl/config.yaml:ro' in vols and 'config/model_config.yaml:/app/src/model/config.yaml:ro' in vols
    assert 'cpus' not in sv['bs'] and 'cpus' not in sv['uav'] and 'mem_limit' not in sv['uav']              # BS và ống không bị giới hạn Pi 4
    vols1, vols2 = ' '.join(sv['client1']['volumes']), ' '.join(sv['client2']['volumes'])
    assert 'outputs/model/client1' in vols1 and 'outputs/model/shared' in vols1 and 'outputs/model/client2' not in vols1
    assert 'outputs/model/client2' in vols2 and 'outputs/model/client1' not in vols2 and 'shared' not in vols2   # mỗi client chỉ thấy dữ liệu của mình
    assert not any('outputs/model' in v for v in sv['bs']['volumes'] + sv['uav']['volumes'])                    # BS và ống không thấy dữ liệu của ai
    assert 'config/model_config.yaml' not in ' '.join(sv['bs']['volumes'])
    assert not any('keys' in v for s in sv.values() for v in s['volumes']), 'ống/BS không được mount khóa'
    print('[TEST] D. Compose: 4 container; client nối vào uav; cờ lệnh đúng; Pi 4 chỉ ở client; mỗi bên chỉ mount thứ được phép thấy; config thật được mount đè bằng bản sao')


def test_compose_with_docker():
    if shutil.which('docker') is None or subprocess.run(['docker', 'info'], capture_output=True).returncode != 0:
        print('[TEST] E. BỎ QUA: Docker không chạy, không kiểm `docker compose config`')
        return
    with tempfile.TemporaryDirectory() as d:
        R.write_config_copies(d, FLQ, 4, 900)
        env = R.build_env(d, 'uav_noma_pc', 'none', FLQ, 4, {'cpus': 1.6, 'mem_limit': '4g'})
        r = subprocess.run(['docker', 'compose', '-f', str(R.COMPOSE), 'config'], cwd=ROOT, env=env, capture_output=True, text=True, encoding='utf-8')
    assert r.returncode == 0, r.stderr
    assert 'uavfl-uav' in r.stdout and '--host uav' in r.stdout and '7201' in r.stdout
    print('[TEST] E. `docker compose config` hợp lệ với biến môi trường của bộ điều phối')


def test_dry_run_process():
    r = subprocess.run([sys.executable, str(ROOT / 'src' / 'uav_channel' / 'run_fl_uav.py'), '--dry-run', '--rounds', '2'], cwd=ROOT,
                       capture_output=True, text=True, encoding='utf-8')
    assert r.returncode == 0, r.stderr
    assert 'dry-run' in r.stdout and 'ckks_full' in r.stdout and 'direct_noma' in r.stdout and '3' in r.stdout
    print('[TEST] F. `--dry-run --rounds 2` chạy được và in kế hoạch (không chạy Docker, không ghi file)')


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
    print('[TEST] run_fl_uav: ' + ('ĐẠT' if not fails else f'LỖI ({fails})'))
    sys.exit(1 if fails else 0)
