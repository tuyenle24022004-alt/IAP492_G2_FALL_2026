import json
import os
import sys
from pathlib import Path

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))

from uav_channel.channel import ChannelModel, ChannelParams, MODES
from uav_channel.channel.sinr import draw_sinr

TOL = 1e-9


def load_root_config():
    with open(ROOT / 'tests' / 'uav_channel' / 'ref' / 'channel_ref_config.yaml', encoding='utf-8') as f:
        return yaml.safe_load(f)


def check_against_reference(config):
    ref = json.load(open(ROOT / 'tests' / 'uav_channel' / 'ref' / 'channel_ref.json', encoding='utf-8'))
    worst, count = 0.0, 0
    for key, rows in ref['gamma'].items():
        los_mode, mode = key.split('/')
        if mode not in MODES:
            continue
        cfg = dict(config, channel=dict(config['channel'], los_mode=los_mode))
        params = ChannelParams.from_config(cfg)
        for t, want in zip(ref['rounds'], rows):
            got = draw_sinr(params, np.random.default_rng([ref['seed'], t]), mode, 1)[0]
            rel = float(np.max(np.abs(got - np.asarray(want)) / np.abs(want)))
            worst = max(worst, rel)
            count += 1
            assert rel < TOL, f'{key} vòng {t}: {got} khác tham chiếu {want}'
    print(f'[TEST] A. SINR trùng tham chiếu: {count} trường hợp, sai khác tương đối tối đa {worst:.1e}')


def check_properties(config):
    cfg_uav = dict(config, channel=dict(config['channel'], mode='uav_noma_pc'))
    cfg_dir = dict(config, channel=dict(config['channel'], mode='direct_noma'))
    uav = ChannelModel.from_config(cfg_uav)
    direct = ChannelModel.from_config(cfg_dir)
    assert uav.round(3) == uav.round(3), 'cùng vòng phải cho cùng kênh'
    assert uav.round(3).sinr != uav.round(4).sinr, 'khác vòng phải cho kênh khác'
    r_uav = np.mean([min(uav.round(t).rate_bps) for t in range(1, 101)])
    r_dir = np.mean([min(direct.round(t).rate_bps) for t in range(1, 101)])
    assert r_uav > 3 * r_dir, f'UAV phải nhanh hơn rõ rệt: {r_uav:.0f} so với {r_dir:.0f}'
    budget = uav.link_budget()
    assert budget['device1_uav_loss_db'] < budget['device1_bs_loss_db'], 'liên kết UAV phải ít suy hao hơn liên kết trực tiếp'
    print(f'[TEST] C. Tính chất: tái lập theo vòng; tốc độ trung bình thấp nhất của hai thiết bị (100 vòng): '
          f'có UAV {r_uav / 1e6:.2f} Mbit/s, không UAV {r_dir / 1e6:.3f} Mbit/s')
    for k, v in budget.items():
        print(f'        {k}: {v:.1f}')


if __name__ == '__main__':
    cfg = load_root_config()
    check_against_reference(cfg)
    check_properties(cfg)
    print('[TEST] channel: ĐẠT')
