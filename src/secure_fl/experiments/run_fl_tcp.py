"""Bộ điều phối: với mỗi arm chạy MỘT tiến trình BS + HAI tiến trình client nói chuyện qua TCP (127.0.0.1), không UAV, không bóp tốc độ.
Mỗi arm: vòng 0 (tổng hợp trọng số huấn luyện cục bộ 150 epoch qua bảo vệ) rồi `fl.rounds` vòng (config model, = 50) × `fl.local_epochs` epoch.

Mỗi arm ghi vào outputs/secure_fl/tcp/<model>/seed<N>/<arm>/ ; xong cả seed thì gộp thành seed<N>.json (collect.py).
Khóa xáo K của arm FAS do bộ điều phối sinh, chỉ đưa cho 2 client (và cho BS ở arm fasbs_*). Arm đã chạy xong thì bỏ qua.
Giả lập Pi 4 là BẮT BUỘC và do chính client.py tự áp (devicelimit.enforce, Job Object); BS không bị giới hạn. Mỗi client ghi device_limits_client<k>.json vào thư mục arm.
Chạy: python src/secure_fl/experiments/run_fl_tcp.py --seed 42 [--arms none ckks_full] [--rounds 50]
"""
import argparse
import os
import subprocess
import sys
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

PY = sys.executable


def run_arm(name, kind, seed, model, rounds, port, out, lock):
    out.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, PYTHONIOENCODING='utf-8')
    k_args = []
    if kind == 'fas':
        (out / 'keys').mkdir(exist_ok=True)
        kf = out / 'keys' / 'perm_seed'
        kf.write_bytes(np.random.default_rng([seed, 99]).bytes(32))
        k_args = ['--k-file', str(kf)]
    bs_args = [PY, str(SRC / 'secure_fl' / 'bs' / 'server.py'), '--arm', name, '--port', str(port), '--out', str(out),
               '--seed', str(seed), '--rounds', str(rounds)] + (k_args if bs_has_key(name, lock) else [])
    cl_args = lambda dev: [PY, str(SRC / 'secure_fl' / 'client' / 'client.py'), '--dev', str(dev), '--arm', name, '--port', str(port),    # noqa: E731
                           '--out', str(out), '--seed', str(seed), '--model', model, '--rounds', str(rounds)] + k_args
    logs = {n: open(out / f'{n}.log', 'w', encoding='utf-8') for n in ('bs', 'client1', 'client2')}
    procs = {'bs': subprocess.Popen(bs_args, cwd=ROOT, env=env, stdout=logs['bs'], stderr=subprocess.STDOUT)}
    time.sleep(1.0)
    for dev in (1, 2):
        procs[f'client{dev}'] = subprocess.Popen(cl_args(dev), cwd=ROOT, env=env, stdout=logs[f'client{dev}'], stderr=subprocess.STDOUT)
    t0 = time.time()
    limit = float(lock['timeout_s']) * rounds
    try:
        for n, p in procs.items():
            p.wait(timeout=max(1.0, limit - (time.time() - t0)))
    except subprocess.TimeoutExpired:
        for p in procs.values():
            p.kill()
        raise RuntimeError(f'arm {name} quá hạn {limit:.0f}s, xem log trong {out}')
    finally:
        for f in logs.values():
            f.close()
    bad = {n: p.returncode for n, p in procs.items() if p.returncode != 0}
    if bad:
        raise RuntimeError(f'arm {name} lỗi {bad}, xem log trong {out}')
    return time.time() - t0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--seed', type=int, required=True)
    ap.add_argument('--model', default='classifier', choices=['classifier', 'fire9_classifier'])
    ap.add_argument('--rounds', type=int)
    ap.add_argument('--arms', nargs='*', help='mặc định: mọi arm trong config')
    ap.add_argument('--out', default='outputs/secure_fl/tcp')
    ap.add_argument('--no-collect', action='store_true')
    a = ap.parse_args()
    tag = f'seed{a.seed}_{stamp()}'
    install_tee(ROOT / a.out / a.model / 'logs' / f'run_fl_tcp_{tag}.log')   # lưu mọi dòng in ra
    cfg = settings.load()
    lock, dev = cfg['lock'], cfg['device']
    print(f'[giả lập thiết bị] mỗi client tự giới hạn {dev["cpus"]} nhân, RAM {dev["mem_limit"]} ({dev["profile"]}), bắt buộc; BS không giới hạn. '
          f'Bằng chứng: device_limits_client*.json trong thư mục từng arm', flush=True)
    mcfg = yaml.safe_load(open(SRC / 'model' / 'config.yaml', encoding='utf-8'))
    rounds = a.rounds or int(mcfg['fl']['rounds'])
    if a.seed != int(mcfg['seed']):
        raise SystemExit(f"trọng số huấn luyện cục bộ 150 epoch chỉ có cho seed {mcfg['seed']} (outputs/model/client*/run); "
                         f"seed {a.seed} cần huấn luyện cục bộ trước")
    arms = arm_list(lock)
    if a.arms:
        arms = [x for x in arms if x[0] in a.arms]
    seed_dir = ROOT / a.out / a.model / f'seed{a.seed}'
    write_run_info(ROOT / a.out / a.model / 'logs' / f'run_info_{tag}.json', backend=lock['backend'], rounds=rounds, model=a.model,
                   arms=[x[0] for x in arms])
    for i, (name, kind, _kw) in enumerate(arms):
        d = seed_dir / name
        if (d / 'bs_log.json').exists() and (d / 'client1_log.json').exists():
            print(f'[seed {a.seed}] {name}: đã có, bỏ qua', flush=True)
            continue
        port = int(lock['base_port']) + (a.seed % 100) * 20 + i
        secs = run_arm(name, kind, a.seed, a.model, rounds, port, d, lock)
        print(f'[seed {a.seed}] {name:<12} xong sau {secs:.0f}s', flush=True)
    if not a.no_collect:
        from secure_fl.experiments.collect import collect_seed
        collect_seed(seed_dir, a.model, lock, rounds)
        print(f'[seed {a.seed}] đã gộp -> {seed_dir.parent / f"seed{a.seed}.json"}', flush=True)


if __name__ == '__main__':
    main()
