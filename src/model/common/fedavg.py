import csv
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # chạy trực tiếp file này vẫn import được gói common

import numpy as np
import torch

from common import data
from common import define_model as dm
from common import finetune as ft
from common.evaluate import evaluate
from common.paths import ROOT, client_paths, load_config
from common.train import make_optimizer, train_one_epoch, print_report

CLIENTS = ['client1', 'client2']


def trainable_params(head):
    return [p for p in head.parameters() if p.requires_grad]


def get_vec(head):
    return torch.cat([p.detach().flatten() for p in trainable_params(head)]).numpy().astype(np.float64)


def set_vec(head, vec):
    i = 0
    with torch.no_grad():
        for p in trainable_params(head):
            n = p.numel()
            p.copy_(torch.from_numpy(np.ascontiguousarray(vec[i:i + n])).view_as(p).float())
            i += n


def weighted_average(vecs, sizes):
    w = np.asarray(sizes, np.float64)
    w = w / w.sum()
    return sum(wi * v for wi, v in zip(w, vecs))


def local_update(head, vec, X, y, cfg, epochs, seed):
    set_vec(head, vec)
    opt = make_optimizer(trainable_params(head), cfg)
    loss = acc = 0.0
    for e in range(epochs):
        rng = np.random.default_rng(seed + e)
        loss, acc = train_one_epoch(head, X, y, opt, int(cfg['train']['batch']), rng)
    return get_vec(head), loss, acc


def local_test_metrics(cfg):
    out = {}
    for c in CLIENTS:
        p = client_paths(c, cfg)['out'] / 'test' / 'metrics.json'
        if p.exists():
            with open(p, encoding='utf-8') as f:
                out[c] = json.load(f)['test_metrics']
    return out


def plot_rounds(history, local, path):
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
    except Exception:
        return
    r = [h['round'] for h in history]
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.2))
    axes[0].plot(r, [h['test_acc'] for h in history], marker='o', label='FedAvg (toàn cục)', color='#2A9D5C')
    colors = {'client1': '#3B6FB6', 'client2': '#C0504D'}
    for c, m in local.items():
        axes[0].axhline(m['accuracy'], linestyle='--', color=colors[c], label=f'{c} cục bộ')
    axes[0].set_xlabel('Vòng')
    axes[0].set_ylabel('Accuracy trên test')
    axes[0].set_title('Accuracy test theo vòng')
    axes[0].legend(frameon=False)
    for k, col in zip(['binh_thuong', 'khoi', 'lua'], ['#4C9A5F', '#8A8F98', '#E0602B']):
        axes[1].plot(r, [h[f'recall_{k}'] for h in history], marker='o', label=k, color=col)
    axes[1].set_xlabel('Vòng')
    axes[1].set_ylabel('Recall trên test')
    axes[1].set_title('Recall từng lớp theo vòng (FedAvg)')
    axes[1].legend(frameon=False)
    for ax in axes:
        ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)


def run(cfg=None, verbose=True):
    cfg = cfg or load_config()
    fl = cfg['fl']
    rounds = int(fl['rounds'])
    local_epochs = int(fl['local_epochs'])
    seed = int(cfg['seed'])
    classes = cfg['classes']
    torch.manual_seed(seed)
    torch.set_num_threads(int(cfg['threads']))

    feats = {c: data.load_client_features(c, cfg, splits=('train', 'val')) for c in CLIENTS}
    Xte, yte = data.load_client_features(CLIENTS[0], cfg, splits=('test',))['test']
    sizes = [len(feats[c]['train'][1]) for c in CLIENTS]

    net, source = ft.prepare_model(cfg)
    _, head = dm.split_model(net, ft.feature_cut(cfg['model']['trainable']))
    g = get_vec(head)
    n_params = g.size
    log = print if verbose else (lambda *a, **k: None)
    log(f'[fedavg] {len(CLIENTS)} client, n_k = {sizes}, trọng số n_k/n = '
          f'{[round(s / sum(sizes), 4) for s in sizes]}; {rounds} vòng × {local_epochs} epoch cục bộ; '
          f'{n_params:,} tham số/vòng ({n_params * 4 / 1024:.1f} KB mỗi chiều mỗi client)', flush=True)

    out = ROOT / cfg['output_root'] / str(fl.get('run_name', 'fedavg'))
    out.mkdir(parents=True, exist_ok=True)

    oneshot = None
    paths = [client_paths(c, cfg)['out'] / 'run' / 'weights.npy' for c in CLIENTS]
    if all(p.exists() for p in paths):
        v = weighted_average([np.load(p).astype(np.float64) for p in paths], sizes)
        set_vec(head, v)
        oneshot = evaluate(head, Xte, yte, classes)
        log(f'[fedavg] mốc tham khảo: lấy trung bình trọng số hai mô hình cục bộ đã huấn luyện (1 lần): '
              f'test acc {oneshot["accuracy"]:.4f}  macro-F1 {oneshot["macro_f1"]:.4f}', flush=True)

    set_vec(head, g)
    base = evaluate(head, Xte, yte, classes)
    log(f'[fedavg] vòng 0 (chưa huấn luyện): test acc {base["accuracy"]:.4f}', flush=True)

    history = []
    t0 = time.time()
    for r in range(1, rounds + 1):
        vecs, tr = [], []
        for ci, c in enumerate(CLIENTS):
            X, y = feats[c]['train']
            v, loss, acc = local_update(head, g, X, y, cfg, local_epochs, seed * 1000 + r * 10 + ci)
            vecs.append(v)
            tr.append((loss, acc))
        g = weighted_average(vecs, sizes)
        set_vec(head, g)
        vals = [evaluate(head, *feats[c]['val'], classes) for c in CLIENTS]
        test = evaluate(head, Xte, yte, classes)
        row = {'round': r, 'train_loss_c1': tr[0][0], 'train_loss_c2': tr[1][0],
               'val_acc_c1': vals[0]['accuracy'], 'val_acc_c2': vals[1]['accuracy'],
               'test_loss': test['loss'], 'test_acc': test['accuracy'], 'test_macro_f1': test['macro_f1']}
        row.update({f'recall_{k}': test['per_class'][k]['recall'] for k in classes})
        history.append(row)
        log(f'[fedavg] vòng {r:2d}  val {vals[0]["accuracy"]:.3f}/{vals[1]["accuracy"]:.3f}  '
              f'test acc {test["accuracy"]:.4f}  F1 {test["macro_f1"]:.4f}  '
              f'recall ' + ' '.join(f'{k[:4]} {test["per_class"][k]["recall"]:.3f}' for k in classes), flush=True)

    final = evaluate(head, Xte, yte, classes)
    local = local_test_metrics(cfg)
    with open(out / 'history.csv', 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(history[0].keys()))
        w.writeheader()
        w.writerows(history)
    np.save(out / 'global_weights.npy', g.astype(np.float32))
    summary = {'rounds': rounds, 'local_epochs': local_epochs, 'n_k': sizes, 'n_params': int(n_params),
               'bytes_per_client_per_round': int(n_params * 4), 'seconds': time.time() - t0,
               'test_metrics': final, 'oneshot_average_test_metrics': oneshot, 'round0_test_metrics': base,
               'local_test_metrics': local}
    with open(out / 'metrics.json', 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)
    plot_rounds(history, {c: m for c, m in local.items()}, out / 'rounds.png')

    if verbose:
        print_report(f'[fedavg] TEST sau {rounds} vòng', final, classes)
        print(f'{"mô hình":<28}{"acc":>8}{"macro-F1":>10}' + ''.join(f'{"R_" + k[:4]:>9}' for k in classes) + f'{"sai":>6}')
        rows = [(f'{c} cục bộ', m) for c, m in local.items()]
        if oneshot:
            rows.append(('trung bình 1 lần', oneshot))
        rows.append((f'FedAvg {rounds} vòng', final))
        for name, m in rows:
            wrong = int(round((1 - m['accuracy']) * len(yte)))
            print(f'{name:<28}{m["accuracy"]:>8.4f}{m["macro_f1"]:>10.4f}'
                  + ''.join(f'{m["per_class"][k]["recall"]:>9.3f}' for k in classes) + f'{wrong:>6}')
        print(f'[fedavg] đã lưu vào {out}')
    return summary


if __name__ == '__main__':
    run()
