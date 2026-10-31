import time

import numpy as np
import torch
from PIL import Image

from . import define_model as dm
from . import finetune as ft
from .paths import client_paths, shared_dir

MEAN = np.array([0.485, 0.456, 0.406], np.float32)
STD = np.array([0.229, 0.224, 0.225], np.float32)
PAD_COLOR = tuple(int(round(v * 255)) for v in MEAN)


def load_image(path, size, mode='squash'):
    im = Image.open(path).convert('RGB')
    w, h = im.size
    if mode == 'squash':
        im = im.resize((size, size), Image.BILINEAR)
    elif mode == 'center_crop':
        s = min(w, h)
        left, top = (w - s) // 2, (h - s) // 2
        im = im.crop((left, top, left + s, top + s)).resize((size, size), Image.BILINEAR)
    elif mode == 'pad':
        s = max(w, h)
        canvas = Image.new('RGB', (s, s), PAD_COLOR)
        canvas.paste(im, ((s - w) // 2, (s - h) // 2))
        im = canvas.resize((size, size), Image.BILINEAR)
    else:
        raise ValueError(f'resize_mode phải là squash, center_crop hoặc pad, nhận {mode}')
    a = (np.asarray(im, np.float32) / 255.0 - MEAN) / STD
    return a.transpose(2, 0, 1)


def list_images(folder, classes):
    files, labels = [], []
    for idx, c in enumerate(classes):
        found = sorted((folder / c).glob('*.jpg'))
        files += found
        labels += [idx] * len(found)
    return files, labels


def extract_features(trunk, files, labels, size, mode, batch=64, tag=''):
    trunk.eval()
    feats = []
    t0 = time.time()
    with torch.no_grad():
        for i in range(0, len(files), batch):
            x = torch.from_numpy(np.stack([load_image(p, size, mode) for p in files[i:i + batch]]))
            feats.append(trunk(x).half().numpy())
            done = min(i + batch, len(files))
            if (i // batch) % 10 == 0 or done == len(files):
                print(f'[trích đặc trưng] {tag} {done}/{len(files)} ({time.time() - t0:.0f}s)', flush=True)
    return np.concatenate(feats), np.array(labels, np.int64)


def cache_file(folder, split, cut, cfg):
    m = cfg['model']
    return folder / f'{split}_cut{cut}_s{m["input_size"]}_{m["resize_mode"]}.npz'


def get_features(split, image_dir, cache_dir, trunk, cfg, cut):
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_file(cache_dir, split, cut, cfg)
    if path.exists():
        z = np.load(path)
        print(f'[trích đặc trưng] {split}: dùng cache {path.name}', flush=True)
        return z['X'], z['y']
    files, labels = list_images(image_dir, cfg['classes'])
    if not files:
        raise FileNotFoundError(f'không thấy ảnh trong {image_dir}')
    m = cfg['model']
    X, y = extract_features(trunk, files, labels, m['input_size'], m['resize_mode'], tag=split)
    np.savez(path, X=X, y=y, files=np.array([str(p.relative_to(image_dir)) for p in files]))
    print(f'[trích đặc trưng] {split}: lưu {path.name} {X.shape} {path.stat().st_size / 1e6:.0f} MB', flush=True)
    return X, y


def extract_client(client, net, cfg):
    cut = ft.feature_cut(cfg['model']['trainable'])
    trunk, _ = dm.split_model(net, cut)
    paths = client_paths(client, cfg)
    out = {}
    for split in ('train', 'val'):
        out[split] = get_features(split, paths[split], paths['features'], trunk, cfg, cut)
    out['test'] = get_features('test', paths['test'], shared_dir(cfg), trunk, cfg, cut)
    return out


def load_client_features(client, cfg, splits=('train', 'val', 'test')):
    cut = ft.feature_cut(cfg['model']['trainable'])
    paths = client_paths(client, cfg)
    out = {}
    folders = {'train': paths['features'], 'val': paths['features'], 'test': shared_dir(cfg)}
    trunk = None
    for split in splits:
        folder = folders[split]
        path = cache_file(folder, split, cut, cfg)
        if not path.exists():
            # chưa có cache: tự trích đặc trưng (một lần) thay vì báo lỗi bắt người dùng chạy extract_features.py
            if trunk is None:
                print(f'[{client}] chưa có cache {path.name}, tự trích đặc trưng', flush=True)
                net, _ = ft.prepare_model(cfg)
                trunk, _ = dm.split_model(net, cut)
            get_features(split, paths[split], folder, trunk, cfg, cut)
        z = np.load(path)
        out[split] = (z['X'], z['y'])
    return out
