"""Chạy toàn bộ test và LƯU kết quả: outputs/secure_fl/tests/<thời điểm>/<test>.log + summary.md.
Test mã hóa thật (test_openfhe) chạy trong container nếu Docker đang chạy và đã build image `doanfl-securefl`; không thì ghi "bỏ qua".
Chạy: python tests/run_all.py"""
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(__file__).resolve().parents[1]
DOCKER_BIN = Path(r'C:\Program Files\Docker\Docker\resources\bin')
IMAGE = 'doanfl-securefl'
HOST_TESTS = ['tests/secure_fl/test_security.py', 'tests/secure_fl/test_protocol.py', 'tests/secure_fl/test_attack_switch.py',
              'tests/secure_fl/test_device_profile.py', 'tests/secure_fl/test_devicelimit.py', 'tests/secure_fl/test_device_guard.py',
              'tests/uav_channel/test_channel.py', 'tests/uav_channel/test_uav_relay.py']
DOCKER_TESTS = ['tests/secure_fl/test_openfhe.py', 'tests/secure_fl/test_security.py']


def run(cmd, timeout=900):
    env = dict(os.environ, PYTHONIOENCODING='utf-8')
    t0 = time.time()
    try:
        r = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout)
        return r.returncode, r.stdout + r.stderr, time.time() - t0
    except subprocess.TimeoutExpired as e:
        return -1, f'QUÁ HẠN {timeout}s\n{e.stdout or ""}', time.time() - t0


def docker_ready():
    if DOCKER_BIN.exists() and str(DOCKER_BIN) not in os.environ['PATH']:
        os.environ['PATH'] += os.pathsep + str(DOCKER_BIN)
    if shutil.which('docker') is None:
        return 'không thấy lệnh docker'
    code, _, _ = run(['docker', 'info'], 60)
    if code != 0:
        return 'Docker chưa chạy'
    code, out, _ = run(['docker', 'images', '-q', IMAGE], 60)
    return None if out.strip() else f'chưa build image {IMAGE}'


def main():
    out = ROOT / 'outputs' / 'secure_fl' / 'tests' / time.strftime('%Y%m%d_%H%M%S')
    out.mkdir(parents=True, exist_ok=True)
    rows = []

    def record(name, where, code, text, secs):
        (out / f'{where}_{Path(name).stem}.log').write_text(text, encoding='utf-8')
        ok, bad, skip = (len(re.findall(p, text)) for p in ('ĐẠT', 'LỖI', 'bỏ qua'))
        rows.append((name, where, 'ĐẠT' if code == 0 else 'LỖI', ok, bad, skip, secs))
        print(f'{rows[-1][2]:<5}{where:<8}{name}  (đạt {ok}, lỗi {bad}, bỏ qua {skip}, {secs:.0f}s)', flush=True)

    for t in HOST_TESTS:
        code, text, secs = run([sys.executable, t])
        record(t, 'windows', code, text, secs)
    why = docker_ready()
    for t in DOCKER_TESTS:
        if why:
            rows.append((t, 'docker', 'BỎ QUA', 0, 0, 0, 0.0))
            print(f'BỎ QUA docker  {t}  ({why})', flush=True)
            continue
        code, text, secs = run(['docker', 'run', '--rm', '-v', f'{ROOT}:/app', IMAGE, 'python', t])
        record(t, 'docker', code, text, secs)

    md = ['# Kết quả chạy test', '', f'Thời điểm: {time.strftime("%Y-%m-%d %H:%M:%S")}', '',
          '| Test | Nơi chạy | Kết quả | Bài đạt | Bài lỗi | Bài bỏ qua | Giây |', '|---|---|---|---|---|---|---|']
    md += [f'| {n} | {w} | {r} | {a} | {b} | {c} | {s:.0f} |' for n, w, r, a, b, c, s in rows]
    (out / 'summary.md').write_text('\n'.join(md) + '\n', encoding='utf-8')
    print(f'\nĐã lưu vào {out}')
    sys.exit(1 if any(r[2] == 'LỖI' for r in rows) else 0)


if __name__ == '__main__':
    main()
