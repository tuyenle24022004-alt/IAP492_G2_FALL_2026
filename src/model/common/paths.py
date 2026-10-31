import sys
from pathlib import Path

import yaml

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding='utf-8')
    except Exception:
        pass

MODEL_DIR = Path(__file__).resolve().parents[1]
ROOT = MODEL_DIR.parents[1]


def load_config(path=None):
    with open(path or MODEL_DIR / 'config.yaml', encoding='utf-8') as f:
        return yaml.safe_load(f)


def client_paths(client, cfg=None):
    cfg = cfg or load_config()
    data = ROOT / cfg['data_root']
    return {
        'train': data / client / 'train',
        'val': data / client / 'val',
        'test': data / 'test',
        'out': ROOT / cfg['output_root'] / client,
        'features': ROOT / cfg.get('feature_root', cfg['output_root']) / client / 'features',
    }


def shared_dir(cfg):
    return ROOT / cfg.get('feature_root', cfg['output_root']) / 'shared'


def count_images(folder, classes):
    return {c: len(list((Path(folder) / c).glob('*.jpg'))) for c in classes}
