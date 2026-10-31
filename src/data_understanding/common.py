import io
import os
import re
import sys
import hashlib
from pathlib import Path

import numpy as np
from PIL import Image

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding='utf-8')
    except Exception:
        pass

ROOT = Path(__file__).resolve().parents[2]
DATA = Path(os.environ.get('DU_DATA', ROOT / 'data' / 'clients'))
OUT = Path(os.environ.get('DU_OUT', ROOT / 'outputs' / 'data_understanding'))
ANALYSIS = OUT / 'analysis'
FIG = OUT / 'figures'

CLASSES = ['binh_thuong', 'khoi', 'lua']
CLASS_VI = {'binh_thuong': 'Bình thường', 'khoi': 'Khói', 'lua': 'Lửa'}
COLORS = {'binh_thuong': '#4C9A5F', 'khoi': '#8A8F98', 'lua': '#E0602B'}
SETS = ['client1_train', 'client1_val', 'client2_train', 'client2_val', 'test']
SET_PATH = {'client1_train': 'client1/train', 'client1_val': 'client1/val', 'client2_train': 'client2/train',
            'client2_val': 'client2/val', 'test': 'test'}
SET_COLORS = {'client1_train': '#3B6FB6', 'client1_val': '#8FB2E0', 'client2_train': '#C0504D', 'client2_val': '#E39A98',
              'test': '#F2B134'}
SOURCE_VI = {
    'smoke_cam': 'Camera khói (data_clients_1)',
    'fire_train': 'Lửa - Train_Data',
    'fire_test': 'Lửa - Test_Data',
    'nonfire_train': 'Bình thường - Train_Data',
    'nonfire_test': 'Bình thường - Test_Data',
    'khac': 'Khác',
}

GRAY = np.array([0.299, 0.587, 0.114], np.float32)


def ensure_dirs():
    for d in (ANALYSIS, FIG):
        d.mkdir(parents=True, exist_ok=True)


def source_of(name):
    if 'train-smoke' in name:
        return 'smoke_cam'
    if 'Train_Data_Fire' in name:
        return 'fire_train'
    if 'Test_Data_Fire' in name:
        return 'fire_test'
    if 'Train_Data_Non_Fire' in name:
        return 'nonfire_train'
    if 'Test_Data_Non_Fire' in name:
        return 'nonfire_test'
    return 'khac'


def frame_of(name):
    if 'train-smoke' not in name:
        return -1
    m = re.search(r'(\d+)\.\w+$', name)
    return int(m.group(1)) if m else -1


def list_files():
    rows = []
    for s in SETS:
        for c in CLASSES:
            d = DATA / SET_PATH[s] / c
            if not d.is_dir():
                print(f'[canh bao] không thấy {d}', flush=True)
                continue
            for p in sorted(d.iterdir()):
                if p.is_file():
                    rows.append({'tap': s, 'label': c, 'file': p.name, 'rel': p.relative_to(DATA).as_posix(),
                                 'source': source_of(p.name), 'frame': frame_of(p.name)})
    return rows


def dhash(img):
    a = np.asarray(img.convert('L').resize((9, 8), Image.BILINEAR), np.int16)
    bits = (a[:, 1:] > a[:, :-1]).flatten()
    return int(np.packbits(bits).view('>u8')[0])


def hashes_to_array(hex_values):
    return np.array([int(h, 16) for h in hex_values], dtype=np.uint64)


def hamming_matrix(a, b):
    return np.bitwise_count(a[:, None] ^ b[None, :]).astype(np.int16)


def image_features(rel):
    data = (DATA / rel).read_bytes()
    r = {'rel': rel, 'readable': False, 'error': '', 'file_kb': len(data) / 1024,
         'md5': hashlib.md5(data).hexdigest()}
    try:
        im = Image.open(io.BytesIO(data))
        r['format'] = im.format
        r['mode'] = im.mode
        w, h = im.size
        r['width'], r['height'] = w, h
        im = im.convert('RGB')
    except Exception as e:
        r['error'] = f'{type(e).__name__}: {e}'[:120]
        return r
    a = np.asarray(im, np.float32)
    g = a @ GRAY
    hsv = np.asarray(im.convert('HSV'), np.float32)
    lap = 4 * g[1:-1, 1:-1] - g[:-2, 1:-1] - g[2:, 1:-1] - g[1:-1, :-2] - g[1:-1, 2:]
    R, G, B = a[..., 0], a[..., 1], a[..., 2]
    r.update({
        'readable': True,
        'aspect': w / h,
        'mean_r': float(R.mean()), 'mean_g': float(G.mean()), 'mean_b': float(B.mean()),
        'brightness': float(g.mean()),
        'contrast': float(g.std()),
        'saturation': float(hsv[..., 1].mean()),
        'sharpness': float(lap.var()),
        'warm_ratio': float(((R > 180) & (R > G * 1.25) & (G > B)).mean()),
        'gray_ratio': float(((hsv[..., 1] < 40) & (hsv[..., 2] > 150)).mean()),
        'dhash': format(dhash(im), '016x'),
    })
    return r


def open_image(rel):
    return Image.open(DATA / rel).convert('RGB')
