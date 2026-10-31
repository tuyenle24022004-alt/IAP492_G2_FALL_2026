import numpy as np

LIGHT_SPEED = 3e8


def dbm_to_w(x):
    return 10 ** ((x - 30) / 10)


def noise_power_w(p):
    return dbm_to_w(-174 + 10 * np.log10(p.bandwidth_hz) + p.noise_figure_db)


def fspl_db(p, distance):
    return 20 * np.log10(4 * np.pi * p.carrier_hz * distance / LIGHT_SPEED)


def los_probability(p, elevation_deg):
    return 1 / (1 + p.a2g_a * np.exp(-p.a2g_b * (elevation_deg - p.a2g_a)))


def a2g_path_loss_db(p, horizontal, height_diff):
    distance = np.sqrt(horizontal ** 2 + height_diff ** 2)
    elevation = np.degrees(np.arctan2(height_diff, horizontal))
    plos = los_probability(p, elevation)
    return fspl_db(p, distance) + p.eta_los_db * plos + p.eta_nlos_db * (1 - plos)


def ground_path_loss_db(p, horizontal):
    d3 = np.sqrt(horizontal ** 2 + (p.h_bs - p.h_device) ** 2)
    return 13.54 + 39.08 * np.log10(d3) + 20 * np.log10(p.carrier_hz / 1e9) - 0.6 * (p.h_device - 1.5)


def rician_power(rng, k_db, size):
    k = 10 ** (k_db / 10)
    los = np.sqrt(k / (k + 1))
    scatter = np.sqrt(1 / (2 * (k + 1)))
    h = los + scatter * (rng.standard_normal(size) + 1j * rng.standard_normal(size))
    return np.abs(h) ** 2


def rayleigh_power(rng, size):
    return rng.exponential(1.0, size)


def horizontal_distance(a, b):
    return float(np.linalg.norm(np.asarray(a, float) - np.asarray(b, float)))
