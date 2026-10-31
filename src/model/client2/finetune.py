import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common import pi4_guard                                                       # noqa: F401,E402  bắt buộc: tự đưa tiến trình vào giả lập Pi 4

from common import finetune as ft
from common.paths import load_config, client_paths, count_images

CLIENT = 'client2'


def prepare(cfg=None, pretrained=True):
    cfg = cfg or load_config()
    return ft.prepare_model(cfg, pretrained)


if __name__ == '__main__':
    cfg = load_config()
    net, source = prepare(cfg)
    s = ft.summary(net)
    print(f'[{CLIENT}] trọng số khởi tạo: {source}')
    print(f'[{CLIENT}] chế độ finetune: {cfg["model"]["trainable"]}')
    print(f'[{CLIENT}] tham số huấn luyện: {s["huan_luyen"]:,} / {s["tong"]:,} (đóng băng {s["dong_bang"]:,})')
    for name, v in s['theo_lop'].items():
        print(f'  {name:<16} {v["params"]:>9,}  {"HUẤN LUYỆN" if v["trainable"] else "đóng băng"}')
    paths = client_paths(CLIENT, cfg)
    for k in ('train', 'val'):
        n = count_images(paths[k], cfg['classes'])
        print(f'[{CLIENT}] {k}: {sum(n.values()):,} ảnh {n}')
