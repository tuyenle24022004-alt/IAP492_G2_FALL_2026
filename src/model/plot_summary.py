import json

import numpy as np
import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

from common.paths import ROOT, client_paths, load_config

plt.rcParams.update({
    'figure.dpi': 110, 'savefig.dpi': 160, 'font.size': 10, 'axes.titlesize': 12, 'axes.titleweight': 'bold',
    'axes.spines.top': False, 'axes.spines.right': False, 'axes.grid': True, 'grid.alpha': 0.25, 'axes.axisbelow': True,
})

CLASS_VI = {'binh_thuong': 'Bình thường', 'khoi': 'Khói', 'lua': 'Lửa'}
CLASS_COLORS = {'binh_thuong': '#4C9A5F', 'khoi': '#8A8F98', 'lua': '#E0602B'}
MODEL_COLORS = ['#3B6FB6', '#C0504D', '#9BBB59', '#2A9D5C']


def load_json(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def draw_box(ax, x, y, w, h, title, lines, color):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle='round,pad=0.02,rounding_size=0.03', fc=color, ec='#444', lw=1.2, alpha=0.18))
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle='round,pad=0.02,rounding_size=0.03', fc='none', ec='#444', lw=1.2))
    ax.text(x + w / 2, y + h - 0.05, title, ha='center', va='top', fontsize=11, fontweight='bold')
    for i, line in enumerate(lines):
        ax.text(x + w / 2, y + h - 0.13 - i * 0.065, line, ha='center', va='top', fontsize=9)


def arrow(ax, p, q, text='', dy=0.03):
    ax.add_patch(FancyArrowPatch(p, q, arrowstyle='-|>', mutation_scale=16, lw=1.6, color='#333'))
    if text:
        ax.text((p[0] + q[0]) / 2, (p[1] + q[1]) / 2 + dy, text, ha='center', va='bottom', fontsize=8.5)


def fig_overview(cfg, out):
    c1 = load_json(client_paths('client1', cfg)['out'] / 'run' / 'metrics.json')
    c2 = load_json(client_paths('client2', cfg)['out'] / 'run' / 'metrics.json')
    n1 = int(sum(sum(r) for r in [c1['train_metrics']['confusion_matrix']][0]))
    n2 = int(sum(sum(r) for r in [c2['train_metrics']['confusion_matrix']][0]))
    sup1 = [c1['train_metrics']['per_class'][k]['support'] for k in cfg['classes']]
    sup2 = [c2['train_metrics']['per_class'][k]['support'] for k in cfg['classes']]
    fl = cfg['fl']
    fig, ax = plt.subplots(figsize=(12, 5.2))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis('off')
    ax.grid(False)
    vn = lambda v: f'{v:,}'.replace(',', '.')
    draw_box(ax, 0.02, 0.54, 0.28, 0.42, 'Thiết bị 1 (client1)',
             [f'{vn(n1)} ảnh train', f'Bình thường {vn(sup1[0])} | Khói {vn(sup1[1])} | Lửa {vn(sup1[2])}',
              'Thân SqueezeNet đóng băng', 'Huấn luyện lớp cuối (1.539 tham số)'], '#3B6FB6')
    draw_box(ax, 0.02, 0.04, 0.28, 0.42, 'Thiết bị 2 (client2)',
             [f'{vn(n2)} ảnh train', f'Bình thường {vn(sup2[0])} | Khói {vn(sup2[1])} | Lửa {vn(sup2[2])}',
              'Thân SqueezeNet đóng băng', 'Huấn luyện lớp cuối (1.539 tham số)'], '#C0504D')
    draw_box(ax, 0.42, 0.29, 0.24, 0.42, 'Máy chủ (FedAvg)',
             ['w = (n1·w1 + n2·w2) / (n1 + n2)', f'n1/n = {n1 / (n1 + n2):.4f}', f'n2/n = {n2 / (n1 + n2):.4f}',
              f'{fl["rounds"]} vòng, {fl["local_epochs"]} epoch cục bộ/vòng'], '#2A9D5C')
    draw_box(ax, 0.755, 0.29, 0.20, 0.42, 'Đánh giá',
             ['Tập test chung', '1.005 ảnh chưa từng thấy', 'Chấm mô hình toàn cục', 'sau tổng hợp'], '#F2B134')
    arrow(ax, (0.30, 0.62), (0.42, 0.56), 'w1 (6 KB)', dy=0.025)
    arrow(ax, (0.30, 0.38), (0.42, 0.44), 'w2 (6 KB)', dy=-0.06)
    arrow(ax, (0.42, 0.62), (0.30, 0.70), 'w toàn cục', dy=0.02)
    arrow(ax, (0.42, 0.38), (0.30, 0.30), 'w toàn cục', dy=-0.055)
    arrow(ax, (0.66, 0.50), (0.755, 0.50), 'w cuối', dy=0.025)
    ax.set_title('Sơ đồ học liên kết giữa hai thiết bị biên', pad=8)
    fig.tight_layout()
    fig.savefig(out, bbox_inches='tight')
    plt.close(fig)


def fig_comparison(cfg, fed_dir, out):
    fed = load_json(fed_dir / 'metrics.json')
    models = [('client1 cục bộ', fed['local_test_metrics']['client1']), ('client2 cục bộ', fed['local_test_metrics']['client2'])]
    if fed.get('oneshot_average_test_metrics'):
        models.append(('Trung bình 1 lần', fed['oneshot_average_test_metrics']))
    models.append((f'FedAvg {fed["rounds"]} vòng', fed['test_metrics']))
    classes = cfg['classes']
    fig, axes = plt.subplots(1, 2, figsize=(13, 4.6), gridspec_kw={'width_ratios': [1, 1.5]})
    ax = axes[0]
    acc = [m['accuracy'] * 100 for _, m in models]
    bars = ax.bar(range(len(models)), acc, color=MODEL_COLORS[:len(models)])
    for b, (_, m), a in zip(bars, models, acc):
        wrong = int(round((1 - m['accuracy']) * sum(sum(r) for r in m['confusion_matrix'])))
        ax.text(b.get_x() + b.get_width() / 2, a + 0.05, f'{a:.2f}%\n({wrong} sai)', ha='center', va='bottom', fontsize=9)
    ax.set_xticks(range(len(models)))
    ax.set_xticklabels([n.replace(' ', '\n', 1) for n, _ in models], fontsize=9)
    ax.set_ylim(min(acc) - 2, max(acc) + 1.2)
    ax.set_ylabel('Accuracy trên test (%)')
    ax.set_title('Accuracy trên tập test')
    ax.grid(axis='x', visible=False)
    ax = axes[1]
    w = 0.8 / len(models)
    x = np.arange(len(classes))
    for i, (name, m) in enumerate(models):
        v = [m['per_class'][k]['recall'] for k in classes]
        ax.bar(x + (i - (len(models) - 1) / 2) * w, v, w, color=MODEL_COLORS[i], label=name)
        for xi, vi in zip(x + (i - (len(models) - 1) / 2) * w, v):
            ax.text(xi, vi + 0.002, f'{vi:.3f}', ha='center', va='bottom', fontsize=7.5, rotation=90)
    ax.set_xticks(x)
    ax.set_xticklabels([CLASS_VI[k] for k in classes])
    ax.set_ylim(0.88, 1.03)
    ax.set_ylabel('Recall trên test')
    ax.set_title('Recall từng lớp')
    ax.legend(frameon=False, fontsize=8.5, ncol=4, loc='upper center', bbox_to_anchor=(0.5, -0.1))
    ax.grid(axis='x', visible=False)
    fig.tight_layout()
    fig.savefig(out, bbox_inches='tight')
    plt.close(fig)


def fig_confusion(cfg, fed_dir, out):
    fed = load_json(fed_dir / 'metrics.json')
    cm = np.asarray(fed['test_metrics']['confusion_matrix'])
    classes = cfg['classes']
    norm = cm / np.maximum(cm.sum(axis=1, keepdims=True), 1)
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.2))
    for ax, mat, count, sub in ((axes[0], cm, True, 'Số ảnh'), (axes[1], norm, False, 'Tỷ lệ theo hàng (recall)')):
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
                ax.text(j, i, str(int(v)) if count else f'{v:.1%}', ha='center', va='center',
                        color='white' if v > top * 0.55 else '#222')
        fig.colorbar(im, ax=ax, shrink=0.8)
    fig.suptitle(f'FedAvg {fed["rounds"]} vòng: mô hình toàn cục trên test', fontweight='bold')
    fig.tight_layout()
    fig.savefig(out, bbox_inches='tight')
    plt.close(fig)


def main():
    cfg = load_config()
    shared = ROOT / cfg['output_root'] / 'shared'
    fed_dir = ROOT / cfg['output_root'] / str(cfg['fl'].get('run_name', 'fedavg'))
    shared.mkdir(parents=True, exist_ok=True)
    fig_overview(cfg, shared / 'overview_fl.png')
    print(f'đã lưu {shared / "overview_fl.png"}')
    if (fed_dir / 'metrics.json').exists():
        fig_comparison(cfg, fed_dir, fed_dir / 'comparison.png')
        fig_confusion(cfg, fed_dir, fed_dir / 'confusion_matrix.png')
        print(f'đã lưu {fed_dir / "comparison.png"} và {fed_dir / "confusion_matrix.png"}')
    else:
        print(f'chưa có {fed_dir / "metrics.json"}, chạy run_fedavg.py trước để vẽ hình so sánh FedAvg')


if __name__ == '__main__':
    main()
