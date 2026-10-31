"""Gộp kết quả một seed (mọi arm) thành seed<N>.json và (khi lock.attack_enabled) tính tấn công NGOẠI TUYẾN trên đúng thứ BS đã nhận (capture/).
TẠM TẮT (lock.attack_enabled: false, từ 30/10/2026): không tính tấn công, 'attacks' = []; phần mã tấn công giữ nguyên để bật lại sau.

Cái bị bảo vệ là TRỌNG SỐ cục bộ v_k của client k (x_k = w_k · v_k). Kẻ tấn công = BS tò mò dựng lại v_k:
  none      : đọc được x_k nên v̂_k = x_k / w_k (chính xác)
  ckks_full : chỉ biết tổng sau khi ghép (= mô hình toàn cục) -> v̂_k = tổng
  fas       : biết tổng ở phần HE; phần rõ đã xáo nên BỎ QUA (đặt bừa chỉ làm tệ đi), trừ fasbs_* (BS có K) thì đọc được
Mốc tham chiếu mỗi arm: đoán v_k bằng đúng phần tổng BS biết (tổng đầy đủ; riêng FAS không có K thì chỉ phần HE, còn lại 0).
Skill = 1 - (sai số dựng lại / sai số mốc)^2: 1 = hoàn hảo, 0 = chỉ ngang mốc, < 0 = tệ hơn.
Cũng đo accuracy trên test của mô hình v̂_k (mô hình "ăn cắp") và của mô hình mốc.
"""
import copy
import json
import sys
from pathlib import Path

import numpy as np
import torch
import yaml

SRC = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(SRC / 'model'))

from common import data, define_model as dm, finetune as ft                      # noqa: E402
from common.evaluate import evaluate                                             # noqa: E402
from common.fedavg import get_vec, set_vec, trainable_params                     # noqa: E402
from common.paths import load_config                                             # noqa: E402
from secure_fl.arms import arm_list, bs_has_key                                  # noqa: E402
from secure_fl.security import make_scheme, priority_order                       # noqa: E402

DEVS = (1, 2)


def cos(a, b):
    d = np.linalg.norm(a) * np.linalg.norm(b)
    return float(a @ b / d) if d > 0 else 0.0


def known_sum(kind, scheme, gsum, knows_k):
    """Phần tổng (mô hình toàn cục) mà BS thực sự biết."""
    if kind == 'fas' and not knows_k:
        k = np.zeros_like(gsum)
        k[scheme.idx_he] = gsum[scheme.idx_he]
        return k
    return gsum.copy()


def estimate(kind, view_vals, view_idx, w_k, known, knows_k):
    """v̂_k của kẻ tấn công cho một arm (xem docstring đầu file)."""
    if kind == 'none':
        return view_vals / w_k
    if kind == 'ckks_full' or not knows_k:
        return known.copy()
    est = known.copy()
    est[view_idx] = view_vals / w_k                    # fasbs: BS có K nên biết vị trí
    return est


def slim(rows):
    return [{'round': r['t'], **{k: v for k, v in r['metrics'].items() if k != 't'}} for r in rows]


def collect_seed(seed_dir, model, lock, rounds):
    seed_dir = Path(seed_dir)
    seed = int(seed_dir.name.replace('seed', ''))
    base = copy.deepcopy(load_config())
    base['seed'] = seed
    base['model']['trainable'] = model
    base['feature_root'] = base['output_root']
    classes = base['classes']
    torch.set_num_threads(int(base['threads']))
    Xte, yte = data.load_client_features('client1', base, splits=('test',))['test']
    net, _ = ft.prepare_model(base)
    _, head = dm.split_model(net, ft.feature_cut(model))
    M = get_vec(head).size
    order = priority_order([p.numel() for p in trainable_params(head)])
    result = {'seed': seed, 'model': model, 'M': int(M), 'rounds': rounds, 'backend': lock['backend'], 'arms': {}}
    g_none = pred_none = None

    def acc_of(vec):
        set_vec(head, vec)
        return evaluate(head, Xte, yte, classes)['accuracy']

    for name, kind, kw in arm_list(lock):
        d = seed_dir / name
        if not (d / 'bs_log.json').exists():
            continue
        bs = json.load(open(d / 'bs_log.json', encoding='utf-8'))
        c = {k: json.load(open(d / f'client{k}_log.json', encoding='utf-8')) for k in DEVS}
        g1, g2 = np.load(d / 'g_client1.npy'), np.load(d / 'g_client2.npy')      # g[t] = mô hình toàn cục sau vòng t (t = 0..R)
        pred = np.load(d / 'pred_client1.npy')
        if name == 'none':
            g_none, pred_none = g1, pred
        K = (d / 'keys' / 'perm_seed').read_bytes() if (d / 'keys' / 'perm_seed').exists() else b'\0' * 32
        scheme = make_scheme(kind, M, he=None, order=order, K=K, **kw)
        knows_k = bs_has_key(name, lock)

        rows = slim(bs['rounds'])
        for r in rows:
            t = r['round']
            r['drift_l2'] = float(np.linalg.norm(g1[t] - g_none[t])) if g_none is not None else 0.0
            r['drift_linf'] = float(np.abs(g1[t] - g_none[t]).max()) if g_none is not None else 0.0
            tr = [np.load(d / 'truth' / f'client{k}_round{t}.npz') for k in DEVS]
            exact = sum(float(z['w']) * z['local'] for z in tr)
            r['err_vs_exact_linf'] = float(np.abs(tr[0]['gsum'] - exact).max())

        attacks = []
        for t in (lock['attack_rounds'] if lock.get('attack_enabled', False) else []):      # tạm tắt: attack_enabled: false -> attacks = []
            if t > rounds:
                continue
            for k in DEVS:
                z = np.load(d / 'truth' / f'client{k}_round{t}.npz')
                local, gsum, w_k = z['local'], z['gsum'], float(z['w'])
                f = d / 'capture' / f'round{t}_dev{k}_plain.npy'
                vals, idx = (None, None)
                if f.exists():
                    vals, idx = scheme.bs_view({'plain': np.load(f)}, t)
                known = known_sum(kind, scheme, gsum, knows_k)
                est = estimate(kind, vals, idx, w_k, known, knows_k)
                nl = np.linalg.norm(local)
                attacks.append({'round': t, 'client': k, 'cos': cos(est, local), 'cos_ref': cos(known, local),
                                'rel_err': float(np.linalg.norm(est - local) / nl),
                                'rel_ref': float(np.linalg.norm(known - local) / nl),
                                'acc': acc_of(est), 'acc_ref': acc_of(known)})

        def bytes_of(key):
            return np.mean([[r['bytes'].get(key, {}).get(str(k), 0) for k in DEVS] for r in bs['rounds']])

        up, sh = bytes_of('UPLOAD'), bytes_of('PARTIAL_DEC')
        down = bytes_of('CSUM') + bytes_of('AGGREGATE')

        def mean(key, src):
            return float(np.mean([r.get(key, 0.0) for r in src]))

        train_rows = [r for r in c[1]['rounds'] if r['t'] > 0]
        final = rows[-1]
        result['arms'][name] = {
            'kind': kind, 'params': {k: v for k, v in kw.items() if k != 'K'}, 'rounds': rows, 'attacks': attacks,
            'round0': {k: v for k, v in rows[0].items() if k in ('acc', 'f1', 'loss')},
            'bytes_per_client': {'upload': float(up), 'partial_dec': float(sh), 'up_total': float(up + sh), 'down_total': float(down),
                                 'expansion_vs_plain': float((up + sh) / (4 * M))},
            'n_ct': bs['sizes']['n_ct'],
            'time_s': {'train': mean('train_s', train_rows), 'protect': mean('protect_s', c[1]['rounds']),
                       'partial_dec': mean('partial_dec_s', c[1]['rounds']), 'finish': mean('finish_s', c[1]['rounds']),
                       'bs_aggregate': mean('aggregate', [r['phase_s'] for r in bs['rounds']]),
                       'bs_fuse': mean('fuse', [r['phase_s'] for r in bs['rounds']]),
                       'round': mean('round', [r['phase_s'] for r in bs['rounds']])},
            'final': {k: v for k, v in final.items() if k not in ('round', 'drift_l2', 'drift_linf', 'err_vs_exact_linf')},
            'final_errors': int(round((1 - final['acc']) * len(yte))),
            'pred_diff_vs_none': int((pred != pred_none).sum()) if pred_none is not None else 0,
            'models_equal_linf': float(np.abs(g1 - g2).max()),
            'noise_sd_mean': float(np.mean([r.get('noise_sd', 0.0) for r in c[1]['rounds']]))}
    from secure_fl.runlog import archive_existing
    archive_existing(seed_dir.parent / f'seed{seed}.json')            # giữ bản cũ trong lich_su/ trước khi ghi đè
    with open(seed_dir.parent / f'seed{seed}.json', 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    return result


if __name__ == '__main__':
    from secure_fl import settings
    scfg = settings.load()
    mcfg = yaml.safe_load(open(SRC / 'model' / 'config.yaml', encoding='utf-8'))
    collect_seed(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else 'classifier', scfg['lock'],
                 int(sys.argv[3]) if len(sys.argv) > 3 else int(mcfg['fl']['rounds']))
