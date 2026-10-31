from dataclasses import dataclass

import numpy as np

from .links import a2g_path_loss_db, ground_path_loss_db, horizontal_distance
from .params import ChannelParams, MODES
from .sinr import draw_sinr


@dataclass(frozen=True)
class RoundChannel:
    t: int
    mode: str
    sinr: tuple
    rate_bps: tuple

    @property
    def sinr_db(self):
        return tuple(float(10 * np.log10(s)) for s in self.sinr)

    @property
    def rate_bytes_per_s(self):
        return tuple(r / 8.0 for r in self.rate_bps)


class ChannelModel:
    def __init__(self, params, mode='uav_noma_pc', seed=0):
        if mode not in MODES:
            raise ValueError(f'chế độ kênh phải thuộc {MODES}, nhận {mode}')
        self.params = params
        self.mode = mode
        self.seed = int(seed)

    @classmethod
    def from_config(cls, cfg, seed=None):
        c = cfg['channel'] if 'channel' in cfg else cfg
        return cls(ChannelParams.from_config(cfg), c.get('mode', 'uav_noma_pc'),
                   cfg.get('seed', 0) if seed is None else seed)

    @property
    def uses_uav(self):
        return self.mode.startswith('uav')

    def round(self, t):
        rng = np.random.default_rng([self.seed, int(t)])
        sinr = draw_sinr(self.params, rng, self.mode, 1)[0]
        factor = 0.5 if self.uses_uav else 1.0
        rate = self.params.bandwidth_hz * factor * np.log2(1 + sinr)
        return RoundChannel(int(t), self.mode, tuple(float(s) for s in sinr), tuple(float(r) for r in rate))

    def link_budget(self):
        p = self.params
        out = {}
        for i, dev in enumerate(p.devices, 1):
            out[f'device{i}_uav_m'] = horizontal_distance(dev, p.uav)
            out[f'device{i}_uav_loss_db'] = float(a2g_path_loss_db(p, horizontal_distance(dev, p.uav), p.h_uav - p.h_device))
            out[f'device{i}_bs_m'] = horizontal_distance(dev, p.bs)
            out[f'device{i}_bs_loss_db'] = float(ground_path_loss_db(p, horizontal_distance(dev, p.bs)))
        out['uav_bs_m'] = horizontal_distance(p.uav, p.bs)
        out['uav_bs_loss_db'] = float(a2g_path_loss_db(p, horizontal_distance(p.uav, p.bs), p.h_uav - p.h_bs))
        return out
