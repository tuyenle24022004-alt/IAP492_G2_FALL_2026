import threading
import time

TIME_MODES = ('real', 'virtual', 'auto')


def use_virtual_time(cfg, rate1, rate2):
    mode = str(cfg.get('time_mode', 'real')).lower()
    if mode not in TIME_MODES:
        raise ValueError(f'time_mode phải thuộc {TIME_MODES}, nhận {mode}')
    if mode == 'virtual':
        return True
    if mode == 'auto':
        floor = float(cfg.get('virtual_below_bps', 1e6)) / 8.0
        return min(rate1, rate2) < floor
    return False


class MessagePacer:
    def __init__(self, rate=None):
        self.lock = threading.Lock()
        self.rate = None
        self.virtual = False
        self.set_rate(rate)

    def set_rate(self, rate, virtual=False):
        with self.lock:
            self.rate = None if rate is None else float(rate)
            self.virtual = bool(virtual)

    def snapshot(self):
        with self.lock:
            return self.rate, self.virtual

    def wait(self, t0, sent, rate, virtual):
        if rate is None or virtual:
            return
        delay = t0 + sent / rate - time.monotonic()
        if delay > 0:
            time.sleep(delay)
