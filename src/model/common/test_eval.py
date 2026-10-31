import csv
import json

import numpy as np
import torch

from . import data
from . import define_model as dm
from . import finetune as ft
from .evaluate import predict_logits, compute_metrics
from .paths import client_paths, load_config, shared_dir
from .train import print_report


def load_head(client, cfg):
    net, _ = ft.prepare_model(cfg, pretrained=False)
    cut = ft.feature_cut(cfg['model']['trainable'])
    _, head = dm.split_model(net, cut)
    path = client_paths(client, cfg)['out'] / 'run' / 'final_head.pt'
    if not path.exists():
        raise FileNotFoundError(f'chưa có {path}, chạy train.py của {client} trước')
    head.load_state_dict(torch.load(path, map_location='cpu'))
    head.eval()
    return head


def load_test(cfg):
    cut = ft.feature_cut(cfg['model']['trainable'])
    path = data.cache_file(shared_dir(cfg), 'test', cut, cfg)
    if not path.exists():
        raise FileNotFoundError(f'chưa có cache test {path}, chạy extract_features.py trước')
    z = np.load(path)
    return z['X'], z['y'], z['files']


def plot_confusion(cm, classes, path, title):
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
    except Exception:
        return
    cm = np.asarray(cm)
    norm = cm / np.maximum(cm.sum(axis=1, keepdims=True), 1)
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.2))
    for ax, mat, fmt, sub in ((axes[0], cm, '{:d}', 'Số ảnh'), (axes[1], norm, '{:.1%}', 'Tỷ lệ theo hàng (recall)')):
        im = ax.imshow(mat, cmap='Blues')
        ax.set_xticks(range(len(classes)))
        ax.set_xticklabels(classes, rotation=20)
        ax.set_yticks(range(len(classes)))
        ax.set_yticklabels(classes)
        ax.set_xlabel('Dự đoán')
        ax.set_ylabel('Thực tế')
        ax.set_title(sub)
        ax.grid(False)
        top = mat.max() if mat.max() else 1
        for i in range(len(classes)):
            for j in range(len(classes)):
                v = mat[i, j]
                ax.text(j, i, fmt.format(int(v) if fmt == '{:d}' else v), ha='center', va='center',
                        color='white' if v > top * 0.55 else '#222')
        fig.colorbar(im, ax=ax, shrink=0.8)
    fig.suptitle(title, fontweight='bold')
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)


def run(client, cfg=None, verbose=True):
    cfg = cfg or load_config()
    classes = cfg['classes']
    torch.set_num_threads(int(cfg['threads']))
    head = load_head(client, cfg)
    X, y, files = load_test(cfg)
    logits = predict_logits(head, X)
    probs = torch.softmax(logits, dim=1).numpy()
    pred = probs.argmax(axis=1)
    m = compute_metrics(logits, y, classes)

    out = client_paths(client, cfg)['out'] / 'test'
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for f, t, p, pr in zip(files, y, pred, probs):
        row = {'file': str(f), 'true': classes[int(t)], 'pred': classes[int(p)], 'correct': int(t == p)}
        row.update({f'p_{c}': float(v) for c, v in zip(classes, pr)})
        rows.append(row)
    with open(out / 'predictions.csv', 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    errors = [r for r in rows if not r['correct']]
    with open(out / 'errors.csv', 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(errors)

    val_path = client_paths(client, cfg)['out'] / 'run' / 'metrics.json'
    val = None
    if val_path.exists():
        with open(val_path, encoding='utf-8') as f:
            val = json.load(f)['val_metrics']
    summary = {'client': client, 'n_test': int(len(y)), 'n_errors': len(errors), 'test_metrics': m,
               'val_accuracy': val['accuracy'] if val else None, 'val_macro_f1': val['macro_f1'] if val else None}
    with open(out / 'metrics.json', 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)
    plot_confusion(m['confusion_matrix'], classes, out / 'confusion_matrix.png', f'{client}: mô hình cục bộ trên test')

    if verbose:
        print_report(f'[{client}] TEST ({len(y)} ảnh, chưa thấy)', m, classes)
        if val:
            print(f'[{client}] so với val: accuracy {val["accuracy"]:.4f} -> test {m["accuracy"]:.4f}; '
                  f'macro-F1 {val["macro_f1"]:.4f} -> test {m["macro_f1"]:.4f}')
        cm = np.asarray(m['confusion_matrix'])
        print(f'[{client}] ma trận nhầm lẫn (hàng = thực tế, cột = dự đoán, thứ tự {classes}):')
        for name, row in zip(classes, cm):
            print(f'    {name:<12} {row.tolist()}')
        print(f'[{client}] sai {len(errors)}/{len(y)} ảnh; đã lưu vào {out}')
    return summary
