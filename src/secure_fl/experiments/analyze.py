"""Tổng hợp so sánh lock (ckks_full, fas) với không lock (none) từ kết quả run_fl_tcp.py: bảng, cổng quyết định, hình.

Đầu vào: outputs/secure_fl/tcp/<model>/seed*.json. Đầu ra: summary_<model>.md, fl_<model>.csv, hình fig_*.png cùng thư mục.
TẠM CHỈ CÒN CỔNG 1 (lock.attack_enabled: false, từ 30/10/2026): bỏ cổng 2 và hình fig_attack_*; bảng cuối chỉ là xếp hạng sơ bộ, chưa xét bảo mật.
Bật lại tấn công bằng attack_enabled: true (xem ghi chú nhãn Δ trong attack_table/figures: nay là TRỌNG SỐ v_k, nhãn cần sửa khi bật lại).
Hai cổng (src/secure_fl/config.yaml `lock`):
  1. Độ chính xác: cận dưới KTC 95% của (acc - acc_none) theo cặp seed >= -δ  (KHÔNG THUA none quá δ, không phải "tương đương").
     Chỉ có 1 seed thì không có KTC: dùng ước lượng điểm của trung bình 10 vòng cuối và ghi rõ.
  2. Rò rỉ: skill = 1 - (‖Δ̂_k-Δ_k‖/‖S-Δ_k‖)^2 <= leak_skill_margin, tức BS không dựng lại Δ_k tốt hơn việc đoán bằng phần tổng S mà nó vốn biết
     (tổng đầy đủ; riêng FAS không có K thì chỉ phần HE vì phần rõ đã xáo).
Cổng 3 (trễ hạn theo kênh) CHƯA ĐO vì chưa có UAV/kênh (src/uav_channel). Ứng viên KHÔNG gồm: none, none_rerun (mốc),
fas_lam0 (chỉ kiểm tra tính đúng), fasbs_* (mốc yếu về bảo mật).
"""
import argparse
import csv
import json
import re
import sys
from pathlib import Path

import numpy as np
import yaml

SRC = Path(__file__).resolve().parents[2]
ROOT = SRC.parent
sys.path.insert(0, str(SRC))

from secure_fl.runlog import archive_existing, install_tee, stamp                # noqa: E402
T975 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228}
COLORS = {'none': '#6B7280', 'none_rerun': '#D1D5DB', 'ckks_full': '#2563EB', 'fas_lam0': '#9CA3AF', 'fas_lam0.01': '#FCD34D',
          'fas_lam0.03': '#FBBF24', 'fas_lam0.1': '#F59E0B', 'fas_lam0.3': '#EA580C', 'fas_lam1': '#B91C1C', 'fasbs_lam0.1': '#7C3AED'}


def label(arm):
    """Tên hiển thị của arm (đọc λ từ tên, nên đổi lưới λ trong config không cần sửa ở đây)."""
    fixed = {'none': 'Không lock', 'none_rerun': 'Không lock (chạy lại)', 'ckks_full': 'Lock A: CKKS 100%'}
    if arm in fixed:
        return fixed[arm]
    m = re.fullmatch(r'(fas|fasbs)_lam([0-9.]+)', arm)
    if not m:
        return arm
    lam = m.group(2).replace('.', ',')
    return f'FAS λ={lam}' if m.group(1) == 'fas' else f'FAS gốc (BS giữ K) λ={lam}'


def color(arm):
    return COLORS.get(arm, '#6B7280')


def is_candidate(arm):
    return arm not in ('none', 'none_rerun', 'fas_lam0') and not arm.startswith('fasbs')


def ci95(d):
    d = np.asarray(d, float)
    n = len(d)
    if n < 2:
        return float(d.mean()), float('nan'), float('nan')
    half = T975.get(n - 1, 1.96) * d.std(ddof=1) / np.sqrt(n)
    return float(d.mean()), float(d.mean() - half), float(d.mean() + half)


def arr(runs, arm, f):
    return np.array([f(r['arms'][arm]) for r in runs if arm in r['arms']], float)


def first_round(rows, thr):
    for r in rows:
        if r['acc'] >= thr:
            return r['round']
    return float('nan')


def pm(x, scale=100.0, nd=2):
    x = np.asarray(x, float) * scale
    return f'{x.mean():.{nd}f}' + (f' ± {x.std(ddof=1):.{nd}f}' if len(x) > 1 else '')


def old_reference():
    """Mốc không lock cũ (src/model, một tiến trình): trung bình 1 lần của 2 mô hình cục bộ và FedAvg 50 vòng bắt đầu từ mô hình khởi tạo."""
    p = ROOT / 'outputs' / 'model' / 'fedavg_50' / 'metrics.json'
    if not p.exists():
        return None
    m = json.load(open(p, encoding='utf-8'))
    return {'oneshot': m['oneshot_average_test_metrics']['accuracy'], 'fedavg': m['test_metrics']['accuracy'], 'rounds': m['rounds']}


def rerun_note(runs, arms):
    """Câu về độ lặp lại của hai lượt `none` — tính từ số liệu thật, không viết sẵn kết quả."""
    if 'none_rerun' not in arms:
        return ''
    ndiff = [sum(abs(p['acc'] - q['acc']) > 1e-12 for p, q in zip(r['arms']['none']['rounds'], r['arms']['none_rerun']['rounds'])) for r in runs]
    pdiff = [r['arms']['none_rerun']['pred_diff_vs_none'] for r in runs]
    if sum(ndiff) == 0 and sum(pdiff) == 0:
        return 'Hai lượt `none` cùng cấu hình cho accuracy giống hệt ở mọi vòng và cùng dự đoán ở mô hình cuối (xem hàng "chạy lại").'
    return (f'Hai lượt `none` cùng cấu hình khác nhau ở {sum(ndiff)} vòng (tổng qua các seed) và {sum(pdiff)} ảnh dự đoán ở mô hình cuối: '
            f'đó là nhiễu nền (PyTorch không tất định), xem hàng "chạy lại".')


def base_final(runs):
    return float(np.mean([r['arms']['none']['final']['acc'] for r in runs]))


def last_mean(a, n=10):
    return float(np.mean([x['acc'] for x in a['rounds'][-n:]]))


def fl_table(runs, arms, delta):
    head = ('| Phương án | Acc vòng 0 (%) | Acc vòng cuối (%) | Acc TB 10 vòng cuối (%) | Macro-F1 | Recall bình thường | Recall khói | Recall lửa | '
            'Ảnh sai | Ảnh khác none | Chênh so với none (điểm) | Đạt cổng 1 | ‖w−w_none‖∞ | Vòng đạt 97,5% | Dao động 5 vòng cuối |')
    lines = [head, '|' + '---|' * 15]
    n = len(runs)
    base_fin = arr(runs, 'none', lambda a: a['final']['acc'])
    base_l10 = arr(runs, 'none', last_mean)
    rows = []
    for arm in arms:
        fin = arr(runs, arm, lambda a: a['final']['acc'])
        l10 = arr(runs, arm, last_mean)
        if n >= 2:
            m, lo, hi = ci95(fin - base_fin)
            ci = f'{100 * m:+.2f} [{100 * lo:+.2f}; {100 * hi:+.2f}]'
            ok_val = lo >= -delta
        else:
            m = float((l10 - base_l10)[0])
            lo = hi = float('nan')
            ci = f'{100 * m:+.2f} (1 seed, TB 10 vòng cuối)'
            ok_val = m >= -delta
        ok = '—' if arm == 'none' else ('có' if ok_val else 'không')
        if not is_candidate(arm) and arm != 'fas_lam0':
            ok = '—'
        drift = arr(runs, arm, lambda a: a['rounds'][-1]['drift_linf'])
        r975 = arr(runs, arm, lambda a: first_round(a['rounds'], 0.975))
        tail = np.array([np.std([x['acc'] for x in r['arms'][arm]['rounds'][-5:]], ddof=1) for r in runs])
        r0 = arr(runs, arm, lambda a: a['round0']['acc'])
        # Các cột trong CSV: hai cách đo độ chính xác tách bạch (vòng cuối / trung bình 10 vòng cuối) để diff luôn = hiệu của đúng hai cột acc
        rows.append({'arm': arm, 'acc_final': fin.mean(), 'acc_last10': l10.mean(), 'acc_std_giua_cac_seed': fin.std(ddof=1) if n > 1 else '',
                     'diff_final': float((fin - base_fin).mean()), 'diff_last10': float((l10 - base_l10).mean()),
                     'ci95_lo': '' if n < 2 else lo, 'ci95_hi': '' if n < 2 else hi,
                     'gate1': ok, 'gate1_dua_tren': 'ci95 cua diff_final' if n >= 2 else 'diff_last10 (1 seed, khong co ci95)',
                     'anh_khac_none': arr(runs, arm, lambda a: a['pred_diff_vs_none']).mean(), 'drift_linf': drift.mean()})
        lines.append(
            f'| {label(arm)} | {pm(r0)} | {pm(fin)} | {pm(l10)} | {pm(arr(runs, arm, lambda a: a["final"]["f1"]), 1, 3)} | '
            f'{pm(arr(runs, arm, lambda a: a["final"]["recall_binh_thuong"]), 1, 3)} | '
            f'{pm(arr(runs, arm, lambda a: a["final"]["recall_khoi"]), 1, 3)} | '
            f'{pm(arr(runs, arm, lambda a: a["final"]["recall_lua"]), 1, 3)} | '
            f'{pm(arr(runs, arm, lambda a: a["final_errors"]), 1, 1)} | '
            f'{arr(runs, arm, lambda a: a["pred_diff_vs_none"]).mean():.1f} | {"—" if arm == "none" else ci} | {ok} | {drift.mean():.1e} | '
            f'{(np.nanmean(r975) if not np.all(np.isnan(r975)) else float("nan")):.1f} | {100 * tail.mean():.2f} |')
    return lines, rows


def attack_table(runs, arms, margin):
    lines = ['| Phương án | cos(Δ̂_k, Δ_k) | cos(tổng BS biết, Δ_k) | Sai số dựng lại ‖Δ̂−Δ‖/‖Δ‖ | Sai số khi đoán bằng tổng BS biết | Skill | '
             'Accuracy mô hình BS dựng lại (%) | Accuracy khi chỉ dùng tổng BS biết (%) | Đạt cổng 2 |', '|---|---|---|---|---|---|---|---|---|']
    res = {}
    for arm in arms:
        def m(key):
            return float(np.mean([np.mean([x[key] for x in r['arms'][arm]['attacks']]) for r in runs]))
        e, e_ref = m('rel_err'), m('rel_ref')
        res[arm] = {'cos': m('cos'), 'ref': m('cos_ref'), 'rel': e, 'rel_ref': e_ref, 'acc': m('acc'), 'acc_ref': m('acc_ref'), 'skill': 1 - (e / e_ref) ** 2}
        res[arm]['gate2'] = 'có' if res[arm]['skill'] <= margin else 'không'
        lines.append(f'| {label(arm)} | {res[arm]["cos"]:.3f} | {res[arm]["ref"]:.3f} | {e:.2f} | {e_ref:.2f} | {res[arm]["skill"]:+.2f} | '
                     f'{100 * res[arm]["acc"]:.1f} | {100 * res[arm]["acc_ref"]:.1f} | {res[arm]["gate2"]} |')
    return lines, res


def attack_on(lock):
    """Có đánh giá tấn công (cổng 2) không. Tạm tắt từ 30/10/2026: lock.attack_enabled = false."""
    return bool(lock.get('attack_enabled', False))


def select_best(fl_rows, att, cost):
    """Cổng 1 (+ cổng 2 nếu att không None) rồi xếp theo byte. Trả về (các dòng, arm tốt nhất hoặc None).
    Mỗi dòng: (arm, gate1, gate2 hoặc None, byte lên, đạt không). Khi att = None thì chỉ xét cổng 1 và kết quả chỉ là xếp hạng SƠ BỘ (chưa xét bảo mật)."""
    rows, passed = [], []
    for fr in fl_rows:
        arm = fr['arm']
        if not is_candidate(arm):
            continue
        g2 = att[arm]['gate2'] if att is not None else None
        ok = fr['gate1'] == 'có' and g2 in (None, 'có')
        rows.append((arm, fr['gate1'], g2, cost[arm]['up_total'], ok))
        if ok:
            passed.append((cost[arm]['up_total'], cost[arm]['round'], arm))
    return rows, (min(passed)[2] if passed else None)


def cost_table(runs, arms):
    lines = ['| Phương án | Ciphertext | UPLOAD + PARTIAL_DEC (B/client/vòng) | Phình so với rõ | Chiều xuống (B/client/vòng) | '
             'Bảo vệ tại client (ms) | BS cộng (ms) | BS ghép (ms) | Giải mã từng phần (ms) | Vòng đầu-cuối trên localhost (s) |',
             '|' + '---|' * 10]
    cost = {}
    for arm in arms:
        b = lambda k: np.mean([r['arms'][arm]['bytes_per_client'][k] for r in runs])        # noqa: E731
        t = lambda k: np.mean([r['arms'][arm]['time_s'][k] for r in runs])                  # noqa: E731
        cost[arm] = {'up_total': b('up_total'), 'round': t('round')}
        lines.append(f'| {label(arm)} | {runs[0]["arms"][arm]["n_ct"]} | {b("up_total"):,.0f} | {b("expansion_vs_plain"):.1f}× | '
                     f'{b("down_total"):,.0f} | {1000 * t("protect"):.1f} | {1000 * t("bs_aggregate"):.1f} | {1000 * t("bs_fuse"):.1f} | '
                     f'{1000 * t("partial_dec"):.1f} | {t("round"):.2f} |')
    return lines, cost


def figures(runs, arms, out, model, with_attack=False):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({'font.size': 10, 'axes.spines.top': False, 'axes.spines.right': False})
    R = runs[0]['rounds']                       # vòng 0..R
    fig, ax = plt.subplots(1, 2, figsize=(12.5, 4.4))
    for arm in arms:
        if arm.startswith('fasbs') or arm in ('fas_lam0', 'none_rerun'):
            continue
        acc = np.array([[x['acc'] for x in r['arms'][arm]['rounds']] for r in runs]) * 100
        ax[0].plot(range(0, R + 1), acc.mean(0), color=color(arm), lw=2 if arm in ('none', 'ckks_full') else 1.4,
                   ls='--' if arm == 'ckks_full' else '-', label=label(arm))
    ax[0].set_ylim(90, 99.5)
    ax[0].set_xlabel('Vòng')
    ax[0].set_ylabel('Accuracy test (%), trung bình qua seed')
    ax[0].legend(frameon=False, fontsize=8, loc='lower right')
    ax[0].set_title('Độ chính xác theo vòng')
    lam_arms = [a for a in arms if a.startswith('fas_lam')]
    lams = [float(a.replace('fas_lam', '')) for a in lam_arms]
    ms = [arr(runs, a, lambda x: x['final']['acc']) * 100 for a in lam_arms]
    base = arr(runs, 'none', lambda x: x['final']['acc']) * 100
    sd0 = base.std(ddof=1) if len(base) > 1 else 0.0
    ax[1].axhspan(base.mean() - sd0, base.mean() + sd0, color='#9CA3AF', alpha=0.25, label='Không lock ± 1 độ lệch chuẩn')
    ax[1].errorbar(lams, [m.mean() for m in ms], [m.std(ddof=1) if len(m) > 1 else 0 for m in ms], color='#B91C1C', marker='o', capsize=3, label='FAS (p=10%)')
    ax[1].axhline(arr(runs, 'ckks_full', lambda x: x['final']['acc']).mean() * 100, color='#2563EB', ls='--', label='CKKS 100%')
    ax[1].set_xscale('symlog', linthresh=0.01)
    ax[1].set_xlabel('λ (nhiễu = λ·RMS phần rõ)')
    ax[1].set_ylabel('Accuracy vòng cuối (%)')
    ax[1].legend(frameon=False, fontsize=8)
    ax[1].set_title('Ảnh hưởng của nhiễu FAS')
    fig.tight_layout()
    fig.savefig(out / f'fig_accuracy_{model}.png', dpi=140)
    plt.close(fig)
    if not with_attack:
        return

    names = [a for a in arms if a != 'none_rerun']
    fig, ax = plt.subplots(1, 2, figsize=(12.5, 4.2))
    cs = [np.mean([np.mean([x['cos'] for x in r['arms'][a]['attacks']]) for r in runs]) for a in names]
    ref = np.mean([np.mean([x['cos_ref'] for x in r['arms'][names[0]]['attacks']]) for r in runs])
    ax[0].barh([label(a) for a in names], cs, color=[color(a) for a in names])
    ax[0].axvline(ref, color='#2563EB', ls='--', lw=1)
    ax[0].invert_yaxis()
    ax[0].set_xlabel('cos(Δ̂_k, Δ_k): BS dựng lại cập nhật của client k')
    ax[0].set_title('Rò rỉ (nét đứt: mức ai biết tổng cũng đoán được)')
    acs = [np.mean([np.mean([x['acc'] for x in r['arms'][a]['attacks']]) for r in runs]) * 100 for a in names]
    ax[1].barh([label(a) for a in names], acs, color=[color(a) for a in names])
    ax[1].invert_yaxis()
    ax[1].set_xlim(30, 100)
    ax[1].set_xlabel('Accuracy (%) của mô hình BS dựng lại cho client k')
    ax[1].set_title('Mô hình BS dựng được')
    fig.tight_layout()
    fig.savefig(out / f'fig_attack_{model}.png', dpi=140)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--model', default='classifier')
    ap.add_argument('--out', default='outputs/secure_fl/tcp')
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding='utf-8')
    lock = yaml.safe_load(open(SRC / 'secure_fl' / 'config.yaml', encoding='utf-8'))['lock']
    out = ROOT / a.out / a.model
    install_tee(out / 'logs' / f'analyze_{stamp()}.log')            # giữ bản in của MỖI lần phân tích (summary_*.md bị ghi đè)
    runs = [json.load(open(p, encoding='utf-8')) for p in sorted(out.glob('seed*.json'))]
    if not runs:
        raise SystemExit(f'chưa có kết quả trong {out}')
    arms = [x for x in runs[0]['arms'] if all(x in r['arms'] for r in runs)]
    seeds = [r['seed'] for r in runs]
    md = [f'# So sánh lock và không lock — mô hình `{a.model}` ({runs[0]["M"]:,} tham số), {len(runs)} seed {seeds}, '
          f'vòng 0 (tổng hợp trọng số 150 epoch qua bảo vệ) + {runs[0]["rounds"]} vòng × 1 epoch, BS và 2 client là 3 tiến trình qua TCP (không UAV), '
          f'backend HE `{runs[0]["backend"]}`', '']
    if runs[0]['backend'] == 'emulated':
        md += ['> **Lưu ý:** backend `emulated` KHÔNG mã hóa; nó chỉ mô hình hóa sai số CKKS và đệm gói đúng cỡ ciphertext đã đo (số đo cũ). '
               'Kết quả độ chính xác và byte hợp lệ trong giới hạn đó; thời gian mã hóa/giải mã và mọi nhận định về bảo mật của phần HE '
               'KHÔNG đến từ OpenFHE thật.', '']
    md += [f'## 1. Ảnh hưởng tới FL (cổng 1: không thua none quá δ = {100 * lock["delta_acc"]:.1f} điểm)', '']
    fl_lines, fl_rows = fl_table(runs, arms, lock['delta_acc'])
    md += fl_lines + ['']
    ref = old_reference()
    if ref:
        a0 = arr(runs, 'none', lambda x: x['round0']['acc'])[0] if len(runs) == 1 else arr(runs, 'none', lambda x: x['round0']['acc']).mean()
        md += [f'Đối chiếu nhánh `none` (đường mới qua BS + client): acc vòng 0 = {100 * a0:.2f}% so với "trung bình 1 lần" cũ {100 * ref["oneshot"]:.2f}% '
               f'(phải trùng, vì cùng là trung bình có trọng số hai mô hình cục bộ); acc vòng cuối = {100 * base_final(runs):.2f}% so với FedAvg {ref["rounds"]} vòng cũ '
               f'{100 * ref["fedavg"]:.2f}% (cũ bắt đầu từ mô hình khởi tạo nên không nhất thiết trùng). '
               + rerun_note(runs, arms), '']
    with_attack = attack_on(lock)
    att = None
    if with_attack:
        md += ['## 2. Rò rỉ về client k (cổng 2)', '']
        at_lines, att = attack_table(runs, arms, lock['leak_skill_margin'])
        md += at_lines + ['']
        md += ['Kẻ tấn công = BS tò mò, biết g_{t-1}, n_k và tổng Δ nếu giao thức cho biết. Skill = 1 − (sai số dựng lại / sai số khi đoán bằng phần tổng BS vốn biết)²: '
               '1 là dựng lại hoàn hảo, 0 là chỉ ngang việc đoán bằng tổng, âm là tệ hơn. Với FAS giữ khóa ở thiết bị, kẻ tấn công bỏ qua phần rõ đã xáo '
               '(không biết vị trí) nên skill = 0 theo cách xây dựng; tác dụng của khóa thể hiện ở chênh lệch với FAS gốc (BS giữ K). Với 2 thiết bị, cập nhật của hai client rất giống nhau nên '
               'chính cos(tổng, Δ_k) đã cao; so cos trực tiếp không phân biệt được các phương án (đã thử, xem lịch sử), vì vậy dùng skill.', '']
    n_cost, n_pick = ('3', '4') if with_attack else ('2', '3')                    # không có mục rò rỉ khi tắt tấn công
    md += [f'## {n_cost}. Chi phí truyền thông và thời gian (đo thật trên localhost, chưa có kênh)', '']
    c_lines, cost = cost_table(runs, arms)
    md += c_lines + ['']
    md += ['Thời gian vòng gồm huấn luyện của client trong giả lập Pi 4 (chỉ giới hạn số nhân và RAM, không làm chậm CPU như Cortex-A72) và không có độ trễ mạng nên chỉ để so sánh tương đối. '
           'Cổng trễ hạn theo tốc độ kênh chưa đo vì chưa có UAV.', '']
    sel, best = select_best(fl_rows, att, cost)
    if with_attack:
        md += [f'## {n_pick}. Qua hai cổng', '']
        md += ['| Phương án | Cổng 1 (độ chính xác) | Cổng 2 (rò rỉ) | Byte lên/vòng/client | Kết luận |', '|---|---|---|---|---|']
        for arm, g1, g2, up, ok in sel:
            md.append(f'| {label(arm)} | {g1} | {g2} | {up:,.0f} | {"đạt cả 2" if ok else "rớt"} |')
        md += ['', f'Phương án tốt nhất (đạt cả 2 cổng, ít byte nhất): **{label(best) if best else "không có phương án nào đạt"}**.', '']
    else:
        md += [f'## {n_pick}. Chọn phương án theo độ chính xác và chi phí', '']
        md += ['| Phương án | Cổng độ chính xác | Byte lên/vòng/client | Kết luận |', '|---|---|---|---|']
        for arm, g1, _, up, ok in sel:
            md.append(f'| {label(arm)} | {g1} | {up:,.0f} | {"qua cổng" if ok else "rớt"} |')
        md += ['', f'Xếp hạng SƠ BỘ (qua cổng độ chính xác, ít byte nhất): **{label(best) if best else "không có phương án nào qua cổng"}**. '
                   '**Chưa phải kết luận chọn phương pháp tốt nhất**, vì chưa xét mức bảo mật và chưa xét kênh.', '']
    for fn in (f'summary_{a.model}.md', f'fl_{a.model}.csv', f'fig_accuracy_{a.model}.png') + ((f'fig_attack_{a.model}.png',) if with_attack else ()):
        archive_existing(out / fn)                                   # giữ bản cũ trong lich_su/ trước khi ghi đè
    (out / f'summary_{a.model}.md').write_text('\n'.join(md), encoding='utf-8')
    with open(out / f'fl_{a.model}.csv', 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=list(fl_rows[0]))
        w.writeheader()
        w.writerows(fl_rows)
    figures(runs, arms, out, a.model, with_attack)
    print('\n'.join(md))


if __name__ == '__main__':
    main()
