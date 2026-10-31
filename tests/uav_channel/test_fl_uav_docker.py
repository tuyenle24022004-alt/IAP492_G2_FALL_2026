"""Kiểm thử TÍCH HỢP THẬT trong Docker: FL 2 vòng qua ống kênh (kênh có UAV), không mã hóa và CKKS 100% bằng OpenFHE thật.
BẠN chạy (mất vài phút, cần Docker Desktop đang chạy):  python tests/uav_channel/test_fl_uav_docker.py
Ghi vào outputs/uav_channel/thu_nghiem_2vong/ (KHÔNG phải thư mục kết quả chính nên không chặn lượt chạy thật). Chạy lại từ đầu: xóa thư mục đó.

Kiểm: (1) FL chạy hết 3 lần truyền qua ống; (2) độ chính xác trùng lượt tcp đã có (none: trùng hẳn; CKKS thật: lệch tối đa 0,3 điểm);
(3) thời gian giữ từng tin khớp byte/R trong dung sai; (4) byte đo thật khớp công thức dưới 0,5%; (5) sai số tổng giải mã mỗi vòng dưới 1e-6 (CKKS thật đúng);
(6) chỉ UPLOAD và PARTIAL_DEC bị giữ; (7) backend là openfhe; (8) giới hạn Pi 4 do Docker áp đúng 1,6 CPU và 4 GB cho client, BS và ống không bị giới hạn;
(9) bản sao config đã mount đè với đúng số vòng."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))

from uav_channel import analyze_channel as AC
from uav_channel.uav.auto_relay import HELD_TYPES

CFG = yaml.safe_load(open(ROOT / 'src' / 'uav_channel' / 'config.yaml', encoding='utf-8'))
FLQ = CFG['fl_qua_kenh']
OUT = ROOT / 'outputs' / 'uav_channel' / 'thu_nghiem_2vong'
ROUNDS = 2
REF = ROOT / 'outputs' / 'secure_fl' / 'tcp' / FLQ['model'] / f'seed{FLQ["seed"]}'


def docker_ready():
    if shutil.which('docker') is None:
        return 'không thấy lệnh docker'
    if subprocess.run(['docker', 'info'], capture_output=True).returncode != 0:
        return 'Docker chưa chạy'
    return None


def ref_acc(arm):
    p = REF / arm / 'bs_log.json'
    if not p.exists():
        return None
    return [r['metrics']['acc'] for r in json.load(open(p, encoding='utf-8'))['rounds']]


def main():
    why = docker_ready()
    if why:
        print(f'[TEST] BỎ QUA: {why}')
        return 0
    cmd = [sys.executable, str(ROOT / 'src' / 'uav_channel' / 'run_fl_uav.py'), '--channels', 'uav_noma_pc', '--arms', 'none', 'ckks_full',
           '--rounds', str(ROUNDS), '--out', str(OUT.relative_to(ROOT))]
    print('[TEST] chạy:', ' '.join(cmd), flush=True)
    r = subprocess.run(cmd, cwd=ROOT, timeout=3600)
    assert r.returncode == 0, f'run_fl_uav.py lỗi (mã {r.returncode}); xem {OUT}/<lượt>/docker.log'
    runs, summ = AC.analyze(OUT, FLQ, FLQ['tol'])
    fails = []

    def check(cond, msg):
        if not cond:
            fails.append(msg)

    for run in runs:
        arm, d = run['arm'], run['dir']
        tag = f'{run["channel"]}/{arm}'
        rows = run['rows']
        check(len(rows) == ROUNDS + 1, f'{tag}: có {len(rows)} lần truyền, cần {ROUNDS + 1}')
        bs = json.load(open(d / 'bs' / 'bs_log.json', encoding='utf-8'))
        check(bs['backend'] == 'openfhe', f'{tag}: backend {bs["backend"]}, cần openfhe')
        check(yaml.safe_load(open(d / 'config' / 'model_config.yaml', encoding='utf-8'))['fl']['rounds'] == ROUNDS, f'{tag}: config mount đè sai số vòng')
        ref = ref_acc(arm)
        if ref:
            tol = 1e-9 if arm == 'none' else 0.003
            for t in range(ROUNDS + 1):
                check(abs(rows[t]['acc'] - ref[t]) <= tol, f'{tag}: vòng {t} accuracy {rows[t]["acc"]:.4f} so với lượt tcp {ref[t]:.4f}')
        check(run['n_out_of_tol'] == 0, f'{tag}: {run["n_out_of_tol"]} tin ngoài dung sai thời gian giữ (lệch tối đa {100 * run["dev_rel_max"]:.1f}%)')
        check(run['sum_err'] and max(run['sum_err']) < 1e-6, f'{tag}: sai số tổng giải mã {max(run["sum_err"], default=float("nan")):.2e} (cần dưới 1e-6)')
        check(run['models_diff'] and max(run['models_diff']) == 0.0, f'{tag}: hai client giữ mô hình khác nhau')
        plan = run['plan']
        for key, got in (('upload_B', rows[1]['upload_B']), ('share_B', rows[1]['partial_dec_B'])):
            want = plan[key]
            check((want == 0 and got == 0) or abs(got - want) / want < 0.005, f'{tag}: {key} đo {got:.0f} B so với công thức {want} B')
        stats = AC.read_jsonl(d / 'uav' / 'uav_stats.jsonl')
        held = {r_['type'] for r_ in stats if r_['kind'] == 'msg'}
        passed = {r_['type'] for r_ in stats if r_['kind'] == 'pass'}
        check(held <= set(HELD_TYPES) and 'UPLOAD' in held, f'{tag}: tin bị giữ {held}')
        check(not (passed & set(HELD_TYPES)) and 'HELLO' in passed and 'METRICS' in passed, f'{tag}: tin đi thẳng {passed}')
        check(('PARTIAL_DEC' in held) == (arm == 'ckks_full'), f'{tag}: PARTIAL_DEC bị giữ không đúng với arm')
        lim = json.load(open(d / 'docker_limits.json', encoding='utf-8'))['containers']
        for c in ('uavfl-client1', 'uavfl-client2'):
            check(lim[c]['cpus'] is not None and abs(lim[c]['cpus'] - 1.6) < 0.01 and abs(lim[c]['mem_limit_mib'] - 4096) < 1, f'{tag}: {c} không bị giới hạn 1,6 CPU / 4 GB: {lim[c]}')
        for c in ('uavfl-bs', 'uavfl-uav'):
            check(lim[c]['cpus'] is None, f'{tag}: {c} không được giới hạn CPU')
        s = summ[(run['channel'], arm)]
        print(f'[TEST] {tag}: {len(rows)} lần truyền; acc {100 * rows[0]["acc"]:.2f}% -> {100 * rows[-1]["acc"]:.2f}%; truyền lên {s["t_len_total"]:.2f}s '
              f'(dự kiến {plan["predicted_total_s"]:.2f}s); byte lên {s["bytes_up"]:,.0f} B; lệch thời gian giữ tối đa {100 * run["dev_rel_max"]:.1f}% / '
              f'{run["dev_abs_max"] * 1000:.0f} ms; sai số tổng {max(run["sum_err"]):.1e}; RAM đỉnh client1 {lim["uavfl-client1"].get("peak_mem_mib", float("nan")):.0f} MiB')
    if fails:
        print('LỖI:\n  ' + '\n  '.join(fails))
        return 1
    print(f'[TEST] fl_uav_docker: ĐẠT ({len(runs)} lượt; kết quả ở {OUT})')
    return 0


if __name__ == '__main__':
    sys.exit(main())
