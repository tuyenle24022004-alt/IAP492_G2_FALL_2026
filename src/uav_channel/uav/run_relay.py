"""Chạy ống kênh (UAV tự theo vòng): đứng giữa client và BS, giữ UPLOAD và PARTIAL_DEC đúng thời gian của kênh vô tuyến bằng đồng hồ thật.

Chạy (trong container `uav` của docker-compose.uav.yml hoặc trực tiếp):
    python src/uav_channel/uav/run_relay.py --channel uav_noma_pc --bs-host bs --out /out
    --channel: uav_noma_pc (có UAV) | direct_noma (không UAV). Cổng nghe, cổng BS, cỡ gói, loại tin giữ lấy từ `fl_qua_kenh` trong config.yaml.
Ghi vào --out: uav_stats.jsonl (từng mẫu kênh và từng tin) và uav_channel.json (tham số kênh, ngân sách đường truyền).
"""
import argparse
import dataclasses
import json
import sys
import time
from pathlib import Path

import yaml

SRC = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SRC))

from uav_channel.channel import ChannelModel, MODES                           # noqa: E402
from uav_channel.uav.auto_relay import AutoRelay                              # noqa: E402

CONFIG = SRC / 'uav_channel' / 'config.yaml'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--channel', required=True, choices=MODES)
    ap.add_argument('--out', required=True, help='thư mục ghi uav_stats.jsonl và uav_channel.json')
    ap.add_argument('--bs-host', default='127.0.0.1')
    ap.add_argument('--bs-port', type=int, help='mặc định: fl_qua_kenh.bs_port')
    ap.add_argument('--listen-host', default='0.0.0.0')
    ap.add_argument('--ports', type=int, nargs=2, help='mặc định: fl_qua_kenh.ports')
    ap.add_argument('--chunk', type=int, help='mặc định: fl_qua_kenh.chunk_bytes')
    ap.add_argument('--seed', type=int, help='mặc định: seed trong config.yaml')
    a = ap.parse_args()
    cfg = yaml.safe_load(open(CONFIG, encoding='utf-8'))
    flq = cfg['fl_qua_kenh']
    cfg['channel']['mode'] = a.channel
    if a.seed is not None:
        cfg['seed'] = a.seed
    model = ChannelModel.from_config(cfg)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / 'uav_channel.json').write_text(json.dumps(
        {'mode': a.channel, 'seed': model.seed, 'params': dataclasses.asdict(model.params), 'link_budget': model.link_budget(),
         'chunk_bytes': a.chunk or flq['chunk_bytes'], 'held_types': flq['held_types']}, ensure_ascii=False, indent=1), encoding='utf-8')
    ports = a.ports or flq['ports']
    relay = AutoRelay(model, a.bs_host, a.bs_port or flq['bs_port'], a.listen_host, ports, out / 'uav_stats.jsonl',
                      chunk=a.chunk or flq['chunk_bytes'], held=flq['held_types'])
    print(f'[ống] kênh {a.channel} (seed {model.seed}); nghe cổng {ports}, chuyển tiếp tới {a.bs_host}:{a.bs_port or flq["bs_port"]}; '
          f'giữ {flq["held_types"]} theo gói {a.chunk or flq["chunk_bytes"]} B; bắt đầu {time.strftime("%Y-%m-%d %H:%M:%S")}', flush=True)
    relay.run()
    print('[ống] kết thúc', flush=True)


if __name__ == '__main__':
    main()
