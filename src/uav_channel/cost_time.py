"""Chi phí truyền thông và thời gian vòng của ba chế độ trên hai kênh (có UAV, không UAV) — KHÔNG chạy FL.

Byte mỗi vòng lấy từ security/ (số đo cũ của ciphertext trong config), tốc độ R_k lấy từ src/uav_channel/channel (hàm thuần),
thời gian truyền = byte / R_k (quasi-static, áp cho cả UPLOAD và PARTIAL_DEC, chiều xuống không bóp — CLAUDE.md 4.2).
Thời gian vòng = huấn luyện + mã hóa + max_k(UPLOAD_k/R_k) + cộng + giải mã từng phần + max_k(PARTIAL_DEC_k/R_k) + ghép.
CHƯA ĐO trong đề tài hiện tại (UAV/kênh để sau). Chạy: python src/uav_channel/cost_time.py [--train-s <giây một epoch một client, thô>]
"""
import argparse
import copy
import json
import sys
from pathlib import Path

import numpy as np
import yaml

SRC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SRC))

from secure_fl.security import make_backend, make_scheme, priority_order         # noqa: E402
from uav_channel.channel import ChannelModel                                     # noqa: E402

ROOT = SRC.parent
MODELS = {'classifier': {'M': 1539, 'blocks': [1536, 3]}, 'fire9_classifier': {'M': 198723, 'blocks': None}}
SCHEMES = [('none', 'none', {}), ('ckks_full', 'ckks_full', {}), ('fas_p10', 'fas', {'p': 0.1, 'lam': 3.0}),
           ('fas_p50', 'fas', {'p': 0.5, 'lam': 3.0})]


def comp_times(kind, n_he, n_ct_all, he, fid):
    """Thời gian tính toán HE (giây, thang Pi 4) theo số ciphertext; none không có."""
    if kind == 'none' or n_ct_all == 0:
        return {'enc': 0.0, 'add': 0.0, 'pdec': 0.0, 'fuse': 0.0}
    return {'enc': n_ct_all * he['t_enc_ct_s'] * fid, 'add': n_ct_all * he['t_add_ct_s'],
            'pdec': n_ct_all * he['t_pdec_ct_s'] * fid, 'fuse': n_ct_all * he['t_fuse_ct_s']}


def pct(a, q):
    return float(np.percentile(a, q))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--train-s', type=float, default=None, help='thời gian thô 1 epoch 1 client (classifier)')
    ap.add_argument('--out', default='outputs/uav_channel')
    a = ap.parse_args()
    cfg = yaml.safe_load(open(SRC / 'uav_channel' / 'config.yaml', encoding='utf-8'))
    he = yaml.safe_load(open(SRC / 'secure_fl' / 'config.yaml', encoding='utf-8'))['he']
    lock = cfg['analysis']
    fid = float(lock['fidelity'])
    N = int(lock['channel_rounds'])
    out = {'channel_rounds': N, 'fidelity': fid, 't_max_s': lock['t_max_s'], 'train_s_raw': a.train_s, 'rows': []}
    be = make_backend('emulated', he)
    for mode in ('uav_noma_pc', 'direct_noma'):
        c = copy.deepcopy(cfg)
        c['channel']['mode'] = mode
        ch = ChannelModel.from_config(c)
        rates = np.array([ch.round(t).rate_bytes_per_s for t in range(N)])        # byte/s, N × 2
        for model, info in MODELS.items():
            M = info['M']
            order = priority_order(info['blocks']) if info['blocks'] else np.arange(M)
            for sname, kind, kw in SCHEMES:
                sch = make_scheme(kind, M, he=be, order=order, **kw)
                sz = sch.sizes()
                n_ct = sz['n_ct']
                ct = comp_times(kind, None, n_ct, he, fid)
                t_up = (sz['upload'] / rates).max(axis=1)
                t_dec = (sz['share'] / rates).max(axis=1)
                t_train = (a.train_s * fid) if (a.train_s and model == 'classifier') else 0.0
                t_comp = t_train + ct['enc'] + ct['add'] + ct['pdec'] + ct['fuse']
                t_round = t_comp + t_up + t_dec
                row = {'channel': mode, 'model': model, 'scheme': sname, 'M': M, 'n_ct': n_ct,
                       'upload_B': sz['upload'], 'share_B': sz['share'], 'up_total_B': sz['upload'] + sz['share'],
                       'expansion_vs_plain': (sz['upload'] + sz['share']) / (4 * M),
                       't_compute_s': t_comp, 't_train_incl': bool(t_train),
                       'tx_p50': pct(t_up + t_dec, 50), 'tx_p90': pct(t_up + t_dec, 90), 'tx_p99': pct(t_up + t_dec, 99),
                       'tx_mean': float((t_up + t_dec).mean()),
                       'round_p50': pct(t_round, 50), 'round_p90': pct(t_round, 90), 'round_p99': pct(t_round, 99),
                       'round_mean': float(t_round.mean()),
                       'late': {str(tm): float((t_round > tm).mean()) for tm in lock['t_max_sweep_s']}}
                out['rows'].append(row)
    rate_stats = {}
    for mode in ('uav_noma_pc', 'direct_noma'):
        c = copy.deepcopy(cfg)
        c['channel']['mode'] = mode
        ch = ChannelModel.from_config(c)
        r = np.array([ch.round(t).rate_bps for t in range(N)])
        mn = r.min(axis=1)
        rate_stats[mode] = {'min_rate_bps_p10': pct(mn, 10), 'p50': pct(mn, 50), 'mean': float(mn.mean())}
    out['rate_stats'] = rate_stats
    path = ROOT / a.out
    path.mkdir(parents=True, exist_ok=True)
    with open(path / 'cost_time.json', 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(json.dumps(rate_stats, indent=1))
    for r in out['rows']:
        print(f"{r['channel']:<12}{r['model']:<17}{r['scheme']:<10} ct {r['n_ct']:>3}  lên {r['up_total_B']:>9,} B "
              f"({r['expansion_vs_plain']:>5.1f}x)  tx p50 {r['tx_p50']:>9.2f}s p99 {r['tx_p99']:>10.1f}s  "
              f"trễ@{lock['t_max_s']}s {r['late'].get(str(lock['t_max_s']), float('nan')):.2f}")


if __name__ == '__main__':
    main()
