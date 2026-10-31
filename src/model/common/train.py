import csv
import copy
import json
import time

import numpy as np
import torch
import torch.nn.functional as F

from . import data
from . import define_model as dm
from . import finetune as ft
from .evaluate import evaluate
from .paths import client_paths, load_config


class BestTracker:
    def __init__(self):
        self.best = float('inf')
        self.best_epoch = 0

    def update(self, value, epoch):
        if value < self.best:
            self.best = value
            self.best_epoch = epoch
            return True
        return False


def make_optimizer(params, cfg):
    o = cfg['train']['optimizer']
    if o['name'].lower() != 'sgd':
        raise ValueError(f'optimizer chỉ hỗ trợ sgd, nhận {o["name"]}')
    return torch.optim.SGD(params, lr=o['lr'], momentum=o.get('momentum', 0.0), weight_decay=o.get('weight_decay', 0.0))


def make_scheduler(opt, cfg):
    s = cfg['train'].get('scheduler', {'name': 'none'})
    name = s.get('name', 'none')
    if name == 'step':
        return torch.optim.lr_scheduler.StepLR(opt, step_size=s['step_size'], gamma=s['gamma']), False
    if name == 'plateau':
        return torch.optim.lr_scheduler.ReduceLROnPlateau(
            opt, factor=s.get('gamma', 0.1), patience=s.get('patience', 5)), True
    return None, False


def iterate_batches(X, y, batch, rng):
    idx = rng.permutation(len(y))
    for i in range(0, len(idx), batch):
        j = np.sort(idx[i:i + batch])
        yield torch.from_numpy(X[j].astype(np.float32)), torch.from_numpy(y[j])


def train_one_epoch(head, X, y, opt, batch, rng):
    head.train()
    total_loss, correct, n = 0.0, 0, 0
    for xb, yb in iterate_batches(X, y, batch, rng):
        opt.zero_grad()
        logits = head(xb)
        loss = F.cross_entropy(logits, yb)
        loss.backward()
        opt.step()
        total_loss += loss.item() * len(yb)
        correct += int((logits.argmax(dim=1) == yb).sum())
        n += len(yb)
    return total_loss / n, correct / n


def save_curves(history, path):
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
    except Exception:
        return
    ep = [h['epoch'] for h in history]
    fig, axes = plt.subplots(1, 3, figsize=(15, 4))
    axes[0].plot(ep, [h['train_loss'] for h in history], label='train')
    axes[0].plot(ep, [h['val_loss'] for h in history], label='val')
    axes[0].set_title('Loss')
    axes[1].plot(ep, [h['train_acc'] for h in history], label='train')
    axes[1].plot(ep, [h['val_acc'] for h in history], label='val')
    axes[1].set_title('Accuracy')
    axes[2].plot(ep, [h['lr'] for h in history])
    axes[2].set_yscale('log')
    axes[2].set_title('Learning rate')
    for ax in axes:
        ax.set_xlabel('Epoch')
        ax.grid(alpha=0.3)
    axes[0].legend()
    axes[1].legend()
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)


def print_report(title, m, classes):
    print(f'{title}: loss {m["loss"]:.4f}  acc {m["accuracy"]:.4f}  macro-F1 {m["macro_f1"]:.4f}')
    for name in classes:
        v = m['per_class'][name]
        print(f'    {name:<12} P {v["precision"]:.3f}  R {v["recall"]:.3f}  F1 {v["f1"]:.3f}  (n={v["support"]})')


def run(client, epochs=None, cfg=None, verbose=True):
    cfg = cfg or load_config()
    if epochs:
        cfg['train']['epochs'] = int(epochs)
    seed = int(cfg['seed'])
    torch.manual_seed(seed)
    torch.set_num_threads(int(cfg['threads']))
    classes = cfg['classes']
    t = cfg['train']
    n_epochs = int(t['epochs'])
    final_mode = t.get('final_weights', 'last')
    if final_mode not in ('last', 'best_val_loss'):
        raise ValueError(f'final_weights phải là last hoặc best_val_loss, nhận {final_mode}')

    feats = data.load_client_features(client, cfg, splits=('train', 'val'))
    Xtr, ytr = feats['train']
    Xva, yva = feats['val']

    net, source = ft.prepare_model(cfg)
    cut = ft.feature_cut(cfg['model']['trainable'])
    _, head = dm.split_model(net, cut)
    params = [p for p in head.parameters() if p.requires_grad]
    opt = make_optimizer(params, cfg)
    sched, on_val = make_scheduler(opt, cfg)
    tracker = BestTracker()

    out = client_paths(client, cfg)['out'] / 'run'
    out.mkdir(parents=True, exist_ok=True)
    if verbose:
        print(f'[{client}] train {len(ytr)} ảnh, val {len(yva)} ảnh; tham số huấn luyện {sum(p.numel() for p in params):,}; '
              f'khởi tạo {source}', flush=True)
        print(f'[{client}] huấn luyện đủ {n_epochs} epoch (không dừng sớm); mô hình cuối: '
              f'{"epoch cuối" if final_mode == "last" else "epoch có val loss thấp nhất"}', flush=True)

    history, best_state = [], copy.deepcopy(head.state_dict())
    t0 = time.time()
    for epoch in range(1, n_epochs + 1):
        te = time.time()
        rng = np.random.default_rng(seed * 1000 + epoch)
        lr = opt.param_groups[0]['lr']
        tr_loss, tr_acc = train_one_epoch(head, Xtr, ytr, opt, int(t['batch']), rng)
        val = evaluate(head, Xva, yva, classes)
        improved = tracker.update(val['loss'], epoch)
        if improved:
            best_state = copy.deepcopy(head.state_dict())
        history.append({'epoch': epoch, 'train_loss': tr_loss, 'train_acc': tr_acc, 'val_loss': val['loss'],
                        'val_acc': val['accuracy'], 'val_macro_f1': val['macro_f1'], 'lr': lr,
                        'seconds': time.time() - te})
        if verbose:
            print(f'[{client}] epoch {epoch:3d}  train {tr_loss:.4f}/{tr_acc:.3f}  val {val["loss"]:.4f}/{val["accuracy"]:.3f}  '
                  f'F1 {val["macro_f1"]:.3f}  lr {lr:.1e}{"  *" if improved else ""}', flush=True)
        if sched is not None:
            sched.step(val['loss']) if on_val else sched.step()

    if final_mode == 'best_val_loss':
        head.load_state_dict(best_state)
        used_epoch = tracker.best_epoch
    else:
        used_epoch = n_epochs
    final_state = copy.deepcopy(head.state_dict())
    final_val = evaluate(head, Xva, yva, classes)
    final_train = evaluate(head, Xtr, ytr, classes)
    vec = ft.trainable_vector(net)

    with open(out / 'history.csv', 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(history[0].keys()))
        w.writeheader()
        w.writerows(history)
    torch.save(final_state, out / 'final_head.pt')
    np.save(out / 'weights.npy', vec.astype(np.float32))
    save_curves(history, out / 'curves.png')
    summary = {
        'client': client,
        'epochs_run': len(history),
        'final_weights': final_mode,
        'final_epoch': used_epoch,
        'best_val_epoch': tracker.best_epoch,
        'best_val_loss': tracker.best,
        'seconds_total': time.time() - t0,
        'seconds_per_epoch': float(np.mean([h['seconds'] for h in history])),
        'n_trainable': int(vec.size),
        'config': cfg,
        'train_metrics': final_train,
        'val_metrics': final_val,
    }
    with open(out / 'metrics.json', 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)

    if verbose:
        print(f'[{client}] xong {len(history)} epoch; mô hình cuối = epoch {used_epoch}; epoch có val loss thấp nhất = '
              f'{tracker.best_epoch} ({tracker.best:.4f}); {summary["seconds_total"]:.0f}s ({summary["seconds_per_epoch"]:.2f}s/epoch)')
        print_report(f'[{client}] TRAIN (mô hình cuối)', final_train, classes)
        print_report(f'[{client}] VAL   (mô hình cuối)', final_val, classes)
        print(f'[{client}] đã lưu vào {out}')
    return summary
