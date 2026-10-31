import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common import define_model as dm
from common.paths import load_config

CLIENT = 'client1'


def build(cfg=None):
    cfg = cfg or load_config()
    net = dm.build_squeezenet(1000)
    return dm.replace_head(net, len(cfg['classes']), cfg['seed'])


if __name__ == '__main__':
    cfg = load_config()
    net = build(cfg)
    trunk, head = dm.split_model(net)
    print(f'[{CLIENT}] số lớp phân loại: {len(cfg["classes"])} {cfg["classes"]}')
    print(f'[{CLIENT}] tổng tham số: {dm.count_params(net):,}')
    print(f'[{CLIENT}] thân (features[0:12]): {dm.count_params(trunk):,}')
    print(f'[{CLIENT}] đầu (fire9 + classifier): {dm.count_params(head):,}')
