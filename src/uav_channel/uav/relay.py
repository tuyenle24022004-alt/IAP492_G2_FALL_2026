import socket
import threading
import time

from secure_fl.common import messages as M
from uav_channel.uav.pipe import DevicePipe, UplinkStats
from uav_channel.uav.shaper import MessagePacer, use_virtual_time


def connect(host, port, timeout=30.0):
    t0 = time.monotonic()
    while True:
        try:
            s = socket.create_connection((host, port), timeout=5.0)
            s.settimeout(None)
            s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            return s
        except OSError:
            if time.monotonic() - t0 > timeout:
                raise
            time.sleep(0.1)


def accept_one(listen_host, port):
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((listen_host, port))
    server.listen(1)
    sock, _ = server.accept()
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    server.close()
    return sock


class UavRelay:
    def __init__(self, bs_host, bs_port, listen_host, device_ports, channel, uav_cfg=None, link_budget=None):
        self.bs_host = bs_host
        self.bs_port = bs_port
        self.listen_host = listen_host
        self.device_ports = list(device_ports)
        self.channel = channel
        self.cfg = uav_cfg or {}
        self.chunk = int(self.cfg.get('shaper_chunk', 16384))
        self.link_budget = link_budget or {}
        self.pacers = {}
        self.stats = {}
        self.stop = threading.Event()
        self.control = None

    def open(self):
        self.control = connect(self.bs_host, self.bs_port)
        M.send_msg(self.control, M.HELLO, {'role': 'uav', 'mode': self.channel.mode, 'link_budget': self.link_budget})
        for k, port in enumerate(self.device_ports, start=1):
            device_sock = accept_one(self.listen_host, port)
            bs_sock = connect(self.bs_host, self.bs_port)
            self.pacers[k] = MessagePacer(rate=None)
            self.stats[k] = UplinkStats()
            DevicePipe(device_sock, bs_sock, self.pacers[k], self.stats[k], self.stop, self.chunk).start()

    def run_round(self, t):
        rc = self.channel.round(t)
        r1, r2 = rc.rate_bytes_per_s
        for k in self.stats:
            self.stats[k].take()
        virtual = use_virtual_time(self.cfg, r1, r2)
        self.pacers[1].set_rate(r1, virtual)
        self.pacers[2].set_rate(r2, virtual)
        M.send_msg(self.control, M.CHANNEL_REPORT, {
            't': t, 'mode': rc.mode, 'sinr': list(rc.sinr), 'sinr_db': list(rc.sinr_db),
            'rate_bps': list(rc.rate_bps), 'rate_bytes_per_s': [r1, r2], 'virtual_time': virtual})
        msg, _ = M.recv_msg(self.control)
        if msg.get('type') != M.ROUND_DONE:
            raise RuntimeError(f'uav mong ROUND_DONE, nhận {msg.get("type")}')
        M.send_msg(self.control, M.UAV_STATS, {'t': t, 'dev1': self.stats[1].take(), 'dev2': self.stats[2].take()})
        return rc

    def run(self, rounds, log=print):
        self.open()
        try:
            for t in range(1, int(rounds) + 1):
                rc = self.run_round(t)
                log(f'[uav] vòng {t} xong: R1 {rc.rate_bps[0] / 1e6:.4f} R2 {rc.rate_bps[1] / 1e6:.4f} Mbit/s')
        finally:
            self.close()

    def close(self):
        self.stop.set()
        try:
            self.control.close()
        except (OSError, AttributeError):
            pass
