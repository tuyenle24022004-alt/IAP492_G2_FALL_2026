import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common import pi4_guard                                                       # noqa: F401,E402  bắt buộc: tự đưa tiến trình vào giả lập Pi 4

import numpy as np
import torch

from common import data, finetune as ft
from common.paths import load_config

CLIENT = 'client1'


def run():
    cfg = load_config()
    torch.set_num_threads(int(cfg['threads']))
    net, source = ft.prepare_model(cfg)
    print(f'[{CLIENT}] trọng số khởi tạo: {source}; chế độ: {cfg["model"]["trainable"]}; '
          f'ảnh {cfg["model"]["input_size"]}x{cfg["model"]["input_size"]} ({cfg["model"]["resize_mode"]})', flush=True)
    return data.extract_client(CLIENT, net, cfg)


if __name__ == '__main__':
    feats = run()
    for split, (X, y) in feats.items():
        values, counts = np.unique(y, return_counts=True)
        print(f'[{CLIENT}] {split}: X {X.shape} {X.dtype}, nhãn {dict(zip(values.tolist(), counts.tolist()))}')
