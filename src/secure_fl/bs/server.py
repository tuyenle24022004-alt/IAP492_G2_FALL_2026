"""Trạm gốc (BS): điều phối vòng, thu UPLOAD của 2 client, CỘNG, ghép phần giải mã, phát AGGREGATE, ghi log.

BS KHÔNG có mô hình, KHÔNG có khóa bí mật HE, KHÔNG có khóa xáo K (trừ arm fasbs_* mô phỏng FAS gốc, khi đó --k-file được cấp).
Mỗi vòng ghi byte THẬT của từng tin nhắn và thời gian từng pha; lưu nguyên phần rõ BS nhận được vào capture/ để phân tích tấn công
ngoại tuyến. Chạy: python src/secure_fl/bs/server.py --arm fas_lam1 --port 7100 --out <thư mục>
"""
import argparse
import json
import socket
import sys
import threading
import time
from pathlib import Path

import numpy as np
import yaml

SRC = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SRC))

from secure_fl import settings                                                   # noqa: E402
from secure_fl.arms import bs_has_key, resolve                                   # noqa: E402
from secure_fl.common import messages as Msg                                     # noqa: E402
from secure_fl.security import make_backend, make_scheme                         # noqa: E402
from secure_fl.security.base import from_wire, to_wire                           # noqa: E402


def recv_parallel(conns, expect):
    """Đọc 1 tin nhắn từ mỗi kết nối cùng lúc; trả {dev: (msg, nbytes, giờ_nhận)}."""
    out, errs = {}, []

    def work(dev, sock):
        try:
            msg, n = Msg.recv_msg(sock)
            assert msg['type'] == expect, f'cần {expect}, nhận {msg["type"]}'
            out[dev] = (msg, n, time.monotonic())
        except Exception as e:                                                      # noqa: BLE001
            errs.append(f'thiết bị {dev}: {e!r}')

    ts = [threading.Thread(target=work, args=(d, s)) for d, s in conns.items()]
    [t.start() for t in ts]
    [t.join() for t in ts]
    if errs:
        raise RuntimeError('; '.join(errs))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--arm', required=True)
    ap.add_argument('--port', type=int, required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--seed', type=int, default=0)
    ap.add_argument('--rounds', type=int, required=True, help='số vòng FL (config model fl.rounds); thêm vòng 0 tổng hợp đầu')
    ap.add_argument('--k-file', help='CHỈ cấp cho arm fasbs_* (BS giữ khóa xáo)')
    ap.add_argument('--bind', help='địa chỉ lắng nghe (mặc định lock.host; trong container dùng 0.0.0.0)')
    a = ap.parse_args()
    cfg = settings.load()
    lock = cfg['lock']
    rounds = a.rounds
    kind, kw = resolve(a.arm, lock)
    if a.k_file and not bs_has_key(a.arm, lock):
        raise SystemExit(f'arm {a.arm} không được cấp khóa xáo cho BS')
    if bs_has_key(a.arm, lock) and not a.k_file:
        raise SystemExit(f'arm {a.arm} cần --k-file (BS giữ K)')
    out = Path(a.out)
    (out / 'capture').mkdir(parents=True, exist_ok=True)
    if a.k_file:
        kw = dict(kw, K=Path(a.k_file).read_bytes())

    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((a.bind or lock['host'], a.port))
    srv.listen(2)
    srv.settimeout(float(lock['timeout_s']))
    conns, n_k, M = {}, {}, None
    for _ in range(2):
        c, _addr = srv.accept()
        c.settimeout(float(lock['timeout_s']))
        msg, _ = Msg.recv_msg(c)
        assert msg['type'] == Msg.HELLO
        conns[int(msg['dev'])], n_k[int(msg['dev'])] = c, int(msg['n_k'])
        M = int(msg['M'])
    devs = sorted(conns)
    w = {d: n_k[d] / sum(n_k.values()) for d in devs}
    he = make_backend(lock['backend'], cfg['he'], seed=a.seed * 10 + 9, role='bs')
    he.setup_bs(conns)                                                    # OpenFHE: tạo context, chuyển tiếp khóa công khai; emulated: không làm gì
    scheme = make_scheme(kind, M, he=he, **kw)

    log = {'arm': a.arm, 'kind': kind, 'M': M, 'n_k': n_k, 'backend': lock['backend'], 'sizes': scheme.sizes(), 'rounds': []}
    for t in range(0, rounds + 1):                                        # vòng 0 = tổng hợp trọng số huấn luyện cục bộ
        row = {'t': t, 'bytes': {}, 'phase_s': {}}
        t0 = time.monotonic()
        row['bytes']['ROUND_START'] = {d: Msg.send_msg(conns[d], Msg.ROUND_START, {'t': t, 'w': w[d]}) for d in devs}
        got = recv_parallel(conns, Msg.UPLOAD)
        t_up = time.monotonic()
        row['bytes']['UPLOAD'] = {d: got[d][1] for d in devs}
        row['phase_s']['wait_upload'] = t_up - t0
        row['phase_s']['upload_spread'] = max(g[2] for g in got.values()) - min(g[2] for g in got.values())
        payloads = [from_wire(got[d][0]['payload'], he) for d in devs]
        for d, p in zip(devs, payloads):                                  # capture: đúng thứ BS nhận được
            if p.get('plain') is not None:
                np.save(out / 'capture' / f'round{t}_dev{d}_plain.npy', p['plain'])
        a0 = time.monotonic()
        csum = scheme.aggregate(payloads)
        row['phase_s']['aggregate'] = time.monotonic() - a0
        shares = []
        if scheme.needs_decrypt:
            row['bytes']['CSUM'] = {d: Msg.send_msg(conns[d], Msg.CSUM, {'t': t, 'csum': to_wire(csum, he)}) for d in devs}
            c0 = time.monotonic()
            got2 = recv_parallel(conns, Msg.PARTIAL_DEC)
            row['phase_s']['wait_partial_dec'] = time.monotonic() - c0
            row['bytes']['PARTIAL_DEC'] = {d: got2[d][1] for d in devs}
            shares = [from_wire(got2[d][0]['share'], he) for d in devs if got2[d][0]['share'] is not None]
        f0 = time.monotonic()
        agg = scheme.bs_fuse(csum, shares)
        row['phase_s']['fuse'] = time.monotonic() - f0
        row['bytes']['AGGREGATE'] = {d: Msg.send_msg(conns[d], Msg.AGGREGATE, {'t': t, 'agg': to_wire(agg, he)}) for d in devs}
        m0 = time.monotonic()
        met, nb = Msg.recv_msg(conns[1])
        assert met['type'] == Msg.METRICS
        row['phase_s']['wait_metrics'] = time.monotonic() - m0
        row['bytes']['METRICS'] = {1: nb}
        row['metrics'] = {k: v for k, v in met.items() if k != 'type'}
        row['phase_s']['round'] = time.monotonic() - t0
        log['rounds'].append(row)
        print(f'[bs {a.arm}] vòng {t:2d}  acc {met.get("acc", float("nan")):.4f}  {row["phase_s"]["round"]:.1f}s', flush=True)
    for c in conns.values():
        c.close()
    with open(out / 'bs_log.json', 'w', encoding='utf-8') as f:
        json.dump(log, f, ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
