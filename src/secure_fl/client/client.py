"""Thiết bị biên (client): bảo vệ TRỌNG SỐ mô hình, nói chuyện với BS, giải mã/giải xáo tổng, cập nhật mô hình.

Luồng (CLAUDE.md mục 4):
  vòng 0 : nạp trọng số đã huấn luyện cục bộ 150 epoch (outputs/model/<client>/run/weights.npy) -> bảo vệ -> BS cộng có trọng số
           n_k/n -> giải mã -> mô hình toàn cục ban đầu (= "trung bình 1 lần", nhưng qua mã hóa)
  vòng t = 1..R : huấn luyện fl.local_epochs (=1) epoch từ mô hình toàn cục -> trọng số -> bảo vệ -> BS cộng -> giải mã -> mô hình mới
Cái được bảo vệ và gửi lên BS là x_k = (n_k/n) · trọng số_k, nên tổng chính là FedAvg. Mỗi tiến trình CHỈ đọc dữ liệu của mình;
client1 đánh giá trên tập test mỗi vòng. Ghi ra --out: truth/ (trọng số cục bộ thật mỗi vòng, CHỈ để phân tích tấn công ngoại
tuyến, không bao giờ gửi đi), client<dev>_log.json, g_client<dev>.npy (mô hình toàn cục từng vòng), pred_client1.npy.
Chạy: python src/secure_fl/client/client.py --dev 1 --arm fas_lam0.1 --port 7100 --rounds 50 --out <thư mục> [--k-file <perm_seed>]
"""
import argparse
import copy
import json
import socket
import sys
import time
from pathlib import Path

import numpy as np
import torch
import yaml

SRC = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(SRC / 'model'))         # `common` = src/model/common

from common import data, define_model as dm, finetune as ft                      # noqa: E402
from common.evaluate import evaluate                                             # noqa: E402
from common.fedavg import get_vec, local_update, set_vec, trainable_params       # noqa: E402
from common.paths import client_paths, load_config                               # noqa: E402
from secure_fl import devicelimit, settings                                      # noqa: E402
from secure_fl.arms import resolve                                               # noqa: E402
from secure_fl.common import messages as Msg                                     # noqa: E402
from secure_fl.security import make_backend, make_scheme, priority_order         # noqa: E402
from secure_fl.security.base import from_wire, to_wire                           # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dev', type=int, required=True, choices=[1, 2])
    ap.add_argument('--arm', required=True)
    ap.add_argument('--port', type=int, required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--rounds', type=int, required=True, help='số vòng FL (lấy từ config model fl.rounds)')
    ap.add_argument('--seed', type=int, default=42)
    ap.add_argument('--model', default='classifier')
    ap.add_argument('--k-file', help='khóa xáo K (32 byte) — chỉ thiết bị (và BS ở arm fasbs_*) có file này')
    ap.add_argument('--host', help='địa chỉ BS (mặc định lock.host; trong container là `bs`)')
    a = ap.parse_args()
    scfg = settings.load()
    lock = scfg['lock']
    rounds = a.rounds
    dev, party = a.dev, a.dev - 1
    me = f'client{dev}'
    out = Path(a.out)
    devicelimit.enforce(me, out_dir=out)                                # bắt buộc: client chỉ chạy trong giả lập Pi 4 (Windows: Job Object; Docker: do compose áp)
    (out / 'truth').mkdir(parents=True, exist_ok=True)

    cfg = copy.deepcopy(load_config())
    cfg['seed'] = a.seed
    cfg['model']['trainable'] = a.model
    cfg['feature_root'] = cfg['output_root']
    classes = cfg['classes']
    local_epochs = int(cfg['fl']['local_epochs'])
    torch.manual_seed(a.seed)
    torch.set_num_threads(int(cfg['threads']))
    X, y = data.load_client_features(me, cfg, splits=('train',))['train']
    Xte = yte = None
    if dev == 1:
        Xte, yte = data.load_client_features(me, cfg, splits=('test',))['test']
    net, _ = ft.prepare_model(cfg)
    _, head = dm.split_model(net, ft.feature_cut(a.model))
    M = get_vec(head).size
    order = priority_order([p.numel() for p in trainable_params(head)])
    wpath = client_paths(me, cfg)['out'] / 'run' / 'weights.npy'
    if not wpath.exists():
        raise SystemExit(f'chưa có trọng số huấn luyện cục bộ {wpath} (chạy src/model/{me}/train.py)')
    w_local0 = np.load(wpath).astype(np.float64)
    assert w_local0.size == M, f'{wpath} có {w_local0.size} số, mô hình cần {M}'

    kind, kw = resolve(a.arm, lock)
    if kind == 'fas':
        kw = dict(kw, K=Path(a.k_file).read_bytes(), order=order)
    he = make_backend(lock['backend'], scfg['he'], seed=a.seed * 10 + dev, role='client', dev=dev)
    scheme = make_scheme(kind, M, he=he, **kw)

    sock = socket.socket()
    deadline = time.monotonic() + 60
    while True:                                                         # BS có thể chưa kịp lắng nghe
        try:
            sock.connect((a.host or lock['host'], a.port))
            break
        except OSError:
            if time.monotonic() > deadline:
                raise
            time.sleep(0.2)
    sock.settimeout(float(lock['timeout_s']))
    Msg.send_msg(sock, Msg.HELLO, {'dev': dev, 'n_k': int(len(y)), 'M': int(M)})
    he.setup_client(sock, dev)                                          # OpenFHE: dựng context, sinh khóa đa bên; emulated: không làm gì

    g = None                                                            # mô hình toàn cục; chưa có trước vòng 0
    gs, log, pred = [], [], None
    for t in range(0, rounds + 1):
        row = {'t': t}
        a0 = time.perf_counter()
        msg, _ = Msg.recv_msg(sock)
        assert msg['type'] == Msg.ROUND_START and msg['t'] == t
        w = float(msg['w'])
        row['wait_round_start_s'] = time.perf_counter() - a0

        if t == 0:                                                      # tổng hợp đầu: trọng số huấn luyện cục bộ 150 epoch
            v, row['train_s'] = w_local0, 0.0
        else:
            a0 = time.perf_counter()
            v, _, _ = local_update(head, g, X, y, cfg, local_epochs, a.seed * 1000 + t * 10 + party)
            row['train_s'] = time.perf_counter() - a0
        x = w * v

        rng = np.random.default_rng([a.seed, 1000 + party, t]) if lock['noise_entropy'] == 'seeded' else np.random.default_rng()
        a0 = time.perf_counter()
        payload = scheme.protect(x, t, party, rng)
        wire = to_wire(payload, he)
        row['protect_s'] = time.perf_counter() - a0
        row['noise_sd'] = scheme.info.get('sd', 0.0)
        Msg.send_msg(sock, Msg.UPLOAD, {'t': t, 'payload': wire})

        if scheme.needs_decrypt:
            a0 = time.perf_counter()
            msg, _ = Msg.recv_msg(sock)
            assert msg['type'] == Msg.CSUM
            row['wait_csum_s'] = time.perf_counter() - a0
            csum = from_wire(msg['csum'], he)
            a0 = time.perf_counter()
            share = scheme.client_share(csum, party)
            row['partial_dec_s'] = time.perf_counter() - a0
            Msg.send_msg(sock, Msg.PARTIAL_DEC, {'t': t, 'share': to_wire(share, he) if share is not None else None})
        else:
            row['wait_csum_s'] = 0.0

        a0 = time.perf_counter()
        msg, _ = Msg.recv_msg(sock)
        assert msg['type'] == Msg.AGGREGATE
        row['wait_aggregate_s'] = time.perf_counter() - a0
        a0 = time.perf_counter()
        g_prev = g
        g = scheme.client_finish(from_wire(msg['agg'], he), t)          # tổng có trọng số của trọng số = mô hình toàn cục mới
        set_vec(head, g)
        row['finish_s'] = time.perf_counter() - a0
        gs.append(g.copy())
        np.savez(out / 'truth' / f'{me}_round{t}.npz', local=v, g_prev=g_prev if g_prev is not None else np.zeros(M), gsum=g, w=w)

        if dev == 1:
            a0 = time.perf_counter()
            m = evaluate(head, Xte, yte, classes)
            row['eval_s'] = time.perf_counter() - a0
            met = {'acc': m['accuracy'], 'f1': m['macro_f1'], 'loss': m['loss']}
            met.update({f'recall_{k}': m['per_class'][k]['recall'] for k in classes})
            Msg.send_msg(sock, Msg.METRICS, {'t': t, **met})
            if t == rounds:
                pred = torch.argmax(head(torch.from_numpy(Xte.astype(np.float32))), dim=1).detach().numpy()
        log.append(row)
    np.save(out / f'g_{me}.npy', np.array(gs))
    if pred is not None:
        np.save(out / 'pred_client1.npy', pred)
    with open(out / f'{me}_log.json', 'w', encoding='utf-8') as f:
        json.dump({'dev': dev, 'arm': a.arm, 'n_k': int(len(y)), 'rounds': log}, f, ensure_ascii=False, indent=1)
    sock.close()


if __name__ == '__main__':
    main()
