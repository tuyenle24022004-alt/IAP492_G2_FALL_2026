"""Bộ điều phối bản DOCKER: mỗi arm chạy 3 container (bs, client1, client2) bằng docker compose, mã hóa thật bằng OpenFHE.

Giống run_fl_tcp.py về luồng và kết quả (vòng 0 + fl.rounds vòng, cùng seed 42), khác ở chỗ BS và hai client là CONTAINER riêng, mỗi bên
chỉ mount thứ nó được phép thấy (docker/docker-compose.yml). Kết quả ghi vào outputs/secure_fl/docker/<model>/seed<N>/<arm>/ rồi gộp
thành seed<N>.json bằng collect.py; xem bằng analyze.py --out outputs/secure_fl/docker.
Yêu cầu: Docker Desktop đang chạy. Chạy: python src/secure_fl/experiments/run_fl_docker.py --seed 42 [--arms none ckks_full] [--backend openfhe]
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import numpy as np
import yaml

SRC = Path(__file__).resolve().parents[2]
ROOT = SRC.parent
sys.path.insert(0, str(SRC))

from secure_fl import settings                                                   # noqa: E402
from secure_fl.arms import arm_list, bs_has_key                                  # noqa: E402
from secure_fl.runlog import install_tee, stamp, write_run_info                  # noqa: E402

COMPOSE = ROOT / 'docker' / 'docker-compose.yml'
COMPOSE_FASBS = ROOT / 'docker' / 'docker-compose.fasbs.yml'
CONTAINERS = ['secure-fl-bs', 'secure-fl-client1', 'secure-fl-client2']


def sh(cmd, env=None, check=True, timeout=None):
    r = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, encoding='utf-8', timeout=timeout)
    if check and r.returncode != 0:
        raise RuntimeError(f'lệnh lỗi ({r.returncode}): {" ".join(cmd)}\n{r.stdout}\n{r.stderr}')
    return r


def check_docker():
    if shutil.which('docker') is None:
        raise SystemExit('không thấy lệnh `docker`: cài Docker Desktop (winget install -e --id Docker.DockerDesktop), khởi động nó rồi chạy lại')
    r = sh(['docker', 'info'], check=False)
    if r.returncode != 0:
        raise SystemExit('Docker chưa chạy: mở Docker Desktop, chờ tới khi báo "Engine running", rồi chạy lại')


_MIB = {'B': 1 / 2**20, 'KiB': 1 / 1024, 'MiB': 1.0, 'GiB': 1024.0, 'kB': 1000 / 2**20, 'MB': 1e6 / 2**20, 'GB': 1e9 / 2**20}


def to_mib(s):
    """'812.3MiB' -> 812.3 (đơn vị của `docker stats`)."""
    m = re.fullmatch(r'\s*([\d.]+)\s*([A-Za-z]+)\s*', s)
    return float(m.group(1)) * _MIB[m.group(2)] if m and m.group(2) in _MIB else float('nan')


def container_limits(env):
    """Giới hạn THỰC TẾ Docker đã áp cho từng container (đọc bằng `docker inspect`, không phải giá trị trong file cấu hình)."""
    r = sh(['docker', 'inspect', '--format', '{{.Name}}|{{.HostConfig.NanoCpus}}|{{.HostConfig.Memory}}|{{.Image}}'] + CONTAINERS, env, check=False)
    out = {}
    for line in r.stdout.splitlines():
        name, cpus, mem, image = line.strip().split('|')
        out[name.lstrip('/')] = {'cpus': int(cpus) / 1e9 if int(cpus) else None, 'mem_limit_mib': int(mem) / 2**20 if int(mem) else None, 'image_id': image}
    return out


class StatsSampler(threading.Thread):
    """Lấy mẫu `docker stats` trong lúc arm chạy để ghi RAM đỉnh và CPU đỉnh của từng container."""

    def __init__(self, env, every_s=2.0):
        super().__init__(daemon=True)
        self.env, self.every_s, self.stop, self.peak, self.n = env, every_s, threading.Event(), {}, 0

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
            self.stop.wait(self.every_s)


def run_arm(name, kind, seed, model, rounds, out, lock, backend):
    for sub in ('bs', 'client1', 'client2', 'keys'):
        (out / sub).mkdir(parents=True, exist_ok=True)
    k_args = ''
    if kind == 'fas':
        (out / 'keys' / 'perm_seed').write_bytes(np.random.default_rng([seed, 99]).bytes(32))
        k_args = '--k-file /keys/perm_seed'
    dev = settings.load()['device']                                           # giả lập Pi 4: giới hạn CPU/RAM của container client
    env = dict(os.environ, ARM=name, SEED=str(seed), ROUNDS=str(rounds), MODEL=model, RUN_DIR=out.as_posix(), BACKEND=backend,
               CLIENT_CPUS=str(dev['cpus']), CLIENT_MEM=str(dev['mem_limit']), CLIENT_K_ARGS=k_args, BS_K_ARGS=k_args if bs_has_key(name, lock) else '')
    files = ['-f', str(COMPOSE)] + (['-f', str(COMPOSE_FASBS)] if bs_has_key(name, lock) else [])
    base = ['docker', 'compose'] + files
    sh(base + ['down', '--remove-orphans'], env, check=False)
    t0 = time.time()
    sh(base + ['up', '-d'], env)
    limits = container_limits(env)                                            # bằng chứng: giới hạn Docker thực sự áp dụng
    sampler = StatsSampler(env)
    sampler.start()
    try:
        limit = float(lock['timeout_s']) * (rounds + 1)
        r = sh(['docker', 'wait'] + CONTAINERS, env, timeout=limit)
        codes = [int(x) for x in r.stdout.split()]
    finally:
        sampler.stop.set()
        sampler.join(timeout=30)
        evidence = {'device_config': dev, 'containers': {c: dict(limits.get(c, {}), **sampler.peak.get(c, {})) for c in CONTAINERS},
                    'so_mau_docker_stats': sampler.n, 'chu_ky_lay_mau_s': sampler.every_s}
        (out / 'docker_limits.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=1), encoding='utf-8')
        log = sh(base + ['logs', '--no-color'], env, check=False)
        (out / 'docker.log').write_text(log.stdout + log.stderr, encoding='utf-8')
        sh(base + ['down', '--remove-orphans'], env, check=False)
    if any(codes):
        raise RuntimeError(f'arm {name}: mã thoát {dict(zip(CONTAINERS, codes))}, xem {out / "docker.log"}')
    for sub in ('bs', 'client1', 'client2'):                                  # gộp về bố cục chuẩn mà collect.py đọc
        shutil.copytree(out / sub, out, dirs_exist_ok=True)
    return time.time() - t0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--seed', type=int, required=True)
    ap.add_argument('--model', default='classifier', choices=['classifier', 'fire9_classifier'])
    ap.add_argument('--rounds', type=int)
    ap.add_argument('--arms', nargs='*', help='mặc định: mọi arm trong config')
    ap.add_argument('--backend', default='openfhe', choices=['openfhe', 'emulated'])
    ap.add_argument('--out', default='outputs/secure_fl/docker')
    ap.add_argument('--no-collect', action='store_true')
    ap.add_argument('--rebuild', action='store_true', help='build lại image (cần mạng); mặc định chỉ build khi chưa có image')
    a = ap.parse_args()
    tag = f'seed{a.seed}_{stamp()}'
    install_tee(ROOT / a.out / a.model / 'logs' / f'run_fl_docker_{tag}.log')   # lưu mọi dòng in ra
    os.environ['SECURE_FL_BACKEND'] = a.backend
    lock = settings.load()['lock']
    mcfg = yaml.safe_load(open(SRC / 'model' / 'config.yaml', encoding='utf-8'))
    rounds = a.rounds or int(mcfg['fl']['rounds'])
    if a.seed != int(mcfg['seed']):
        raise SystemExit(f"trọng số huấn luyện cục bộ 150 epoch chỉ có cho seed {mcfg['seed']}; seed {a.seed} cần huấn luyện cục bộ trước")
    arms = arm_list(lock)
    if a.arms:
        arms = [x for x in arms if x[0] in a.arms]
    check_docker()
    img = sh(['docker', 'image', 'inspect', 'doanfl-securefl', '--format', '{{.Id}}'], check=False).stdout.strip()
    write_run_info(ROOT / a.out / a.model / 'logs' / f'run_info_{tag}.json', backend=a.backend, rounds=rounds, model=a.model,
                   arms=[x[0] for x in arms], docker_image_id=img)
    if not img or a.rebuild:                       # image đã có thì KHÔNG build lại: build cần mạng để kiểm tra image nền python:3.12-slim
        sh(['docker', 'compose', '-f', str(COMPOSE), 'build', 'bs'], dict(os.environ, ARM='x', SEED='0', ROUNDS='0', RUN_DIR=ROOT.as_posix()))
    seed_dir = ROOT / a.out / a.model / f'seed{a.seed}'
    for name, kind, _kw in arms:
        d = seed_dir / name
        if (d / 'bs_log.json').exists() and (d / 'client1_log.json').exists():
            print(f'[seed {a.seed}] {name}: đã có, bỏ qua', flush=True)
            continue
        secs = run_arm(name, kind, a.seed, a.model, rounds, d, lock, a.backend)
        print(f'[seed {a.seed}] {name:<12} xong sau {secs:.0f}s', flush=True)
    if not a.no_collect:
        from secure_fl.experiments.collect import collect_seed
        collect_seed(seed_dir, a.model, dict(lock, backend=a.backend), rounds)
        print(f'[seed {a.seed}] đã gộp -> {seed_dir.parent / f"seed{a.seed}.json"}', flush=True)


if __name__ == '__main__':
    main()
