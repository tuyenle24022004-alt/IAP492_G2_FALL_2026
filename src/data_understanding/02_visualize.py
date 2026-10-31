import json

import numpy as np
import pandas as pd
import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt

import common as C

plt.rcParams.update({
    'figure.dpi': 110, 'savefig.dpi': 160, 'font.size': 10, 'axes.titlesize': 12, 'axes.titleweight': 'bold',
    'axes.spines.top': False, 'axes.spines.right': False, 'axes.grid': True, 'grid.alpha': 0.25,
    'axes.axisbelow': True, 'figure.facecolor': 'white',
})

FEATURES = [('brightness', 'Độ sáng'), ('contrast', 'Độ tương phản'), ('saturation', 'Độ bão hòa'),
            ('sharpness', 'Độ nét'), ('warm_ratio', 'Tỷ lệ màu nóng'), ('gray_ratio', 'Tỷ lệ xám sáng'),
            ('width', 'Chiều rộng'), ('height', 'Chiều cao'), ('file_kb', 'Dung lượng KB')]


def save(fig, name):
    fig.tight_layout()
    fig.savefig(C.FIG / name, bbox_inches='tight')
    plt.close(fig)
    print(f'[visual] {name}', flush=True)


def fig_split_counts(m):
    fig, axes = plt.subplots(1, 2, figsize=(14, 4.8))
    ax = axes[0]
    bottom = np.zeros(len(C.SETS))
    for l in C.CLASSES:
        v = m.loc[C.SETS, l].to_numpy()
        ax.bar([t.replace('_', chr(10)) for t in C.SETS], v, bottom=bottom, color=C.COLORS[l], label=C.CLASS_VI[l])
        for i, (b, vi) in enumerate(zip(bottom, v)):
            if vi > m.tong.max() * 0.04:
                ax.text(i, b + vi / 2, f'{vi:,}', ha='center', va='center', color='white', fontsize=9, fontweight='bold')
        bottom += v
    for i, t in enumerate(C.SETS):
        ax.text(i, bottom[i], f'{int(m.loc[t, "tong"]):,}', ha='center', va='bottom', fontweight='bold')
    ax.set_ylabel('Số ảnh')
    ax.set_title('Số lượng ảnh theo tập')
    ax.legend(frameon=False)
    ax.grid(axis='x', visible=False)
    ax = axes[1]
    pct = m[C.CLASSES].div(m.tong, axis=0).loc[C.SETS] * 100
    left = np.zeros(len(C.SETS))
    for l in C.CLASSES:
        v = pct[l].to_numpy()
        ax.barh([t.replace('_', ' ') for t in C.SETS], v, left=left, color=C.COLORS[l], label=C.CLASS_VI[l])
        for i, (b, vi) in enumerate(zip(left, v)):
            if vi > 6:
                ax.text(b + vi / 2, i, f'{vi:.0f}%', ha='center', va='center', color='white', fontsize=9, fontweight='bold')
        left += v
    ax.invert_yaxis()
    ax.set_xlim(0, 100)
    ax.set_xlabel('Tỷ lệ lớp trong tập (%)')
    ax.set_title('Cơ cấu lớp trong từng tập')
    ax.grid(axis='y', visible=False)
    save(fig, '01_split_counts.png')


def fig_split_overview(m):
    tot = m.tong
    parts = [(t.replace('_', ' '), tot[t], C.SET_COLORS[t]) for t in C.SETS]
    fig, axes = plt.subplots(1, 2, figsize=(12.5, 4.8))
    ax = axes[0]
    ax.pie([p[1] for p in parts], colors=[p[2] for p in parts], startangle=90, counterclock=False,
           wedgeprops={'width': 0.42, 'edgecolor': 'white'},
           labels=[f'{p[0]}{chr(10)}{int(p[1]):,} ({100 * p[1] / tot.sum():.1f}%)' for p in parts], textprops={'fontsize': 9})
    ax.text(0, 0, f'{int(tot.sum()):,}{chr(10)}ảnh', ha='center', va='center', fontsize=12, fontweight='bold')
    ax.set_title('Mỗi client có train + val riêng; test chung (chưa thấy)')
    ax.grid(False)
    ax = axes[1]
    ctr = m.loc[['client1_train', 'client2_train'], C.CLASSES]
    share = ctr.div(ctr.sum(axis=0), axis=1) * 100
    x = np.arange(len(C.CLASSES))
    for off, c in ((-0.2, 'client1_train'), (0.2, 'client2_train')):
        ax.bar(x + off, share.loc[c], 0.4, color=C.SET_COLORS[c], label=c.replace('_train', ''))
        for i, l in enumerate(C.CLASSES):
            ax.text(i + off, share.loc[c, l], f'{share.loc[c, l]:.0f}%{chr(10)}({int(ctr.loc[c, l]):,})', ha='center', va='bottom', fontsize=8)
    ax.set_xticks(x)
    ax.set_xticklabels([C.CLASS_VI[l] for l in C.CLASSES])
    ax.set_ylim(0, 110)
    ax.set_ylabel('% ảnh train của lớp về mỗi client')
    ax.set_title('Phân bố không đồng nhất (non-IID) giữa 2 thiết bị')
    ax.legend(frameon=False)
    save(fig, '02_split_overview.png')


def fig_sources(df):
    t = df.groupby(['tap', 'source']).size().unstack(fill_value=0).reindex(index=C.SETS)
    palette = ['#8A8F98', '#E0602B', '#F2A06B', '#4C9A5F', '#9CCB9F', '#7B68A6']
    fig, ax = plt.subplots(figsize=(10, 4.4))
    left = np.zeros(len(C.SETS))
    for k, col in zip([c for c in C.SOURCE_VI if c in t.columns], palette):
        v = t[k].to_numpy()
        ax.barh(C.SETS, v, left=left, color=col, label=C.SOURCE_VI[k])
        for i, (b, vi) in enumerate(zip(left, v)):
            if vi > t.sum(axis=1).max() * 0.05:
                ax.text(b + vi / 2, i, f'{vi:,}', ha='center', va='center', color='white', fontsize=8, fontweight='bold')
        left += v
    ax.invert_yaxis()
    ax.set_xlabel('Số ảnh')
    ax.set_title('Nguồn gốc ảnh trong từng tập')
    ax.legend(frameon=False, fontsize=8, loc='lower right')
    ax.grid(axis='y', visible=False)
    save(fig, '03_source_by_set.png')


def fig_resolution(ok):
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.4))
    for l in C.CLASSES:
        g = ok[ok.label == l]
        axes[0].scatter(g.width, g.height, s=8, alpha=0.3, color=C.COLORS[l], label=f'{C.CLASS_VI[l]} (n={len(g):,})')
    axes[0].set_xlabel('Chiều rộng (px)')
    axes[0].set_ylabel('Chiều cao (px)')
    axes[0].set_title('Kích thước ảnh')
    axes[0].legend(frameon=False, markerscale=2)
    bins = np.linspace(0, 3, 61)
    for l in C.CLASSES:
        axes[1].hist(np.clip(ok[ok.label == l].aspect, 0, 3), bins=bins, alpha=0.6, color=C.COLORS[l], label=C.CLASS_VI[l])
    axes[1].set_xlabel('Tỷ lệ rộng/cao')
    axes[1].set_ylabel('Số ảnh')
    axes[1].set_title('Tỷ lệ khung hình')
    axes[1].legend(frameon=False)
    save(fig, '04_resolution_aspect.png')


def fig_filesize(ok):
    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    data = [ok[ok.label == l].file_kb for l in C.CLASSES]
    bp = axes[0].boxplot(data, tick_labels=[C.CLASS_VI[l] for l in C.CLASSES], patch_artist=True, showfliers=False)
    for p, l in zip(bp['boxes'], C.CLASSES):
        p.set_facecolor(C.COLORS[l])
        p.set_alpha(0.75)
    axes[0].set_ylabel('Dung lượng (KB)')
    axes[0].set_title('Dung lượng file theo lớp')
    tot = ok.groupby('label').file_kb.sum().reindex(C.CLASSES) / 1024
    axes[1].bar([C.CLASS_VI[l] for l in C.CLASSES], tot, color=[C.COLORS[l] for l in C.CLASSES])
    for i, v in enumerate(tot):
        axes[1].text(i, v, f'{v:,.1f} MB', ha='center', va='bottom')
    axes[1].set_ylabel('Tổng dung lượng (MB)')
    axes[1].set_title('Tổng dung lượng theo lớp')
    save(fig, '05_file_size.png')


def fig_image_stats(ok):
    items = [('brightness', 'Độ sáng (0-255)'), ('contrast', 'Độ tương phản (độ lệch chuẩn xám)'),
             ('saturation', 'Độ bão hòa (0-255)'), ('sharpness', 'Độ nét (log10 phương sai Laplacian)'),
             ('warm_ratio', 'Tỷ lệ điểm ảnh màu nóng (cam/đỏ)'), ('gray_ratio', 'Tỷ lệ điểm ảnh xám sáng (giống khói)')]
    fig, axes = plt.subplots(2, 3, figsize=(13, 7))
    for ax, (k, title) in zip(axes.ravel(), items):
        data = [ok[ok.label == l][k].dropna() for l in C.CLASSES]
        if k == 'sharpness':
            data = [np.log10(d + 1) for d in data]
        parts = ax.violinplot(data, showmedians=True, showextrema=False)
        for b, l in zip(parts['bodies'], C.CLASSES):
            b.set_facecolor(C.COLORS[l])
            b.set_alpha(0.7)
        parts['cmedians'].set_color('#222')
        ax.set_xticks(range(1, 4))
        ax.set_xticklabels([C.CLASS_VI[l] for l in C.CLASSES])
        ax.set_title(title, fontsize=10)
    fig.suptitle('Đặc trưng thị giác đơn giản của từng lớp', fontsize=13, fontweight='bold')
    save(fig, '06_image_statistics.png')


def fig_mean_rgb(ok):
    m = ok.groupby('label')[['mean_r', 'mean_g', 'mean_b']].mean().reindex(C.CLASSES)
    fig, ax = plt.subplots(figsize=(7.5, 4))
    x = np.arange(3)
    w = 0.26
    for i, l in enumerate(C.CLASSES):
        v = m.loc[l].to_numpy()
        ax.bar(x + (i - 1) * w, v, w, color=C.COLORS[l], label=C.CLASS_VI[l])
        for xi, vi in zip(x, v):
            ax.text(xi + (i - 1) * w, vi, f'{vi:.0f}', ha='center', va='bottom', fontsize=8)
    ax.set_xticks(x)
    ax.set_xticklabels(['Đỏ (R)', 'Lục (G)', 'Lam (B)'])
    ax.set_ylabel('Giá trị trung bình (0-255)')
    ax.set_title('Màu trung bình theo lớp')
    ax.legend(frameon=False, ncol=3)
    save(fig, '07_mean_rgb.png')


def fig_set_similarity(ok):
    items = [('brightness', 'Độ sáng'), ('saturation', 'Độ bão hòa'), ('contrast', 'Độ tương phản'), ('warm_ratio', 'Tỷ lệ màu nóng')]
    fig, axes = plt.subplots(1, 4, figsize=(16, 4.2))
    for ax, (k, title) in zip(axes, items):
        data = [ok[ok.tap == t][k].dropna() for t in C.SETS]
        bp = ax.boxplot(data, tick_labels=[t.replace('_', chr(10)) for t in C.SETS], patch_artist=True, showfliers=False)
        for b, t in zip(bp['boxes'], C.SETS):
            b.set_facecolor(C.SET_COLORS[t])
            b.set_alpha(0.8)
        ax.set_title(title, fontsize=10)
    fig.suptitle('Các tập có phân bố đặc trưng tương đương nhau không?', fontsize=13, fontweight='bold')
    save(fig, '08_set_similarity.png')


def fig_samples(df, n=8):
    rng = np.random.default_rng(1)
    fig, axes = plt.subplots(len(C.CLASSES), n, figsize=(n * 2, len(C.CLASSES) * 1.7))
    for r, l in enumerate(C.CLASSES):
        g = df[df.label == l]
        pick = g.iloc[rng.choice(len(g), min(n, len(g)), replace=False)]
        for c in range(n):
            ax = axes[r, c]
            ax.axis('off')
            if c < len(pick):
                ax.imshow(C.open_image(pick.iloc[c].rel))
        axes[r, 0].set_title(C.CLASS_VI[l], loc='left', fontsize=11, color=C.COLORS[l])
    fig.suptitle('Ảnh mẫu từng lớp', fontsize=13, fontweight='bold')
    save(fig, '09_samples.png')


def fig_samples_by_client(df, n=6):
    rng = np.random.default_rng(2)
    fig, axes = plt.subplots(2 * len(C.CLASSES), n, figsize=(n * 1.9, 2 * len(C.CLASSES) * 1.5))
    for ci, c in enumerate(['client1_train', 'client2_train']):
        for r, l in enumerate(C.CLASSES):
            row = ci * len(C.CLASSES) + r
            g = df[(df.tap == c) & (df.label == l)]
            pick = g.iloc[rng.choice(len(g), min(n, len(g)), replace=False)]
            for k in range(n):
                ax = axes[row, k]
                ax.axis('off')
                if k < len(pick):
                    ax.imshow(C.open_image(pick.iloc[k].rel))
            axes[row, 0].set_title(f'{c} - {C.CLASS_VI[l]} ({len(g):,} ảnh)', loc='left', fontsize=10, color=C.COLORS[l])
    save(fig, '10_samples_by_client.png')


def fig_smoke_timeline(df):
    g = df[df.frame >= 0].sort_values('frame')
    fig, ax = plt.subplots(figsize=(12, 3.8))
    for i, t in enumerate(C.SETS):
        s = g[g.tap == t]
        ax.scatter(s.frame, np.full(len(s), i), s=10, color=C.SET_COLORS[t], label=f'{t} ({len(s):,})')
    ax.set_yticks(range(len(C.SETS)))
    ax.set_yticklabels([t.replace('_', ' ') for t in C.SETS])
    ax.set_xlabel('Số thứ tự khung hình (tên file)')
    ax.set_title('Ảnh khói: vị trí khung hình của từng tập (khung liền nhau cùng một tập thì không rò rỉ)')
    ax.legend(frameon=False, ncol=5, loc='upper center', bbox_to_anchor=(0.5, -0.28), fontsize=8)
    ax.grid(axis='y', visible=False)
    save(fig, '11_smoke_frame_split.png')


def fig_leakage(ok, summary):
    chk = summary['kiem_tra_trung_lap']
    near = chk['gan_trung_dhash']
    thrs = sorted(near, key=int)
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.4))
    ax = axes[0]
    x = np.arange(len(thrs))
    w = 0.26
    for i, l in enumerate(C.CLASSES):
        v = [near[t]['giua_cac_tap_theo_nhan'][l] for t in thrs]
        ax.bar(x + (i - 1) * w, v, w, color=C.COLORS[l], label=C.CLASS_VI[l])
        for xi, vi in zip(x, v):
            ax.text(xi + (i - 1) * w, vi, f'{vi:,}', ha='center', va='bottom', fontsize=8)
    ax.set_xticks(x)
    ax.set_xticklabels([f'dHash ≤ {t}' + (' (giống hệt hash)' if t == '0' else '') for t in thrs], fontsize=8)
    ax.set_ylabel('Số cặp ảnh nằm ở 2 tập khác nhau')
    ax.set_title(f'Cặp ảnh gần giống nhau giữa các tập\n(md5 trùng giữa các tập: {chk["md5_trung_giua_cac_tap_so_nhom"]})')
    ax.legend(frameon=False)
    ax = axes[1]
    big = thrs[-1]
    pairs = near[big]['theo_cap_tap']
    ks = sorted(pairs, key=pairs.get, reverse=True)
    ax.barh(ks, [pairs[k] for k in ks], color='#6B8EBB')
    for i, k in enumerate(ks):
        ax.text(pairs[k], i, f' {pairs[k]:,}', va='center', fontsize=8)
    ax.invert_yaxis()
    ax.set_xlabel('Số cặp')
    ax.set_title(f'Theo cặp tập (dHash ≤ {big}); trong cùng tập: {near[big]["trong_cung_tap"]:,} cặp')
    save(fig, '12_leakage_check.png')


def fig_correlation(ok):
    cols = [k for k, _ in FEATURES]
    corr = ok[cols].corr(method='spearman')
    fig, ax = plt.subplots(figsize=(7, 6))
    im = ax.imshow(corr, cmap='RdBu_r', vmin=-1, vmax=1)
    names = [v for _, v in FEATURES]
    ax.set_xticks(range(len(cols)))
    ax.set_xticklabels(names, rotation=45, ha='right')
    ax.set_yticks(range(len(cols)))
    ax.set_yticklabels(names)
    for i in range(len(cols)):
        for j in range(len(cols)):
            ax.text(j, i, f'{corr.iloc[i, j]:.2f}', ha='center', va='center', fontsize=7,
                    color='white' if abs(corr.iloc[i, j]) > 0.6 else '#222')
    ax.grid(False)
    fig.colorbar(im, ax=ax, shrink=0.8)
    ax.set_title('Tương quan Spearman giữa các đặc trưng')
    save(fig, '13_feature_correlation.png')


def write_facts(df, ok, m, summary):
    L = ['# Số liệu tóm tắt để viết báo cáo dữ liệu', '', 'Tạo tự động bởi 02_visualize.py từ analysis/.', '']
    L += ['## 1. Tổng quan', '',
          f'- Thư mục dữ liệu: `{summary["thu_muc_du_lieu"]}`',
          f'- Tổng ảnh: {summary["tong_anh"]:,}; đọc được: {summary["doc_duoc"]:,}; hỏng: {summary["hong"]:,}; dung lượng: {summary["dung_luong_mb"]:,.0f} MB',
          f'- Định dạng: {summary["dinh_dang"]}; chế độ màu: {summary["che_do_mau"]}',
          f'- Kích thước rộng: trung vị {summary["kich_thuoc"]["rong"]["50%"]:.0f}, nhỏ nhất {summary["kich_thuoc"]["rong"]["min"]:.0f}, lớn nhất {summary["kich_thuoc"]["rong"]["max"]:.0f} px',
          f'- Kích thước cao: trung vị {summary["kich_thuoc"]["cao"]["50%"]:.0f}, nhỏ nhất {summary["kich_thuoc"]["cao"]["min"]:.0f}, lớn nhất {summary["kich_thuoc"]["cao"]["max"]:.0f} px', '']
    L += ['## 2. Chia tập (mỗi client có train + val riêng; test chung dùng sau tổng hợp)', '', '| Tập | Bình thường | Khói | Lửa | Tổng | % tổng |', '|---|---|---|---|---|---|']
    tot = m.tong.sum()
    for t in C.SETS:
        r = m.loc[t]
        L.append(f'| {t} | {r.binh_thuong:,} | {r.khoi:,} | {r.lua:,} | {r.tong:,} | {100 * r.tong / tot:.1f}% |')
    L.append(f'| **Cộng** | {m.binh_thuong.sum():,} | {m.khoi.sum():,} | {m.lua.sum():,} | {tot:,} | 100% |')
    L += ['', '### Gộp train / val / test', '', '| Tập | Bình thường | Khói | Lửa | Tổng | % tổng |', '|---|---|---|---|---|---|']
    for k, r in summary['train_val_test'].items():
        L.append(f'| {k} | {r["binh_thuong"]:,} | {r["khoi"]:,} | {r["lua"]:,} | {r["tong"]:,} | {r["ti_le_pct"]:.1f}% |')
    L += ['', '### Mức độ non-IID giữa 2 client (train)', '', '| Lớp | client1 train | client2 train | % về client1 |', '|---|---|---|---|']
    for l in C.CLASSES:
        a, b = m.loc['client1_train', l], m.loc['client2_train', l]
        L.append(f'| {C.CLASS_VI[l]} | {a:,} | {b:,} | {100 * a / (a + b):.1f}% |')
    L += ['', '### Nguồn ảnh theo tập', '']
    src = df.groupby(['tap', 'source']).size().unstack(fill_value=0).reindex(index=C.SETS)
    cols = [c for c in C.SOURCE_VI if c in src.columns]
    L += ['| Tập | ' + ' | '.join(C.SOURCE_VI[c] for c in cols) + ' |', '|---|' + '---|' * len(cols)]
    for t in C.SETS:
        L.append(f'| {t} | ' + ' | '.join(f'{src.loc[t, c]:,}' for c in cols) + ' |')
    chk = summary['kiem_tra_trung_lap']
    near = chk['gan_trung_dhash']
    L += ['', '## 3. Kiểm tra trùng lặp và rò rỉ', '',
          f'- Nhóm ảnh trùng md5 (bất kỳ tập nào): {chk["md5_trung_trong_cung_tap_hoac_khac_tap_so_nhom"]:,}',
          f'- Nhóm ảnh trùng md5 nằm ở NHIỀU tập khác nhau: {chk["md5_trung_giua_cac_tap_so_nhom"]:,}',
          '- dHash (hash 64 bit theo độ dốc sáng); khoảng cách Hamming càng nhỏ càng giống. Ảnh khói chụp từ camera cố định nên khung hình khác nhau vẫn có hash gần nhau (cùng khung cảnh), không hẳn là ảnh trùng.', '',
          '| Ngưỡng dHash | Cặp cùng tập | Cặp khác tập | Khác tập: bình thường | khói | lửa |', '|---|---|---|---|---|---|']
    for t in sorted(near, key=int):
        r = near[t]
        b = r['giua_cac_tap_theo_nhan']
        L.append(f'| ≤ {t} | {r["trong_cung_tap"]:,} | {r["giua_cac_tap"]:,} | {b["binh_thuong"]:,} | {b["khoi"]:,} | {b["lua"]:,} |')
    L.append('')
    L += ['## 4. Đặc trưng thị giác trung bình', '', '### Theo lớp', '',
          '| Lớp | Rộng | Cao | Sáng | Tương phản | Bão hòa | Độ nét | Màu nóng | Xám sáng |', '|---|---|---|---|---|---|---|---|---|']
    cols = ['width', 'height', 'brightness', 'contrast', 'saturation', 'sharpness', 'warm_ratio', 'gray_ratio']
    for l, r in ok.groupby('label')[cols].mean().reindex(C.CLASSES).iterrows():
        L.append(f'| {C.CLASS_VI[l]} | {r.width:.0f} | {r.height:.0f} | {r.brightness:.1f} | {r.contrast:.1f} | {r.saturation:.1f} | {r.sharpness:.0f} | {r.warm_ratio:.3f} | {r.gray_ratio:.3f} |')
    L += ['', '### Theo tập', '',
          '| Tập | Rộng | Cao | Sáng | Tương phản | Bão hòa | Độ nét | Màu nóng | Xám sáng |', '|---|---|---|---|---|---|---|---|---|']
    for t, r in ok.groupby('tap')[cols].mean().reindex(C.SETS).iterrows():
        L.append(f'| {t} | {r.width:.0f} | {r.height:.0f} | {r.brightness:.1f} | {r.contrast:.1f} | {r.saturation:.1f} | {r.sharpness:.0f} | {r.warm_ratio:.3f} | {r.gray_ratio:.3f} |')
    L += ['', '## 5. Danh sách hình', '']
    for f in sorted(p.name for p in C.FIG.glob('*.png')):
        L.append(f'- figures/{f}')
    (C.OUT / 'bao_cao_so_lieu.md').write_text('\n'.join(L) + '\n', encoding='utf-8')
    print('[visual] bao_cao_so_lieu.md', flush=True)


def main():
    C.ensure_dirs()
    df = pd.read_csv(C.ANALYSIS / 'files.csv')
    m = pd.read_csv(C.ANALYSIS / 'split_matrix.csv').set_index('tap')
    with open(C.ANALYSIS / 'summary.json', encoding='utf-8') as f:
        summary = json.load(f)
    ok = df[df.readable]

    fig_split_counts(m)
    fig_split_overview(m)
    fig_sources(df)
    fig_resolution(ok)
    fig_filesize(ok)
    fig_image_stats(ok)
    fig_mean_rgb(ok)
    fig_set_similarity(ok)
    fig_samples(df)
    fig_samples_by_client(df)
    fig_smoke_timeline(df)
    fig_leakage(ok, summary)
    fig_correlation(ok)
    write_facts(df, ok, m, summary)
    print(f'[visual] xong -> {C.OUT}', flush=True)


if __name__ == '__main__':
    main()
