"""Kiểm thử analyze_channel.py bằng dữ liệu GIẢ có đáp án biết trước (không cần Docker): thời gian truyền, dung sai, sai số tổng, thời gian đạt mốc, bảng, CSV.
Chạy: python tests/uav_channel/test_analyze_channel.py"""
import json
import sys
import tempfile
from pathlib import Path

import numpy as np
import yaml

sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))

from uav_channel import analyze_channel as AC

CFG = yaml.safe_load(open(ROOT / 'src' / 'uav_channel' / 'config.yaml', encoding='utf-8'))
FLQ = CFG['fl_qua_kenh']
TOL = FLQ['tol']
N = 3                                                                     # số lần truyền (vòng 0..2) của dữ liệu giả
COMPUTE_S = 2.0                                                           # thời gian tính giả mỗi vòng
UP, PD = 6220, 66411                                                      # byte khung giả (PD chỉ dùng cho ckks_full)


def make_run(root, channel, arm, rate, bad_msg=None, sum_noise=1e-8):
    """Tạo thư mục một lượt chạy giả. rate = tốc độ byte/s của cả hai thiết bị ở mọi vòng; bad_msg = (vòng, thiết bị) có thời gian giữ gấp đôi."""
    d = Path(root) / f'{channel}_{arm}'
    for sub in ('bs', 'uav', 'client1/truth', 'client2/truth'):
        (d / sub).mkdir(parents=True, exist_ok=True)
    frames = {'UPLOAD': UP, **({'PARTIAL_DEC': PD} if arm == 'ckks_full' else {})}
    t_len = sum(f / rate for f in frames.values())
    rounds, lines = [], [json.dumps({'kind': 'start', 'mode': channel})]
    for t in range(N):
        by = {'UPLOAD': {'1': UP, '2': UP}}
        if arm == 'ckks_full':
            by['PARTIAL_DEC'] = {'1': PD, '2': PD}
        rounds.append({'t': t, 'bytes': by, 'phase_s': {'round': COMPUTE_S + t_len}, 'metrics': {'acc': 0.970 + 0.004 * t}})
        lines.append(json.dumps({'kind': 'channel', 't': t, 'mode': channel, 'sinr_db': [5.0, 4.0], 'rate_bps': [8 * rate] * 2, 'rate_Bps': [rate, rate]}))
        for ty, fr in frames.items():
            for dev in (1, 2):
                scale = 2.0 if bad_msg == (t, dev) and ty == 'UPLOAD' else 1.0
                lines.append(json.dumps({'kind': 'msg', 'dev': dev, 'type': ty, 't': t, 'frame': fr, 'n_packets': 5, 'rate_Bps': rate,
                                         'hold_s': scale * fr / rate, 'start_ts': 0.0}))
    (d / 'bs' / 'bs_log.json').write_text(json.dumps({'arm': arm, 'rounds': rounds}), encoding='utf-8')
    (d / 'uav' / 'uav_stats.jsonl').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    (d / 'plan.json').write_text(json.dumps({'predicted_total_s': N * t_len}), encoding='utf-8')
    rng = np.random.default_rng(1)
    for t in range(N):
        l1, l2 = rng.normal(size=10), rng.normal(size=10)
        gsum = 0.5 * l1 + 0.5 * l2 + sum_noise
        for k, loc in ((1, l1), (2, l2)):
            np.savez(d / f'client{k}' / 'truth' / f'client{k}_round{t}.npz', local=loc, g_prev=np.zeros(10), gsum=gsum, w=np.float64(0.5))
    return d, t_len


def test_load_run_values():
    with tempfile.TemporaryDirectory() as tmp:
        d, t_len = make_run(tmp, 'direct_noma', 'ckks_full', rate=1000.0)
        run = AC.load_run(d, TOL)
    assert run['arm'] == 'ckks_full' and run['channel'] == 'direct_noma' and len(run['rows']) == N
    assert all(abs(r['t_len_s'] - t_len) < 1e-9 for r in run['rows']), 'T_lên = T_UPLOAD + T_PARTIAL_DEC'
    assert abs(run['rows'][0]['t_upload_s'] - UP / 1000.0) < 1e-9 and abs(run['rows'][0]['t_partial_dec_s'] - PD / 1000.0) < 1e-9
    assert run['n_out_of_tol'] == 0 and run['dev_rel_max'] < 1e-9
    assert max(run['sum_err']) < 1e-7 and max(run['models_diff']) == 0.0
    assert abs(run['rows'][1]['upload_B'] - UP) < 1e-9 and abs(run['rows'][1]['partial_dec_B'] - PD) < 1e-9
    print(f'[TEST] A. load_run: T_lên = UPLOAD + PARTIAL_DEC = {t_len:.2f}s đúng; byte, sai số tổng ({max(run["sum_err"]):.1e}), hai client giữ mô hình giống nhau')


def test_tolerance_detects_bad_message():
    with tempfile.TemporaryDirectory() as tmp:
        d, _ = make_run(tmp, 'direct_noma', 'none', rate=1000.0, bad_msg=(1, 2))
        run = AC.load_run(d, TOL)
    assert run['n_out_of_tol'] == 1 and run['rows'][1]['n_msgs_ngoai_dung_sai'] == 1 and run['dev_rel_max'] > 0.9
    assert AC.ok_time(1.00, 1.04, 0.05, 0.03) and not AC.ok_time(1.0, 1.2, 0.05, 0.03) and AC.ok_time(0.05, 0.03, 0.05, 0.03)
    print('[TEST] B. Một tin bị giữ gấp đôi được phát hiện là ngoài dung sai max(5%, 30 ms); tin lệch nhỏ và tin ngắn lệch dưới 30 ms thì chấp nhận')


def test_sum_error_detected():
    with tempfile.TemporaryDirectory() as tmp:
        d, _ = make_run(tmp, 'uav_noma_pc', 'none', rate=1e6, sum_noise=1e-3)
        run = AC.load_run(d, TOL)
    assert 0.9e-3 < max(run['sum_err']) < 1.1e-3
    print(f'[TEST] C. Sai số tổng giải mã 1e-3 được đo đúng ({max(run["sum_err"]):.2e}); bình thường phải dưới 1e-6')


def test_time_to_threshold_and_report():
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / 'ket_qua'
        make_run(out, 'uav_noma_pc', 'none', rate=1e6)
        make_run(out, 'uav_noma_pc', 'ckks_full', rate=1e6)
        make_run(out, 'direct_noma', 'none', rate=1e3)
        d4, t_len = make_run(out, 'direct_noma', 'ckks_full', rate=1e3)
        runs, summ = AC.analyze(out, FLQ, TOL)
        assert len(runs) == 4 and set(summ) == {(c, a) for c in ('uav_noma_pc', 'direct_noma') for a in ('none', 'ckks_full')}
        s = summ[('direct_noma', 'ckks_full')]
        cum2 = 3 * (COMPUTE_S + t_len)                                    # acc vòng 2 = 0.978 vượt 0.975 nhưng chưa tới 0.98
        assert abs(s['time_to'][0.975] - cum2) < 1e-6 and s['time_to'][0.98] is None
        assert abs(s['t_len_total'] - 3 * t_len) < 1e-9 and abs(s['predicted_total'] - 3 * t_len) < 1e-9
        ratio = summ[('direct_noma', 'none')]['t_len_med'] / summ[('uav_noma_pc', 'none')]['t_len_med']
        assert abs(ratio - 1000.0) < 1e-6
        md = (out / 'summary_kenh.md').read_text(encoding='utf-8')
        for must in ('Có UAV', 'Không UAV', 'CKKS 100%', 'Không mã hóa', '## 6. UAV nhanh hơn', '1000.0 lần', 'ĐO bằng đồng hồ', '—'):
            assert must in md, f'thiếu "{must}" trong summary_kenh.md'
        rows = (out / 'per_round.csv').read_text(encoding='utf-8').strip().splitlines()
        assert len(rows) == 1 + 4 * N and rows[0].startswith('kenh,arm,sai_so_tong')
        ck = json.loads((out / 'kiem_tra.json').read_text(encoding='utf-8'))
        assert set(ck) == {'uav_noma_pc_none', 'uav_noma_pc_ckks_full', 'direct_noma_none', 'direct_noma_ckks_full'}
        try:
            import matplotlib  # noqa: F401
            assert (out / 'fig_acc_theo_thoi_gian.png').stat().st_size > 1000
        except ImportError:
            pass
    print(f'[TEST] D. analyze: 4 lượt -> thời gian đạt 97,5% = {cum2:.1f}s (đúng), mốc 98% chưa đạt ghi "—", UAV nhanh hơn 1000 lần, '
          f'per_round.csv {len(rows)} dòng, kiem_tra.json, hình')


def test_fmt_s():
    assert AC.fmt_s(None) == '—' and AC.fmt_s(float('nan')) == '—' and AC.fmt_s(5.0) == '5.00 s' and AC.fmt_s(600.0) == '10.0 phút' and AC.fmt_s(36000.0) == '10.00 giờ'
    print('[TEST] E. fmt_s hiển thị giây, phút, giờ đúng; thiếu số liệu hiển thị "—"')


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
    print('[TEST] analyze_channel: ' + ('ĐẠT' if not fails else f'LỖI ({fails})'))
    sys.exit(1 if fails else 0)
