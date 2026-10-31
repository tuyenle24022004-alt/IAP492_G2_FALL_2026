from dataclasses import dataclass

MODES = ('uav_noma_pc', 'uav_noma', 'direct_noma')
LOS_MODES = ('mean', 'random')


@dataclass(frozen=True)
class ChannelParams:
    carrier_hz: float = 2e9
    bandwidth_hz: float = 1e6
    p_device_dbm: float = 23.0
    p_uav_dbm: float = 30.0
    noise_figure_db: float = 7.0
    h_bs: float = 25.0
    h_uav: float = 100.0
    h_device: float = 1.5
    bs: tuple = (0.0, 0.0)
    uav: tuple = (700.0, 0.0)
    devices: tuple = ((900.0, 0.0), (1200.0, 0.0))
    a2g_a: float = 9.61
    a2g_b: float = 0.16
    eta_los_db: float = 1.0
    eta_nlos_db: float = 20.0
    rician_k_db: float = 5.0
    shadow_db: float = 6.0
    los_mode: str = 'mean'

    def __post_init__(self):
        if self.los_mode not in LOS_MODES:
            raise ValueError(f'los_mode phải thuộc {LOS_MODES}, nhận {self.los_mode}')
        if len(self.devices) != 2:
            raise ValueError('kênh có đúng 2 thiết bị')

    @classmethod
    def from_config(cls, cfg):
        c = cfg['channel'] if 'channel' in cfg else cfg
        a2g = c.get('a2g', {})
        d = cls()
        return cls(
            carrier_hz=float(c.get('fc', d.carrier_hz)),
            bandwidth_hz=float(c.get('B', d.bandwidth_hz)),
            p_device_dbm=float(c.get('P_dev_dBm', d.p_device_dbm)),
            p_uav_dbm=float(c.get('P_uav_dBm', d.p_uav_dbm)),
            noise_figure_db=float(c.get('NF_dB', d.noise_figure_db)),
            h_bs=float(c.get('h_bs', d.h_bs)),
            h_uav=float(c.get('h_uav', d.h_uav)),
            h_device=float(c.get('h_dev', d.h_device)),
            bs=tuple(float(v) for v in c.get('bs', d.bs)),
            uav=tuple(float(v) for v in c.get('uav', d.uav)),
            devices=tuple(tuple(float(v) for v in dev) for dev in c.get('devices', d.devices)),
            a2g_a=float(a2g.get('a', d.a2g_a)),
            a2g_b=float(a2g.get('b', d.a2g_b)),
            eta_los_db=float(a2g.get('eta_los_dB', d.eta_los_db)),
            eta_nlos_db=float(a2g.get('eta_nlos_dB', d.eta_nlos_db)),
            rician_k_db=float(c.get('K_dB', d.rician_k_db)),
            shadow_db=float(c.get('shadow_dB', d.shadow_db)),
            los_mode=str(c.get('los_mode', d.los_mode)),
        )
