from common import pi4_guard                                                        # noqa: F401  bắt buộc: tự đưa tiến trình vào giả lập Pi 4

import copy
import csv
import json
import time

import numpy as np
import torch
import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt

from common import data, fedavg, finetune as ft, test_eval, train
from common.paths import ROOT, client_paths, load_config

CLIENTS = ['client1', 'client2']
MODEL_NAMES = {'client1': 'client1 cục bộ', 'client2': 'client2 cục bộ', 'oneshot': 'Trung bình 1 lần', 'fedavg': 'FedAvg'}
MODE_COLORS = {'classifier': '#3B6FB6', 'fire9_classifier': '#E0602B'}
MODE_VI = {'classifier': 'Chỉ lớp cuối (1.539 tham số)', 'fire9_classifier': 'fire9 + lớp cuối (198.723 tham số)'}


def run_config(base, exp, mode, seed):
    cfg = copy.deepcopy(base)
    cfg['seed'] = int(seed)
    cfg['model']['trainable'] = mode
    cfg['train']['epochs'] = int(exp['local_epochs'])
    cfg['fl']['rounds'] = int(exp['rounds'])
    cfg['fl']['run_name'] = 'fedavg'
    cfg['feature_root'] = base['output_root']
    cfg['output_root'] = f'{base["output_root"]}/experiments/{exp["name"]}/{mode}/seed{seed}'
    return cfg


def slim(m, classes):
    r = {'accuracy': m['accuracy'], 'macro_f1': m['macro_f1'], 'loss': m['loss'],
         'errors': int(round((1 - m['accuracy']) * sum(sum(row) for row in m['confusion_matrix'])))}
    r.update({f'recall_{k}': m['per_class'][k]['recall'] for k in classes})
    return r


def read_json(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def one_run(base, exp, mode, seed, result_path):
    cfg = run_config(base, exp, mode, seed)
    classes = cfg['classes']
    torch.manual_seed(int(seed))
    t0 = time.time()
    for client in CLIENTS:
        train.run(client, cfg=cfg, verbose=False)
        test_eval.run(client, cfg=cfg, verbose=False)
    fed = fedavg.run(cfg=cfg, verbose=False)
    models = {c: read_json(client_paths(c, cfg)['out'] / 'test' / 'metrics.json')['test_metrics'] for c in CLIENTS}
    models['oneshot'] = fed['oneshot_average_test_metrics']
    models['fedavg'] = fed['test_metrics']
    result = {'mode': mode, 'seed': int(seed), 'seconds': time.time() - t0,
              'models': {k: slim(v, classes) for k, v in models.items()}}
    result_path.parent.mkdir(parents=True, exist_ok=True)
    with open(result_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    return result


def aggregate(results, modes, classes):
    keys = ['accuracy', 'macro_f1', 'loss', 'errors'] + [f'recall_{k}' for k in classes]
    rows = []
    for mode in modes:
        rs = [r for r in results if r['mode'] == mode]
        for model in MODEL_NAMES:
            row = {'mode': mode, 'model': model, 'n_seeds': len(rs)}
            for k in keys:
                v = np.array([r['models'][model][k] for r in rs], float)
                row[f'{k}_mean'] = float(v.mean())
                row[f'{k}_std'] = float(v.std(ddof=1)) if len(v) > 1 else 0.0
            rows.append(row)
    return rows


def write_tables(out, results, summary, classes):
    with open(out / 'results.csv', 'w', newline='', encoding='utf-8-sig') as f:
        keys = ['accuracy', 'macro_f1', 'loss', 'errors'] + [f'recall_{k}' for k in classes]
        w = csv.writer(f)
        w.writerow(['mode', 'seed', 'model'] + keys)
        for r in results:
            for model in MODEL_NAMES:
                w.writerow([r['mode'], r['seed'], model] + [r['models'][model][k] for k in keys])
    with open(out / 'summary.csv', 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=list(summary[0].keys()))
        w.writeheader()
        w.writerows(summary)
    lines = ['| Chế độ | Mô hình | Accuracy (%) | Macro-F1 | Recall bình thường | Recall khói | Recall lửa | Ảnh sai |',
             '|---|---|---|---|---|---|---|---|']
    for row in summary:
        lines.append(
            f'| {row["mode"]} | {MODEL_NAMES[row["model"]]} | {100 * row["accuracy_mean"]:.2f} ± {100 * row["accuracy_std"]:.2f} | '
            f'{row["macro_f1_mean"]:.3f} ± {row["macro_f1_std"]:.3f} | '
            f'{row["recall_binh_thuong_mean"]:.3f} ± {row["recall_binh_thuong_std"]:.3f} | '
            f'{row["recall_khoi_mean"]:.3f} ± {row["recall_khoi_std"]:.3f} | '
            f'{row["recall_lua_mean"]:.3f} ± {row["recall_lua_std"]:.3f} | '
            f'{row["errors_mean"]:.1f} ± {row["errors_std"]:.1f} |')
    (out / 'summary.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return '\n'.join(lines)


def plot(out, results, summary, modes, classes):
    fig, axes = plt.subplots(1, 2, figsize=(14, 4.8), gridspec_kw={'width_ratios': [1.1, 1]})
    ax = axes[0]
    names = list(MODEL_NAMES)
    w = 0.8 / len(modes)
    x = np.arange(len(names))
    for i, mode in enumerate(modes):
        off = (i - (len(modes) - 1) / 2) * w
        rows = {r['model']: r for r in summary if r['mode'] == mode}
        mean = [100 * rows[n]['accuracy_mean'] for n in names]
        std = [100 * rows[n]['accuracy_std'] for n in names]
        ax.bar(x + off, mean, w, yerr=std, capsize=4, color=MODE_COLORS.get(mode, '#888'), alpha=0.85, label=MODE_VI.get(mode, mode))
        for j, n in enumerate(names):
            pts = [100 * r['models'][n]['accuracy'] for r in results if r['mode'] == mode]
            ax.scatter(np.full(len(pts), x[j] + off), pts, s=10, color='#222', zorder=3)
            ax.text(x[j] + off, mean[j] + std[j] + 0.08, f'{mean[j]:.2f}', ha='center', va='bottom', fontsize=8)
    ax.set_xticks(x)
    ax.set_xticklabels([MODEL_NAMES[n].replace(' ', '\n', 1) for n in names])
    allv = [100 * r['models'][n]['accuracy'] for r in results for n in names]
    ax.set_ylim(min(allv) - 1.5, max(allv) + 1.5)
    ax.set_ylabel('Accuracy trên test (%)')
    ax.set_title('Accuracy (trung bình ± độ lệch chuẩn, chấm = từng seed)')
    ax.legend(frameon=False, loc='upper center', bbox_to_anchor=(0.5, -0.14), ncol=2, fontsize=9)
    ax.grid(axis='x', visible=False)
    ax = axes[1]
    x2 = np.arange(len(classes))
    for i, mode in enumerate(modes):
        off = (i - (len(modes) - 1) / 2) * w
        row = [r for r in summary if r['mode'] == mode and r['model'] == 'fedavg'][0]
        mean = [row[f'recall_{k}_mean'] for k in classes]
        std = [row[f'recall_{k}_std'] for k in classes]
        ax.bar(x2 + off, mean, w, yerr=std, capsize=4, color=MODE_COLORS.get(mode, '#888'), alpha=0.85)
        for xi, m in zip(x2 + off, mean):
            ax.text(xi, m + 0.004, f'{m:.3f}', ha='center', va='bottom', fontsize=8)
    ax.set_xticks(x2)
    ax.set_xticklabels(['Bình thường', 'Khói', 'Lửa'])
    ax.set_ylim(0.9, 1.03)
    ax.set_ylabel('Recall trên test')
    ax.set_title('Recall từng lớp của FedAvg theo chế độ')
    ax.grid(axis='x', visible=False)
    fig.tight_layout()
    fig.savefig(out / 'comparison.png', dpi=150, bbox_inches='tight')
    plt.close(fig)


def main():
    base = load_config()
    exp = base['experiments']
    modes = list(exp['trainable'])
    seeds = list(exp['seeds'])
    classes = base['classes']
    torch.set_num_threads(int(base['threads']))
    out = ROOT / base['output_root'] / 'experiments' / exp['name']
    out.mkdir(parents=True, exist_ok=True)
    total = len(modes) * len(seeds)
    results, done = [], 0
    t_all = time.time()
    for mode in modes:
        cfg_mode = run_config(base, exp, mode, seeds[0])
        net, _ = ft.prepare_model(cfg_mode)
        for client in CLIENTS:
            data.extract_client(client, net, cfg_mode)
        for seed in seeds:
            done += 1
            path = out / mode / f'seed{seed}' / 'result.json'
            if path.exists():
                results.append(read_json(path))
                print(f'[{done}/{total}] {mode} seed {seed}: đã có kết quả, bỏ qua', flush=True)
                continue
            r = one_run(base, exp, mode, seed, path)
            results.append(r)
            m = r['models']
            print(f'[{done}/{total}] {mode} seed {seed}: client1 {100 * m["client1"]["accuracy"]:.2f}%  '
                  f'client2 {100 * m["client2"]["accuracy"]:.2f}%  trung bình {100 * m["oneshot"]["accuracy"]:.2f}%  '
                  f'FedAvg {100 * m["fedavg"]["accuracy"]:.2f}%  ({r["seconds"]:.0f}s, đã chạy {time.time() - t_all:.0f}s)', flush=True)
    summary = aggregate(results, modes, classes)
    table = write_tables(out, results, summary, classes)
    plot(out, results, summary, modes, classes)
    print('\n' + table)
    print(f'\nđã lưu vào {out}')


if __name__ == '__main__':
    main()
