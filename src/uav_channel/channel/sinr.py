import numpy as np

from .links import (a2g_path_loss_db, dbm_to_w, fspl_db, ground_path_loss_db, horizontal_distance, los_probability,
                    noise_power_w, rayleigh_power, rician_power)

POWER_CONTROL_GRID = np.logspace(-3, 0, 61)


def _random_los_link(p, rng, horizontal, height_diff, size):
    distance = np.sqrt(horizontal ** 2 + height_diff ** 2)
    elevation = np.degrees(np.arctan2(height_diff, horizontal))
    plos = los_probability(p, elevation)
    is_los = rng.random(size) < plos
    loss_db = fspl_db(p, distance) + np.where(is_los, p.eta_los_db, p.eta_nlos_db)
    fading = np.where(is_los, rician_power(rng, p.rician_k_db, size), rayleigh_power(rng, size))
    return 10 ** (-loss_db / 10) * fading


def _uav_noma(a, beta, noise):
    strong = a.argmax(1)
    sinr = np.zeros(a.shape)
    for k in range(2):
        own, other = a[:, k:k + 1], a[:, 1 - k:2 - k]
        decoded_first = (strong == k)[:, None]
        interference = np.where(decoded_first, beta * other, 0.0)
        sinr[:, k:k + 1] = beta * own / (interference + beta * noise + noise)
    return sinr


def _uav_noma_power_control(a, p_uav, loss_uav_bs, fading_uav_bs, noise):
    n = a.shape[0]
    strong = a.argmax(1)
    best = np.zeros((n, 2))
    best_min = np.full(n, -1.0)
    for alpha in POWER_CONTROL_GRID:
        scaled = a.copy()
        scaled[np.arange(n), strong] *= alpha
        gain = p_uav / (scaled.sum(1, keepdims=True) + noise)
        beta = (gain * loss_uav_bs * fading_uav_bs)[:, 0]
        for first in (0, 1):
            second = 1 - first
            sinr_first = beta * scaled[:, first] / (beta * scaled[:, second] + beta * noise + noise)
            sinr_second = beta * scaled[:, second] / (beta * noise + noise)
            cand = np.zeros((n, 2))
            cand[:, first] = sinr_first
            cand[:, second] = sinr_second
            worst = cand.min(1)
            better = worst > best_min
            best[better] = cand[better]
            best_min[better] = worst[better]
    return best


def _direct_noma(c, noise):
    strong = c.argmax(1)
    sinr = np.zeros(c.shape)
    for k in range(2):
        decoded_first = strong == k
        sinr[:, k] = c[:, k] / (np.where(decoded_first, c[:, 1 - k], 0.0) + noise)
    return sinr


def draw_sinr(p, rng, mode, n=1):
    devices = np.asarray(p.devices, float)
    bs = np.asarray(p.bs, float)
    uav = np.asarray(p.uav, float)
    noise = noise_power_w(p)
    p_dev = dbm_to_w(p.p_device_dbm)
    p_uav = dbm_to_w(p.p_uav_dbm)

    loss_dev_uav = np.array([10 ** (-a2g_path_loss_db(p, horizontal_distance(d, uav), p.h_uav - p.h_device) / 10)
                             for d in devices])
    loss_uav_bs = 10 ** (-a2g_path_loss_db(p, horizontal_distance(uav, bs), p.h_uav - p.h_bs) / 10)
    loss_dev_bs = np.array([10 ** (-ground_path_loss_db(p, horizontal_distance(d, bs)) / 10) for d in devices])

    fading_dev_uav = rician_power(rng, p.rician_k_db, (n, 2))
    fading_uav_bs = rician_power(rng, p.rician_k_db, (n, 1))
    if p.los_mode == 'random':
        fading_dev_uav = np.stack([
            _random_los_link(p, rng, horizontal_distance(d, uav), p.h_uav - p.h_device, n) for d in devices], 1)
        fading_uav_bs = _random_los_link(p, rng, horizontal_distance(uav, bs), p.h_uav - p.h_bs, n)[:, None]
        loss_dev_uav = np.ones(2)
        loss_uav_bs = 1.0
    fading_dev_bs = rayleigh_power(rng, (n, 2)) * 10 ** (rng.normal(0, p.shadow_db, (n, 2)) / 10)

    if mode == 'direct_noma':
        return _direct_noma(p_dev * loss_dev_bs * fading_dev_bs, noise)

    a = p_dev * loss_dev_uav * fading_dev_uav
    if mode == 'uav_noma':
        gain = p_uav / (a.sum(1, keepdims=True) + noise)
        return _uav_noma(a, gain * loss_uav_bs * fading_uav_bs, noise)
    if mode == 'uav_noma_pc':
        return _uav_noma_power_control(a, p_uav, loss_uav_bs, fading_uav_bs, noise)
    raise ValueError(f'chế độ kênh không hợp lệ: {mode}')
