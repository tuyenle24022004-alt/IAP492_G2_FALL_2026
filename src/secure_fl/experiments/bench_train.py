"""Đo thời gian thô 1 epoch huấn luyện cục bộ của từng client (chạy khi máy rảnh, từng client một).
Ghi outputs/experiments/lock_vs_none/timing.json; cost_time.py --train-s dùng giá trị trung vị."""
import copy
import json
import sys
import time
from pathlib import Path

import numpy as np
import torch

SRC = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(SRC / 'model'))

from secure_fl import devicelimit                                                # noqa: E402

devicelimit.enforce('bench_train')                                               # bắt buộc: đo trong giả lập Pi 4, không đo ngoài giả lập

from common import data, define_model as dm, finetune as ft                      # noqa: E402
from common.fedavg import get_vec, local_update                                  # noqa: E402
from common.paths import ROOT, load_config                                       # noqa: E402

CLIENTS = ['client1', 'client2']


def main(model='classifier', reps=7):
    cfg = copy.deepcopy(load_config())
    cfg['model']['trainable'] = model
    cfg['feature_root'] = cfg['output_root']
    torch.set_num_threads(int(cfg['threads']))
    net, _ = ft.prepare_model(cfg)
    _, head = dm.split_model(net, ft.feature_cut(model))
    g = get_vec(head)
    out = {'model': model, 'threads': int(cfg['threads']), 'epoch_s': {}}
    for c in CLIENTS:
        X, y = data.load_client_features(c, cfg, splits=('train',))['train']
        ts = []
        for r in range(reps):
            a = time.perf_counter()
            local_update(head, g, X, y, cfg, 1, 1000 + r)
            ts.append(time.perf_counter() - a)
        out['epoch_s'][c] = {'runs': ts, 'median': float(np.median(ts)), 'cv': float(np.std(ts) / np.mean(ts))}
        print(c, f'trung vị {np.median(ts):.3f}s  CV {100 * np.std(ts) / np.mean(ts):.1f}%')
    out['median_s'] = float(np.median([v['median'] for v in out['epoch_s'].values()]))
    p = ROOT / 'outputs' / 'secure_fl'
    p.mkdir(parents=True, exist_ok=True)
    with open(p / f'timing_{model}.json', 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main(*(sys.argv[1:2] or ['classifier']))
