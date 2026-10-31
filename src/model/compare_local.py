import csv
import json

import numpy as np

from common.paths import ROOT, client_paths, load_config

CLIENTS = ['client1', 'client2']


def main():
    cfg = load_config()
    classes = cfg['classes']
    res = {}
    for c in CLIENTS:
        p = client_paths(c, cfg)['out'] / 'test' / 'metrics.json'
        if not p.exists():
            raise SystemExit(f'chưa có {p}, chạy {c}/evaluate_test.py trước')
        with open(p, encoding='utf-8') as f:
            res[c] = json.load(f)

    header = ['chi_so'] + CLIENTS
    rows = [
        ['accuracy_val'] + [res[c]['val_accuracy'] for c in CLIENTS],
        ['accuracy_test'] + [res[c]['test_metrics']['accuracy'] for c in CLIENTS],
        ['macro_f1_val'] + [res[c]['val_macro_f1'] for c in CLIENTS],
        ['macro_f1_test'] + [res[c]['test_metrics']['macro_f1'] for c in CLIENTS],
        ['loss_test'] + [res[c]['test_metrics']['loss'] for c in CLIENTS],
        ['so_anh_sai'] + [res[c]['n_errors'] for c in CLIENTS],
    ]
    for k in classes:
        for metric in ('precision', 'recall', 'f1'):
            rows.append([f'{metric}_{k}'] + [res[c]['test_metrics']['per_class'][k][metric] for c in CLIENTS])

    out = ROOT / cfg['output_root'] / 'shared'
    out.mkdir(parents=True, exist_ok=True)
    with open(out / 'local_models_on_test.csv', 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)

    print(f'{"chỉ số":<24}' + ''.join(f'{c:>12}' for c in CLIENTS))
    for r in rows:
        vals = ''.join(f'{v:>12.4f}' if isinstance(v, float) else f'{v:>12}' for v in r[1:])
        print(f'{r[0]:<24}{vals}')

    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
    except Exception:
        return
    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    x = np.arange(len(classes))
    colors = {'client1': '#3B6FB6', 'client2': '#C0504D'}
    for ax, metric, title in ((axes[0], 'recall', 'Recall từng lớp trên test'), (axes[1], 'f1', 'F1 từng lớp trên test')):
        for i, c in enumerate(CLIENTS):
            v = [res[c]['test_metrics']['per_class'][k][metric] for k in classes]
            ax.bar(x + (i - 0.5) * 0.38, v, 0.38, color=colors[c], label=c)
            for xi, vi in zip(x + (i - 0.5) * 0.38, v):
                ax.text(xi, vi, f'{vi:.2f}', ha='center', va='bottom', fontsize=8)
        ax.set_xticks(x)
        ax.set_xticklabels(classes)
        ax.set_ylim(0.88, 1.03)
        ax.set_title(title)
        ax.grid(axis='x', visible=False)
        ax.legend(frameon=False, ncol=2, loc='upper center', bbox_to_anchor=(0.5, -0.1))
    fig.tight_layout()
    fig.savefig(out / 'local_models_on_test.png', dpi=140)
    plt.close(fig)
    print(f'đã lưu vào {out}')


if __name__ == '__main__':
    main()
