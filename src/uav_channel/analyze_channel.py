"""Gộp kết quả FL chạy thật qua kênh: bảng 2x2 (kênh x arm), kiểm tra tính đúng, hình độ chính xác theo thời gian đồng hồ.

Nguồn (mỗi lượt <kênh>_<arm>/): bs/bs_log.json (đồng hồ BS, byte, độ chính xác), uav/uav_stats.jsonl (ống ghi từng tin và từng mẫu kênh),
client1|2/truth/ (trọng số cục bộ và tổng sau giải mã mỗi vòng), plan.json (dự kiến). MỌI con số trong bảng là số ĐO bằng đồng hồ máy,
trừ cột "dự kiến" (tính từ chuỗi kênh) chỉ để đối chiếu.
Kiểm tra: (1) thời gian giữ từng tin = khung/R trong dung sai max(rel, abs_s); (2) sai số tổng giải mã so với tổng đúng mỗi vòng; (3) hai client giữ mô hình giống nhau.
Chạy: python src/uav_channel/analyze_channel.py [--out outputs/uav_channel/fl_qua_kenh]
Ghi vào --out: per_round.csv, summary_kenh.md, kiem_tra.json, fig_acc_theo_thoi_gian.png.
"""
import argparse
import csv
import json
import sys
from pathlib import Path

import numpy as np
import yaml

SRC = Path(__file__).resolve().parents[1]
ROOT = SRC.parent
sys.path.insert(0, str(SRC))

CONFIG = SRC / 'uav_channel' / 'config.yaml'
LABEL_CH = {'uav_noma_pc': 'Có UAV', 'direct_noma': 'Không UAV'}
LABEL_ARM = {'none': 'Không mã hóa', 'ckks_full': 'CKKS 100%'}
HELD = ('UPLOAD', 'PARTIAL_DEC')


def read_jsonl(path):
    p = Path(path)
    return [json.loads(x) for x in p.read_text(encoding='utf-8').splitlines() if x.strip()] if p.exists() else []


def ok_time(measured, want, rel, abs_s):
    return abs(measured - want) <= max(rel * want, abs_s)


def sum_errors(run_dir, rounds):
    """Mỗi vòng: sai số lớn nhất giữa tổng client1 nhận được sau giải mã và tổng đúng w1*local1 + w2*local2; chênh giữa hai client."""
    err, diff = [], []
    for t in range(rounds):
        z = [np.load(Path(run_dir) / f'client{k}' / 'truth' / f'client{k}_round{t}.npz') for k in (1, 2)]
        exact = float(z[0]['w']) * z[0]['local'] + float(z[1]['w']) * z[1]['local']
        err.append(float(np.abs(z[0]['gsum'] - exact).max()))
        diff.append(float(np.abs(z[0]['gsum'] - z[1]['gsum']).max()))
    return err, diff


def load_run(run_dir, tol):
    run_dir = Path(run_dir)
    bs = json.load(open(run_dir / 'bs' / 'bs_log.json', encoding='utf-8'))
    stats = read_jsonl(run_dir / 'uav' / 'uav_stats.jsonl')
    chans = {r['t']: r for r in stats if r['kind'] == 'channel'}
    msgs = [r for r in stats if r['kind'] == 'msg']
    plan = json.load(open(run_dir / 'plan.json', encoding='utf-8')) if (run_dir / 'plan.json').exists() else {}
    rows = []
    for r in bs['rounds']:
        t = r['t']
        hold = {ty: [m for m in msgs if m['t'] == t and m['type'] == ty] for ty in HELD}
        t_up = max((m['hold_s'] for m in hold['UPLOAD']), default=0.0)
        t_pd = max((m['hold_s'] for m in hold['PARTIAL_DEC']), default=0.0)
        bad = [m for m in hold['UPLOAD'] + hold['PARTIAL_DEC'] if not ok_time(m['hold_s'], m['frame'] / m['rate_Bps'], tol['rel'], tol['abs_s'])]
        ch = chans.get(t, {})
        up_b = float(np.mean(list(r['bytes']['UPLOAD'].values())))
        pd_b = float(np.mean(list(r['bytes'].get('PARTIAL_DEC', {}).values()))) if 'PARTIAL_DEC' in r['bytes'] else 0.0
        rows.append({'t': t, 'acc': r['metrics']['acc'], 't_round_bs_s': r['phase_s']['round'], 't_upload_s': t_up, 't_partial_dec_s': t_pd,
                     't_len_s': t_up + t_pd, 'n_msgs_ngoai_dung_sai': len(bad), 'upload_B': up_b, 'partial_dec_B': pd_b,
                     'R1_Bps': (ch.get('rate_Bps') or [float('nan')] * 2)[0], 'R2_Bps': (ch.get('rate_Bps') or [float('nan')] * 2)[1],
                     'sinr1_db': (ch.get('sinr_db') or [float('nan')] * 2)[0], 'sinr2_db': (ch.get('sinr_db') or [float('nan')] * 2)[1]})
    try:
        err, diff = sum_errors(run_dir, len(rows))
    except FileNotFoundError:
        err, diff = [], []
    dev_rel = [abs(m['hold_s'] - m['frame'] / m['rate_Bps']) / (m['frame'] / m['rate_Bps']) for m in msgs]
    dev_abs = [abs(m['hold_s'] - m['frame'] / m['rate_Bps']) for m in msgs]
    eff = [8 * m['frame'] / m['hold_s'] for m in msgs if m['hold_s'] > 0]
    return {'dir': run_dir, 'arm': bs['arm'], 'channel': (chans[min(chans)]['mode'] if chans else None), 'rows': rows, 'plan': plan,
            'sum_err': err, 'models_diff': diff, 'n_msgs': len(msgs), 'dev_rel_max': max(dev_rel, default=0.0), 'dev_abs_max': max(dev_abs, default=0.0),
            'n_out_of_tol': sum(r['n_msgs_ngoai_dung_sai'] for r in rows), 'eff_bit_s': eff}


def time_to(rows, thr):
    cum = np.cumsum([r['t_round_bs_s'] for r in rows])
    for r, c in zip(rows, cum):
        if r['acc'] >= thr:
            return float(c)
    return None


def fmt_s(x):
    if x is None or x != x:
        return '—'
    return f'{x:.2f} s' if x < 120 else (f'{x / 60:.1f} phút' if x < 7200 else f'{x / 3600:.2f} giờ')


def summarize(runs, flq, tol):
    q = lambda a, p: float(np.percentile(a, p)) if len(a) else float('nan')      # noqa: E731
    out = {}
    for run in runs:
        rows = run['rows']
        t_len = [r['t_len_s'] for r in rows]
        out[(run['channel'], run['arm'])] = {
            'n_transmissions': len(rows), 'final_acc': rows[-1]['acc'], 'acc0': rows[0]['acc'],
            't_len_med': q(t_len, 50), 't_len_p90': q(t_len, 90), 't_len_max': max(t_len), 't_len_total': float(sum(t_len)),
            't_round_total': float(sum(r['t_round_bs_s'] for r in rows)), 'predicted_total': run['plan'].get('predicted_total_s'),
            'eff_med_bit_s': q(run['eff_bit_s'], 50), 'n_msgs': run['n_msgs'], 'n_out_of_tol': run['n_out_of_tol'],
            'dev_rel_max': run['dev_rel_max'], 'dev_abs_max': run['dev_abs_max'],
            'sum_err_max': max(run['sum_err']) if run['sum_err'] else None, 'models_diff_max': max(run['models_diff']) if run['models_diff'] else None,
            'bytes_up': float(np.mean([r['upload_B'] + r['partial_dec_B'] for r in rows])),
            'time_to': {thr: time_to(rows, thr) for thr in flq['targets_acc']}}
    return out


def write_report(runs, summ, flq, tol, out):
    md = ['# FL chạy thật qua kênh: có UAV và không UAV, không mã hóa và CKKS 100%', '',
          f'Sinh bởi `src/uav_channel/analyze_channel.py`. **Mọi con số là số ĐO bằng đồng hồ máy** (ống kênh giữ tin thật), trừ cột "dự kiến" '
          f'(tính từ chuỗi kênh, chỉ để đối chiếu). Vòng 0 cộng {len(runs[0]["rows"]) - 1} vòng = {len(runs[0]["rows"])} lần truyền, '
          f'{flq["local_epochs"]} epoch mỗi vòng, seed FL {flq["seed"]}.', '']
    chs = [c for c in LABEL_CH if any(k[0] == c for k in summ)]
    arms = [x for x in LABEL_ARM if any(k[1] == x for k in summ)]

    def cell(c, x, f):
        s = summ.get((c, x))
        return f(s) if s else '—'

    def table(title, f, note=''):
        md.extend([f'## {title}', ''] + ([note, ''] if note else []))
        md.append('| Phương án | ' + ' | '.join(LABEL_CH[c] for c in chs) + ' |')
        md.append('|---|' + '---|' * len(chs))
        for x in arms:
            md.append(f'| {LABEL_ARM[x]} | ' + ' | '.join(cell(c, x, f) for c in chs) + ' |')
        md.append('')

    table('1. Thời gian truyền lên mỗi vòng (UPLOAD + PARTIAL_DEC, thiết bị chậm hơn quyết định)',
          lambda s: f'trung vị {fmt_s(s["t_len_med"])}, p90 {fmt_s(s["t_len_p90"])}, lớn nhất {fmt_s(s["t_len_max"])}')
    table('2. Tổng thời gian cả lượt', lambda s: f'truyền {fmt_s(s["t_len_total"])}; vòng theo đồng hồ BS {fmt_s(s["t_round_total"])}; '
          f'dự kiến truyền {fmt_s(s["predicted_total"])}', 'Thời gian vòng của BS gồm cả huấn luyện, mã hóa, cộng, ghép thật và chờ kênh.')
    table('3. Độ chính xác và thời gian để đạt', lambda s: f'vòng 0 {100 * s["acc0"]:.2f}%, cuối {100 * s["final_acc"]:.2f}%; ' +
          '; '.join(f'≥{100 * t:g}%: {fmt_s(v)}' for t, v in s['time_to'].items()),
          'Độ chính xác không phụ thuộc kênh (giao thức chờ đủ hai client); thời gian đến mốc tính theo đồng hồ BS cộng dồn. "—" là chưa đạt trong số vòng đã chạy.')
    table('4. Byte gửi lên mỗi client mỗi vòng và tốc độ hiệu dụng', lambda s: f'{s["bytes_up"]:,.0f} B; tốc độ hiệu dụng trung vị {s["eff_med_bit_s"] / 1e3:.1f} kbit/s')
    table('5. Kiểm tra tính đúng', lambda s: f'thời gian giữ từng tin so với khung/R: lệch tương đối lớn nhất {100 * s["dev_rel_max"]:.1f}%, tuyệt đối lớn nhất '
          f'{s["dev_abs_max"] * 1000:.0f} ms, {s["n_out_of_tol"]}/{s["n_msgs"]} tin ngoài dung sai max({100 * tol["rel"]:g}%, {1000 * tol["abs_s"]:g} ms); '
          + (f'sai số tổng giải mã lớn nhất {s["sum_err_max"]:.1e}; hai client giữ mô hình lệch {s["models_diff_max"]:.1e}' if s['sum_err_max'] is not None else 'chưa có truth/'))
    if len(chs) == 2:
        md.extend(['## 6. UAV nhanh hơn bao nhiêu lần (không UAV chia có UAV)', '', '| Phương án | Trung vị truyền mỗi vòng | Tổng thời gian truyền |', '|---|---|---|'])
        for x in arms:
            a, b = summ.get(('uav_noma_pc', x)), summ.get(('direct_noma', x))
            if a and b and a['t_len_med'] > 0 and a['t_len_total'] > 0:
                md.append(f'| {LABEL_ARM[x]} | {b["t_len_med"] / a["t_len_med"]:.1f} lần | {b["t_len_total"] / a["t_len_total"]:.1f} lần |')
        md.append('')
    md.extend(['## Giới hạn', '',
               '- Mô phỏng ở tầng ứng dụng (không mất gói, ACK, trễ lan truyền); đường xuống lý tưởng; hai thiết bị gửi đồng thời, thực tế lệch nhau khoảng 0,1 s; SIC và đồng bộ hoàn hảo.',
               '- Một chuỗi kênh duy nhất (seed trong config.yaml), một mẫu fading cho cả vòng; mô hình đô thị, một điểm hình học; K = 5 dB và NF = 7 dB chưa có nguồn.',
               '- Mã hóa là OpenFHE thật trong container; giả lập Pi 4 của Docker chỉ giới hạn số nhân và RAM, không làm CPU chậm như Pi thật.',
               '- Số vòng ít thì độ chính xác chưa hội tụ; so sánh độ chính xác giữa các phương án chỉ có ý nghĩa ở cùng số vòng.', ''])
    (out / 'summary_kenh.md').write_text('\n'.join(md), encoding='utf-8')


def write_csv(runs, out):
    with open(out / 'per_round.csv', 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        keys = list(runs[0]['rows'][0].keys())
        w.writerow(['kenh', 'arm', 'sai_so_tong'] + keys)
        for run in runs:
            for i, r in enumerate(run['rows']):
                w.writerow([run['channel'], run['arm'], (f'{run["sum_err"][i]:.3e}' if i < len(run['sum_err']) else '')] + [r[k] for k in keys])


def write_fig(runs, out):
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
    except Exception:                                                    # noqa: BLE001
        return
    fig, ax = plt.subplots(figsize=(8, 4.6))
    style = {'uav_noma_pc': '-', 'direct_noma': '--'}
    color = {'none': '#3B6FB6', 'ckks_full': '#C0504D'}
    for run in runs:
        rows = run['rows']
        x = np.cumsum([r['t_round_bs_s'] for r in rows])
        y = [100 * r['acc'] for r in rows]
        c = color.get(run['arm'], 'gray')
        ax.plot(x, y, style.get(run['channel'], '-'), marker='o', ms=3, color=c,
                label=f'{LABEL_CH.get(run["channel"], run["channel"])}, {LABEL_ARM.get(run["arm"], run["arm"])}')
        for xi, yi in zip(x, y):                                         # ghi số giây thật cạnh mỗi chấm (trục log khó đọc số chính xác)
            ax.annotate(fmt_s(xi), (xi, yi), textcoords='offset points', xytext=(4, 6), fontsize=7, color=c)
    ax.set_xscale('log')
    ax.set_xlabel('Thời gian đồng hồ BS cộng dồn (giây, thang log)')
    ax.set_ylabel('Accuracy trên test (%)')
    ax.set_title('Độ chính xác theo thời gian đồng hồ (đo, qua ống kênh)')
    ax.grid(alpha=0.3)
    ax.legend(frameon=False, fontsize=8)
    fig.tight_layout()
    fig.savefig(out / 'fig_acc_theo_thoi_gian.png', dpi=140)
    plt.close(fig)


def analyze(out_root, flq, tol):
    out_root = Path(out_root)
    runs = [load_run(d, tol) for d in sorted(out_root.glob('*_*')) if (d / 'bs' / 'bs_log.json').exists()]
    if not runs:
        raise SystemExit(f'chưa có lượt chạy nào trong {out_root}')
    summ = summarize(runs, flq, tol)
    write_report(runs, summ, flq, tol, out_root)
    write_csv(runs, out_root)
    write_fig(runs, out_root)
    (out_root / 'kiem_tra.json').write_text(json.dumps({f'{k[0]}_{k[1]}': {kk: vv for kk, vv in v.items() if kk != 'time_to'} for k, v in summ.items()},
                                                       ensure_ascii=False, indent=1, default=float), encoding='utf-8')
    return runs, summ


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    cfg = yaml.safe_load(open(CONFIG, encoding='utf-8'))
    flq = cfg['fl_qua_kenh']
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=str(ROOT / flq['out']))
    a = ap.parse_args()
    runs, summ = analyze(a.out, flq, flq['tol'])
    print(f'đã phân tích {len(runs)} lượt -> {a.out}')
    print((Path(a.out) / 'summary_kenh.md').read_text(encoding='utf-8'))


if __name__ == '__main__':
    main()
