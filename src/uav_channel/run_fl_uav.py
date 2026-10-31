"""Bộ điều phối: FL chạy THẬT qua ống kênh (có UAV / không UAV), mã hóa OpenFHE thật trong container.

Mỗi lượt = (kênh, arm): 4 container `bs`, `uav` (ống kênh), `client1`, `client2` (docker/docker-compose.uav.yml). Client nối vào `uav`, `uav` giữ
UPLOAD và PARTIAL_DEC đúng thời gian của kênh bằng ĐỒNG HỒ THẬT rồi chuyển cho `bs`. Không sửa mã FL (BS, client, mã hóa) và không sửa config thật:
mọi thông số của đợt đặt ở khối `fl_qua_kenh` trong src/uav_channel/config.yaml, bộ điều phối tạo BẢN SAO config model (fl.rounds, fl.local_epochs) và
config secure_fl (lock.timeout_s) cho từng lượt rồi mount đè vào container; bản sao lưu trong <lượt>/config/ làm bằng chứng.

Hạn chờ: client nhanh phải đợi client chậm xong, có thể hàng giờ ở kênh không UAV; lock.timeout_s (900 s) sẽ làm client lỗi, nên được nâng theo
chuỗi kênh (tx_plan.timeout_for). Giữ Windows không ngủ trong lúc chạy. Kết quả: outputs/uav_channel/fl_qua_kenh/<kênh>_<arm>/{bs,client1,client2,uav,config}/.
Chạy:  python src/uav_channel/run_fl_uav.py [--arms none ckks_full] [--channels uav_noma_pc direct_noma] [--rounds N] [--dry-run]
Lượt đã có bs/bs_log.json thì bỏ qua. Thứ tự chạy: ngắn trước, dài sau (theo thời gian dự kiến).
"""
import argparse
import ctypes
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import yaml

SRC = Path(__file__).resolve().parents[1]
ROOT = SRC.parent
sys.path.insert(0, str(SRC))

from secure_fl import settings                                                    # noqa: E402
from secure_fl.experiments.run_fl_docker import to_mib                            # noqa: E402  (hàm thuần đổi đơn vị của docker stats)
from secure_fl.runlog import install_tee, stamp, write_run_info                   # noqa: E402
from uav_channel import tx_plan as TP                                             # noqa: E402
from uav_channel.channel import ChannelModel, MODES                               # noqa: E402

CONFIG = SRC / 'uav_channel' / 'config.yaml'
COMPOSE = SRC / 'uav_channel' / 'docker' / 'docker-compose.uav.yml'
IMAGE = 'doanfl-securefl'
CONTAINERS = ['uavfl-bs', 'uavfl-uav', 'uavfl-client1', 'uavfl-client2']
FL_CONTAINERS = ['uavfl-bs', 'uavfl-client1', 'uavfl-client2']


def sh(cmd, env=None, check=True, timeout=None):
    r = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout)
    if check and r.returncode != 0:
        raise RuntimeError(f'lệnh lỗi ({r.returncode}): {" ".join(cmd)}\n{r.stdout}\n{r.stderr}')
    return r


def keep_awake(on):
    """Giữ Windows không ngủ (lượt không UAV dài hàng giờ); gọi từ luồng chính và giữ nguyên cho tới khi tắt."""
    if os.name == 'nt':
        es_continuous, es_system_required = 0x80000000, 0x00000001
        ctypes.windll.kernel32.SetThreadExecutionState(es_continuous | es_system_required if on else es_continuous)


def check_docker():
    if shutil.which('docker') is None:
        raise SystemExit('không thấy lệnh `docker`: cài và khởi động Docker Desktop rồi chạy lại')
    if sh(['docker', 'info'], check=False).returncode != 0:
        raise SystemExit('Docker chưa chạy: mở Docker Desktop, chờ báo "Engine running", rồi chạy lại')
    if not sh(['docker', 'images', '-q', IMAGE], check=False).stdout.strip():
        print(f'[điều phối] chưa có image {IMAGE}: build (cần mạng)', flush=True)
        sh(['docker', 'build', '-f', 'docker/Dockerfile', '-t', IMAGE, '.'])


def n_params(flq):
    return int(json.load(open(ROOT / flq['model_metrics'], encoding='utf-8'))['n_params'])


def plan_run(channel, arm, cfg, flq, he, m, rounds):
    """Dự kiến một lượt chạy từ chuỗi kênh: byte, thời gian truyền, thời gian chờ dài nhất, hạn chờ, hạn tổng."""
    c = {**cfg, 'channel': {**cfg['channel'], 'mode': channel}}
    up, sh_ = TP.frame_bytes(arm, m, he, flq['frame_overhead_B'])
    pred = TP.predict(ChannelModel.from_config(c), up, sh_, rounds + 1)
    timeout_s = TP.timeout_for(pred['max_wait_s'], flq['timeout_margin'], flq['timeout_min_s'])
    limit_s = flq['timeout_margin'] * (pred['total_s'] + (rounds + 1) * flq['compute_s_per_round']) + 3600.0
    return {'channel': channel, 'arm': arm, 'rounds': rounds, 'n_transmissions': rounds + 1, 'upload_B': up, 'share_B': sh_,
            'predicted_total_s': pred['total_s'], 'max_wait_s': pred['max_wait_s'], 'min_rate_bit_s': 8 * pred['min_rate_Bps'],
            'timeout_s': timeout_s, 'limit_s': limit_s}


def write_config_copies(run_dir, flq, rounds, timeout_s):
    """Bản sao config model (fl.rounds, fl.local_epochs) và secure_fl (lock.timeout_s) cho lượt chạy; file thật không đổi."""
    cdir = Path(run_dir) / 'config'
    cdir.mkdir(parents=True, exist_ok=True)
    model_cfg = yaml.safe_load(open(SRC / 'model' / 'config.yaml', encoding='utf-8'))
    model_cfg['fl']['rounds'] = int(rounds)
    model_cfg['fl']['local_epochs'] = int(flq['local_epochs'])
    sfl_cfg = yaml.safe_load(open(SRC / 'secure_fl' / 'config.yaml', encoding='utf-8'))
    sfl_cfg['lock']['timeout_s'] = int(timeout_s)
    for name, cfg in (('model_config.yaml', model_cfg), ('secure_fl_config.yaml', sfl_cfg)):
        (cdir / name).write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding='utf-8')
    return cdir


def build_env(run_dir, channel, arm, flq, rounds, device):
    return dict(os.environ, ARM=arm, SEED=str(flq['seed']), ROUNDS=str(rounds), MODEL=flq['model'], RUN_DIR=Path(run_dir).as_posix(),
                CHANNEL=channel, BACKEND='openfhe', PORT1=str(flq['ports'][0]), PORT2=str(flq['ports'][1]), BS_PORT=str(flq['bs_port']),
                CLIENT_CPUS=str(device['cpus']), CLIENT_MEM=str(device['mem_limit']))


def container_limits(env):
    """Giới hạn THỰC TẾ Docker đã áp (docker inspect), không phải giá trị trong file cấu hình."""
    r = sh(['docker', 'inspect', '--format', '{{.Name}}|{{.HostConfig.NanoCpus}}|{{.HostConfig.Memory}}|{{.Image}}'] + CONTAINERS, env, check=False)
    out = {}
    for line in r.stdout.splitlines():
        name, cpus, mem, image = line.strip().split('|')
        out[name.lstrip('/')] = {'cpus': int(cpus) / 1e9 if int(cpus) else None, 'mem_limit_mib': int(mem) / 2**20 if int(mem) else None, 'image_id': image}
    return out


class Sampler(threading.Thread):
    """Lấy mẫu `docker stats` (RAM đỉnh, CPU đỉnh) và in dòng tiến độ mới nhất của BS mỗi `progress_s` giây."""

    def __init__(self, env, every_s=5.0, progress_s=60.0):
        super().__init__(daemon=True)
        self.env, self.every_s, self.progress_s = env, every_s, progress_s
        self.stop, self.peak, self.n, self.t_progress = threading.Event(), {}, 0, time.time()

    def run(self):
        while not self.stop.is_set():
            r = sh(['docker', 'stats', '--no-stream', '--format', '{{.Name}}|{{.MemUsage}}|{{.CPUPerc}}'] + CONTAINERS, self.env, check=False)
            for line in r.stdout.splitlines():
                parts = line.strip().split('|')
                if len(parts) != 3:
                    continue
                mem, cpu = to_mib(parts[1].split('/')[0]), float(parts[2].rstrip('%') or 0)
                p = self.peak.setdefault(parts[0], {'peak_mem_mib': 0.0, 'peak_cpu_pct': 0.0})
                p['peak_mem_mib'] = max(p['peak_mem_mib'], mem if mem == mem else 0.0)
                p['peak_cpu_pct'] = max(p['peak_cpu_pct'], cpu)
            self.n += 1
            if time.time() - self.t_progress >= self.progress_s:
                self.t_progress = time.time()
                last = [x for x in sh(['docker', 'logs', '--tail', '3', 'uavfl-bs'], self.env, check=False).stdout.splitlines() if x.strip()]
                print(f'[tiến độ {time.strftime("%H:%M:%S")}] ' + (last[-1] if last else '(chưa có dòng nào từ BS)'), flush=True)
            self.stop.wait(self.every_s)


def run_one(p, cfg, flq, out_root, device):
    run_dir = out_root / f'{p["channel"]}_{p["arm"]}'
    for sub in ('bs', 'client1', 'client2', 'uav'):
        (run_dir / sub).mkdir(parents=True, exist_ok=True)
    write_config_copies(run_dir, flq, p['rounds'], p['timeout_s'])
    (run_dir / 'plan.json').write_text(json.dumps(p, ensure_ascii=False, indent=1), encoding='utf-8')
    env = build_env(run_dir, p['channel'], p['arm'], flq, p['rounds'], device)
    base = ['docker', 'compose', '-f', str(COMPOSE)]
    sh(base + ['down', '--remove-orphans'], env, check=False)
    print(f'[điều phối] {p["channel"]} / {p["arm"]}: {p["n_transmissions"]} lần truyền, dự kiến truyền {p["predicted_total_s"] / 3600:.2f} giờ, '
          f'hạn chờ một tin {p["timeout_s"]} s, hạn tổng {p["limit_s"] / 3600:.1f} giờ; bắt đầu {time.strftime("%Y-%m-%d %H:%M:%S")}', flush=True)
    t0 = time.time()
    sh(base + ['up', '-d'], env)
    limits = container_limits(env)
    sampler = Sampler(env)
    sampler.start()
    codes, timed_out = [], False
    try:
        r = sh(['docker', 'wait'] + FL_CONTAINERS, env, timeout=p['limit_s'])
        codes = [int(x) for x in r.stdout.split()]
    except subprocess.TimeoutExpired:
        timed_out = True
    finally:
        sampler.stop.set()
        sampler.join(timeout=30)
        evidence = {'device_config': device, 'containers': {c: dict(limits.get(c, {}), **sampler.peak.get(c, {})) for c in CONTAINERS},
                    'so_mau_docker_stats': sampler.n, 'chu_ky_lay_mau_s': sampler.every_s}
        (run_dir / 'docker_limits.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=1), encoding='utf-8')
        log = sh(base + ['logs', '--no-color'], env, check=False)
        (run_dir / 'docker.log').write_text(log.stdout + log.stderr, encoding='utf-8')
        try:                                                                  # ống thoát khi cả hai client đóng kết nối; chờ để lấy mã thoát thật
            uav_exit = sh(['docker', 'wait', 'uavfl-uav'], env, check=False, timeout=120).stdout.strip()
        except subprocess.TimeoutExpired:
            uav_exit = ''                                                     # ống chưa thoát: không coi là lỗi, stats đã được ghi từng dòng
        sh(base + ['down', '--remove-orphans'], env, check=False)
    if timed_out:
        raise RuntimeError(f'lượt {p["channel"]}/{p["arm"]} quá hạn tổng {p["limit_s"]:.0f}s, xem {run_dir / "docker.log"}')
    if any(codes) or uav_exit not in ('0', ''):
        raise RuntimeError(f'lượt {p["channel"]}/{p["arm"]}: mã thoát {dict(zip(FL_CONTAINERS, codes))}, ống {uav_exit}; xem {run_dir / "docker.log"}')
    secs = time.time() - t0
    write_run_info(run_dir / 'run_info.json', backend='openfhe', rounds=p['rounds'], model=flq['model'], plan=p, fl_qua_kenh=flq, channel_seed=cfg['seed'])
    print(f'[điều phối] {p["channel"]} / {p["arm"]} xong sau {secs:.0f}s ({secs / 3600:.2f} giờ)', flush=True)
    return secs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--arms', nargs='*')
    ap.add_argument('--channels', nargs='*')
    ap.add_argument('--rounds', type=int, help='mặc định: fl_qua_kenh.rounds')
    ap.add_argument('--dry-run', action='store_true', help='chỉ in kế hoạch và dự kiến, không chạy Docker, không ghi file')
    ap.add_argument('--out', help='thư mục kết quả (mặc định: fl_qua_kenh.out); dùng thư mục riêng khi chạy thử để không chặn lượt thật')
    a = ap.parse_args()
    cfg = yaml.safe_load(open(CONFIG, encoding='utf-8'))
    flq = cfg['fl_qua_kenh']
    arms, channels = a.arms or flq['arms'], a.channels or flq['channels']
    bad = [c for c in channels if c not in MODES] + [x for x in arms if x not in ('none', 'ckks_full')]
    if bad:
        raise SystemExit(f'không hợp lệ: {bad}')
    rounds = a.rounds if a.rounds is not None else int(flq['rounds'])
    he, m = settings.load()['he'], n_params(flq)
    plans = sorted((plan_run(c, x, cfg, flq, he, m, rounds) for c in channels for x in arms), key=lambda p: p['predicted_total_s'])
    out_root = ROOT / (a.out or flq['out'])
    print(f'FL qua kênh: {rounds} vòng + vòng 0, {flq["local_epochs"]} epoch mỗi vòng, seed FL {flq["seed"]}, seed kênh {cfg["seed"]}, M = {m} tham số')
    print(f'{"kênh":<13}{"arm":<11}{"lần truyền":>10}{"UPLOAD B":>11}{"PD B":>9}{"dự kiến truyền":>16}{"chờ lệch max":>14}{"hạn chờ s":>11}')
    for p in plans:
        print(f'{p["channel"]:<13}{p["arm"]:<11}{p["n_transmissions"]:>10}{p["upload_B"]:>11,}{p["share_B"]:>9,}{p["predicted_total_s"] / 3600:>13.2f} h'
              f'{p["max_wait_s"] / 3600:>11.2f} h{p["timeout_s"]:>11}')
    if a.dry_run:
        print('(dry-run: không chạy gì)')
        return
    install_tee(out_root / 'logs' / f'run_fl_uav_{stamp()}.log')
    check_docker()
    device = settings.load()['device']
    keep_awake(True)
    try:
        for p in plans:
            if (out_root / f'{p["channel"]}_{p["arm"]}' / 'bs' / 'bs_log.json').exists():
                print(f'[điều phối] {p["channel"]} / {p["arm"]} đã có kết quả, bỏ qua', flush=True)
                continue
            run_one(p, cfg, flq, out_root, device)
    finally:
        keep_awake(False)


if __name__ == '__main__':
    main()
