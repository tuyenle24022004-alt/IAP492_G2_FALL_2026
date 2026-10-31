import socket
import threading
import time

from secure_fl.common import framing, messages


class UplinkStats:
    def __init__(self):
        self.lock = threading.Lock()
        self.items = []

    def add(self, mtype, nbytes, tx_s, wall_s, virtual):
        with self.lock:
            self.items.append({'type': mtype, 'bytes': nbytes, 'tx_s': tx_s, 'wall_s': wall_s, 'virtual': virtual})

    def take(self):
        with self.lock:
            items, self.items = self.items, []
        return items


def _close(*socks):
    for s in socks:
        try:
            s.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass


def pump(src, dst, pacer, stats, stop, chunk):
    try:
        while not stop.is_set():
            header, n = framing.read_header(src)
            first = framing.recv_exactly(src, min(n, chunk))
            if pacer is None:
                dst.sendall(header + first + framing.recv_exactly(src, n - len(first)))
                continue
            mtype = messages.peek_type(first)
            rate, virtual = pacer.snapshot()
            t0 = time.monotonic()
            done = len(first)
            piece = header + first
            sent = 0
            while True:
                sent += len(piece)
                pacer.wait(t0, sent, rate, virtual)
                if done >= n:
                    wall = time.monotonic() - t0
                    frame = framing.HEADER.size + n
                    tx = frame / rate if (virtual and rate) else wall
                    stats.add(mtype, frame, tx, wall, bool(virtual and rate))
                    dst.sendall(piece)
                    break
                dst.sendall(piece)
                piece = framing.recv_exactly(src, min(chunk, n - done))
                done += len(piece)
    except (ConnectionError, OSError):
        pass
    finally:
        stop.set()
        _close(src, dst)


class DevicePipe:
    def __init__(self, device_sock, bs_sock, pacer, stats, stop, chunk):
        self.pacer = pacer
        self.stats = stats
        self.threads = [
            threading.Thread(target=pump, args=(device_sock, bs_sock, pacer, stats, stop, chunk), daemon=True),
            threading.Thread(target=pump, args=(bs_sock, device_sock, None, None, stop, chunk), daemon=True),
        ]

    def start(self):
        for t in self.threads:
            t.start()
