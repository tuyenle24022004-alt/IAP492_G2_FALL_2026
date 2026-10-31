"""Kiểm tra ĐỘC LẬP rằng số trong báo cáo khớp số gốc: tính lại từ từng arm (bs_log.json, client*_log.json) KHÔNG qua seed42.json,
collect.py hay analyze.py, rồi tìm đúng chuỗi số đó trong báo cáo. Có số nào không tìm thấy thì báo LỖI.
Chạy: python src/secure_fl/experiments/audit_report.py   (ghi log vào outputs/secure_fl/tcp/classifier/logs/audit_<giờ>.log)"""
import glob
import json
import sys
from pathlib import Path

import numpy as np

SRC = Path(__file__).resolve().parents[2]
ROOT = SRC.parent
sys.path.insert(0, str(SRC))

from secure_fl.runlog import install_tee, stamp                                  # noqa: E402

BASE = ROOT / 'outputs' / 'secure_fl' / 'tcp' / 'classifier'
REPORT = ROOT / 'report' / 'bao_cao_so_sanh_ma_hoa_khong_mahoa.md'


def main():
    install_tee(BASE / 'logs' / f'audit_{stamp()}.log')
    text = REPORT.read_text(encoding='utf-8')
    rows, bad = [], 0
    for d in sorted(glob.glob(str(BASE / 'seed42' / '*'))):
        d = Path(d)
        if not (d / 'bs_log.json').exists():
            continue
        bs = json.load(open(d / 'bs_log.json', encoding='utf-8'))
        rounds = bs['rounds']
        acc = [r['metrics']['acc'] for r in rounds]
        n = len(rounds)
        up = np.mean([[r['bytes']['UPLOAD'][str(k)] for k in (1, 2)] for r in rounds])
        sh = np.mean([[r['bytes'].get('PARTIAL_DEC', {}).get(str(k), 0) for k in (1, 2)] for r in rounds])
        down = np.mean([[r['bytes'].get('CSUM', {}).get(str(k), 0) + r['bytes']['AGGREGATE'][str(k)] for k in (1, 2)] for r in rounds])
        checks = {
            'acc vòng 0': f'{100 * acc[0]:.2f}',
            'acc vòng cuối': f'{100 * acc[-1]:.2f}',
            'acc TB 10 vòng cuối': f'{100 * np.mean(acc[-10:]):.2f}',
            'byte lên (UPLOAD+PARTIAL_DEC)': f'{up + sh:,.0f}',
            'byte UPLOAD': f'{up:,.0f}',
            'byte PARTIAL_DEC': f'{sh:,.0f}',
            'byte xuống': f'{down:,.0f}',
        }
        def mb(key, devs=('1', '2')):
            v = [r['bytes'][key][d] for r in rounds if key in r['bytes'] for d in devs if d in r['bytes'][key]]
            return float(np.mean(v)) if v else 0.0
        checks['byte ROUND_START'] = f'{mb("ROUND_START"):,.0f}'
        checks['byte CSUM'] = f'{mb("CSUM"):,.0f}'
        checks['byte AGGREGATE'] = f'{mb("AGGREGATE"):,.0f}'
        checks['byte METRICS (client1)'] = f'{mb("METRICS", ("1",)):,.0f}'
        for m in (0, 1, 2, 5, 10, 20, 30, 40, 50):
            checks[f'acc vòng {m}'] = f'{100 * acc[m]:.2f}'
        # sai khác tổng so với tổng đúng: tính lại từ trọng số thật của hai client (truth/) và tổng client1 nhận được
        ee = []
        for t in range(n):
            z1 = np.load(d / 'truth' / f'client1_round{t}.npz')
            z2 = np.load(d / 'truth' / f'client2_round{t}.npz')
            exact = float(z1['w']) * z1['local'] + float(z2['w']) * z2['local']
            ee.append(float(np.abs(z1['gsum'] - exact).max()))
        checks['sai khác tổng, vòng 0'] = f'{ee[0]:.1e}'
        checks['sai khác tổng, TB các vòng'] = f'{np.mean(ee):.1e}'
        checks['sai khác tổng, lớn nhất'] = f'{max(ee):.1e}'
        g1, g2 = np.load(d / 'g_client1.npy'), np.load(d / 'g_client2.npy')
        checks['‖g1−g2‖∞'] = f'{np.abs(g1 - g2).max():.1e}'
        # bằng chứng giả lập Pi 4 của hai client (đọc thẳng device_limits_client*.json)
        l1 = json.load(open(d / 'device_limits_client1.json', encoding='utf-8'))['do_thuc_te']
        l2 = json.load(open(d / 'device_limits_client2.json', encoding='utf-8'))['do_thuc_te']
        checks['working set đỉnh client1 / client2'] = f'{l1["working_set_dinh_mib"]:.0f} / {l2["working_set_dinh_mib"]:.0f}'
        checks['commit đỉnh client1 / client2'] = f'{l1["commit_dinh_mib"]:.0f} / {l2["commit_dinh_mib"]:.0f}'
        checks['số nhân TB client1 / client2'] = f'{l1["so_nhan_trung_binh"]:.2f} / {l2["so_nhan_trung_binh"]:.2f}'
        for name, s in checks.items():
            ok = s in text
            bad += not ok
            rows.append((d.name, name, s, 'KHỚP' if ok else 'KHÔNG THẤY TRONG BÁO CÁO'))
    print(f'Kiểm tra {len(rows)} con số tính lại từ log từng arm so với {REPORT.name}\n')
    print(f'{"arm":<14}{"chỉ số":<32}{"giá trị tính lại":<18}kết quả')
    for r in rows:
        print(f'{r[0]:<14}{r[1]:<32}{r[2]:<18}{r[3]}')
    # số của test mã hóa thật
    tl = sorted(glob.glob(str(ROOT / 'outputs' / 'secure_fl' / 'tests' / '*' / 'docker_test_openfhe.log')))[-1]
    for line in Path(tl).read_text(encoding='utf-8').splitlines():
        if '[TEST]' in line and 'sai số' in line:
            line = line.replace('[TEST] ', '')
            ok = line in text
            bad += not ok
            print(f'\ntest_openfhe: "{line}" -> {"KHỚP" if ok else "KHÔNG THẤY TRONG BÁO CÁO"}')
    print(f'\nTỔNG: {len(rows)} số, {bad} không khớp -> {"ĐẠT" if bad == 0 else "LỖI"}')
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
