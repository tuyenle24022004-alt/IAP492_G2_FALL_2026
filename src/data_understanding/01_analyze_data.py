import json
import argparse
from multiprocessing import Pool

import numpy as np
import pandas as pd

import common as C


def near_duplicates(df, thresholds):
    res = {t: {'nguong_hamming': t, 'trong_cung_tap': 0, 'giua_cac_tap': 0,
               'giua_cac_tap_theo_nhan': {l: 0 for l in C.CLASSES}, 'trong_cung_tap_theo_nhan': {l: 0 for l in C.CLASSES},
               'theo_cap_tap': {}} for t in thresholds}
    for label, g in df.groupby('label'):
        h = C.hashes_to_array(g.dhash.tolist())
        tap = g.tap.to_numpy()
        for i in range(0, len(h), 1024):
            d = C.hamming_matrix(h[i:i + 1024], h)
            for t in thresholds:
                rows, cols = np.nonzero(d <= t)
                rows = rows + i
                keep = rows < cols
                for a, b in zip(tap[rows[keep]], tap[cols[keep]]):
                    r = res[t]
                    if a == b:
                        r['trong_cung_tap'] += 1
                        r['trong_cung_tap_theo_nhan'][label] += 1
                    else:
                        r['giua_cac_tap'] += 1
                        r['giua_cac_tap_theo_nhan'][label] += 1
                        k = ' - '.join(sorted((a, b)))
                        r['theo_cap_tap'][k] = r['theo_cap_tap'].get(k, 0) + 1
    return {str(t): v for t, v in res.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--workers', type=int, default=8)
    ap.add_argument('--near-thr', type=int, default=4)
    args = ap.parse_args()
    C.ensure_dirs()

    meta = pd.DataFrame(C.list_files())
    if meta.empty:
        raise SystemExit(f'không thấy ảnh trong {C.DATA}')
    print(f'[analyze] {len(meta)} ảnh trong {C.DATA}', flush=True)
    with Pool(args.workers) as pool:
        feats = []
        for i, r in enumerate(pool.imap(C.image_features, meta.rel.tolist(), chunksize=32), 1):
            feats.append(r)
            if i % 2000 == 0:
                print(f'[analyze] {i}/{len(meta)}', flush=True)
    df = meta.merge(pd.DataFrame(feats), on='rel', how='left')
    df.to_csv(C.ANALYSIS / 'files.csv', index=False, encoding='utf-8-sig')
    ok = df[df.readable]

    matrix = df.groupby(['tap', 'label']).size().unstack(fill_value=0).reindex(index=C.SETS, columns=C.CLASSES, fill_value=0)
    matrix['tong'] = matrix.sum(axis=1)
    matrix.reset_index().to_csv(C.ANALYSIS / 'split_matrix.csv', index=False, encoding='utf-8-sig')

    long_rows = []
    for t in C.SETS:
        for l in C.CLASSES:
            long_rows.append({
                'tap': t, 'label': l, 'so_anh': int(matrix.loc[t, l]),
                'ti_le_trong_tap_pct': 100 * matrix.loc[t, l] / matrix.loc[t, 'tong'],
                'ti_le_trong_lop_pct': 100 * matrix.loc[t, l] / matrix[l].sum(),
            })
    pd.DataFrame(long_rows).to_csv(C.ANALYSIS / 'split_counts.csv', index=False, encoding='utf-8-sig')

    grouped = df.assign(nhom=df.tap.map(lambda t: 'train' if t.endswith('_train') else ('val' if t.endswith('_val') else 'test')))
    g3 = grouped.groupby(['nhom', 'label']).size().unstack(fill_value=0).reindex(index=['train', 'val', 'test'], columns=C.CLASSES, fill_value=0)
    g3['tong'] = g3.sum(axis=1)
    g3['ti_le_pct'] = 100 * g3.tong / g3.tong.sum()
    g3.reset_index().to_csv(C.ANALYSIS / 'split_train_val_test.csv', index=False, encoding='utf-8-sig')

    src = df.groupby(['tap', 'source']).size().unstack(fill_value=0).reindex(index=C.SETS)
    src.reset_index().to_csv(C.ANALYSIS / 'source_by_set.csv', index=False, encoding='utf-8-sig')

    num_cols = ['width', 'height', 'file_kb', 'brightness', 'contrast', 'saturation', 'sharpness', 'warm_ratio', 'gray_ratio']
    ok.groupby('label')[num_cols].describe(percentiles=[0.25, 0.5, 0.75]).T.to_csv(C.ANALYSIS / 'feature_stats_by_label.csv', encoding='utf-8-sig')
    ok.groupby('tap')[num_cols].describe(percentiles=[0.25, 0.5, 0.75]).T.to_csv(C.ANALYSIS / 'feature_stats_by_set.csv', encoding='utf-8-sig')

    md5_sets = ok.groupby('md5').tap.nunique()
    md5_count = ok.groupby('md5').size()
    near = near_duplicates(ok, sorted({0, 2, args.near_thr}))

    summary = {
        'thu_muc_du_lieu': str(C.DATA),
        'tong_anh': int(len(df)),
        'doc_duoc': int(df.readable.sum()),
        'hong': int((~df.readable).sum()),
        'dung_luong_mb': float(df.file_kb.sum() / 1024),
        'dinh_dang': ok.format.value_counts().to_dict(),
        'che_do_mau': ok['mode'].value_counts().to_dict(),
        'kich_thuoc': {
            'rong': {k: float(v) for k, v in ok.width.describe().items()},
            'cao': {k: float(v) for k, v in ok.height.describe().items()},
        },
        'ma_tran_tap_x_lop': matrix.to_dict(orient='index'),
        'train_val_test': g3.to_dict(orient='index'),
        'ti_le_tap_pct': {t: float(100 * matrix.loc[t, 'tong'] / matrix.tong.sum()) for t in C.SETS},
        'kiem_tra_trung_lap': {
            'md5_trung_trong_cung_tap_hoac_khac_tap_so_nhom': int((md5_count > 1).sum()),
            'md5_trung_giua_cac_tap_so_nhom': int((md5_sets > 1).sum()),
            'gan_trung_dhash': near,
            'nguong_lon_nhat': str(max(int(k) for k in near)),
        },
        'khung_hinh_khoi_theo_tap': {
            t: {'so_anh': int(((df.tap == t) & (df.frame >= 0)).sum())} for t in C.SETS
        },
    }
    with open(C.ANALYSIS / 'summary.json', 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)
    print(matrix.to_string())
    print(json.dumps(summary['kiem_tra_trung_lap'], ensure_ascii=False))
    print(f'[analyze] xong -> {C.ANALYSIS}', flush=True)


if __name__ == '__main__':
    main()
