"""Ống kênh TỰ THEO VÒNG: đứng giữa client và BS, giữ tin lại đúng thời gian của kênh vô tuyến bằng ĐỒNG HỒ THẬT.

Khác `relay.py`: không cần kết nối điều khiển tới BS (BS không phải sửa). Ống tự đọc loại tin và số vòng `t` ở đầu thân tin msgpack
(FL đã gửi sẵn `type` và `t`), hỏi `channel.round(t)` lấy tốc độ R_k của vòng đó rồi giữ tin.

Quy tắc (xem docs ý tưởng FL qua kênh):
- Mỗi thiết bị một đường và hai luồng riêng (thiết bị -> BS có giữ; BS -> thiết bị đi thẳng), nên hai thiết bị bị giữ SONG SONG.
- CHỈ giữ các loại tin trong `held` (mặc định UPLOAD, PARTIAL_DEC) theo chiều thiết bị -> BS. Mọi tin khác đi thẳng.
- Tin được chuyển tiếp theo từng gói `chunk` byte; gói thứ i chỉ được thả khi đồng hồ >= t0 + (byte đã gửi)/R. Mốc tính tuyệt đối từ t0 nên sai số
  ngủ không cộng dồn; gói nhỏ giữ cho BS luôn thấy dữ liệu đang chảy.
- Ống không đọc nội dung (chỉ đọc `type`, `t`), không có khóa.
Mỗi tin ghi một dòng JSON vào `stats_path` (uav_stats.jsonl): kind=channel (mẫu kênh của vòng t), kind=msg (tin bị giữ), kind=pass (tin đi thẳng).
"""
import json
import socket
import threading
import time
from pathlib import Path

import msgpack

from secure_fl.common import framing                  # chỉ ĐỌC khung tin (4 byte độ dài + thân), không sửa gì bên secure_fl

HELD_TYPES = ('UPLOAD', 'PARTIAL_DEC')


def peek_type_round(prefix):
    """Đọc (type, t) ở đầu thân msgpack chỉ từ phần đầu tin; (None, None) nếu không đọc được. t là None nếu tin không có trường t."""
    try:
        up = msgpack.Unpacker(raw=False)
        up.feed(prefix)
        out = {}
        for _ in range(up.read_map_header()):
            key = up.unpack()
            if key not in ('type', 't'):
                break                                 # gặp khóa khác (vd. payload lớn) thì dừng, không đọc giá trị của nó
            out[key] = up.unpack()
            if len(out) == 2:
                break
        return out.get('type'), out.get('t')
    except Exception:                                  # noqa: BLE001  phần đầu tin không đủ hoặc không phải msgpack
        return None, None


class StatsLog:
    """Ghi JSON Lines an toàn giữa nhiều luồng; ghi xuống đĩa ngay từng dòng (bị ngắt giữa chừng vẫn còn số liệu)."""

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.f = open(self.path, 'a', encoding='utf-8')
        self.lock = threading.Lock()

    def write(self, rec):
        with self.lock:
            self.f.write(json.dumps(rec, ensure_ascii=False) + '\n')
            self.f.flush()

    def close(self):
        with self.lock:
            self.f.close()


class RateProvider:
    """Tốc độ R_k(t) từ mô hình kênh; mỗi vòng t lấy MỘT mẫu kênh dùng chung cho mọi tin của vòng đó (kể cả UPLOAD và PARTIAL_DEC)."""

    def __init__(self, channel, stats):
        self.channel = channel
        self.stats = stats
        self.cache = {}
        self.lock = threading.Lock()

    def rate(self, dev, t):
        with self.lock:
            if t not in self.cache:
                rc = self.channel.round(t)
                self.cache[t] = rc
                self.stats.write({'kind': 'channel', 't': t, 'mode': rc.mode, 'sinr_db': list(rc.sinr_db),
                                  'rate_bps': list(rc.rate_bps), 'rate_Bps': list(rc.rate_bytes_per_s)})
            return float(self.cache[t].rate_bytes_per_s[dev - 1])


def pump_held(dev, src, dst, rates, stats, chunk, held):
    """Chiều thiết bị -> BS: đọc từng khung; tin thuộc `held` bị giữ theo R_k(t), tin khác đi thẳng. Trả khi kết nối đóng."""
    hdr = framing.HEADER.size
    try:
        while True:
            header, n = framing.read_header(src)
            first = framing.recv_exactly(src, min(n, chunk))
            mtype, t = peek_type_round(first)
            frame = hdr + n
            if mtype not in held:
                rest = framing.recv_exactly(src, n - len(first)) if n > len(first) else b''
                dst.sendall(header + first + rest)
                stats.write({'kind': 'pass', 'dev': dev, 'type': mtype, 'frame': frame})
                continue
            if t is None:
                raise RuntimeError(f'tin {mtype} của thiết bị {dev} không có số vòng t: ống không đoán tốc độ')
            rate = rates.rate(dev, int(t))
            piece, done, sent, npk = header + first, len(first), 0, 0
            t_start, t0 = time.time(), time.monotonic()
            while True:
                sent += len(piece)
                npk += 1
                delay = t0 + sent / rate - time.monotonic()      # mốc tuyệt đối từ t0: không cộng dồn sai số ngủ
                if delay > 0:
                    time.sleep(delay)
                dst.sendall(piece)
                if done >= n:
                    break
                piece = framing.recv_exactly(src, min(chunk, n - done))
                done += len(piece)
            stats.write({'kind': 'msg', 'dev': dev, 'type': mtype, 't': int(t), 'frame': frame, 'n_packets': npk,
                         'rate_Bps': rate, 'hold_s': time.monotonic() - t0, 'start_ts': t_start})
    except (ConnectionError, OSError):
        pass


def pump_through(src, dst):
    """Chiều BS -> thiết bị: đi thẳng, không giữ (đường xuống giả định lý tưởng)."""
    try:
        while True:
            data = src.recv(65536)
            if not data:
                break
            dst.sendall(data)
    except (ConnectionError, OSError):
        pass


def _close(*socks):
    for s in socks:
        try:
            s.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            s.close()
        except OSError:
            pass


def connect(host, port, timeout=120.0):
    """Nối tới BS, thử lại tới khi BS lắng nghe."""
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
            time.sleep(0.2)


class AutoRelay:
    def __init__(self, channel, bs_host, bs_port, listen_host, ports, stats_path, chunk=1460, held=HELD_TYPES,
                 accept_timeout=900.0, log=print):
        self.channel, self.bs_host, self.bs_port = channel, bs_host, int(bs_port)
        self.listen_host, self.ports = listen_host, [int(p) for p in ports]
        self.chunk, self.held, self.accept_timeout, self.log = int(chunk), tuple(held), float(accept_timeout), log
        self.stats = StatsLog(stats_path)
        self.rates = RateProvider(channel, self.stats)
        self.errors = []
        self.ready = threading.Event()

    def _listen(self):
        servers = []
        for port in self.ports:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((self.listen_host, port))
            s.listen(1)
            s.settimeout(self.accept_timeout)
            servers.append(s)
        return servers

    def _run_up(self, dev, device_sock, bs_sock):
        """Chạy luồng giữ tin; lỗi giao thức (vd. thiếu số vòng) được ghi nhận và đóng kết nối để FL dừng rõ ràng, không treo."""
        try:
            pump_held(dev, device_sock, bs_sock, self.rates, self.stats, self.chunk, self.held)
        except Exception as e:                          # noqa: BLE001
            self.errors.append(f'thiết bị {dev}: {e!r}')
            _close(device_sock, bs_sock)

    def _serve(self, dev, server):
        try:
            device_sock, _ = server.accept()
            device_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            device_sock.settimeout(None)
            bs_sock = connect(self.bs_host, self.bs_port)
            self.log(f'[ống] thiết bị {dev} đã nối (cổng {self.ports[dev - 1]}), chuyển tiếp tới {self.bs_host}:{self.bs_port}')
            up = threading.Thread(target=self._run_up, args=(dev, device_sock, bs_sock))
            down = threading.Thread(target=pump_through, args=(bs_sock, device_sock))
            up.start()
            down.start()
            up.join()                                   # thiết bị đóng kết nối (hết FL)
            _close(bs_sock)                             # báo cho BS biết, đồng thời kéo luồng xuống kết thúc
            down.join(timeout=30)
            _close(device_sock)
            self.log(f'[ống] thiết bị {dev} đã đóng')
        except Exception as e:                          # noqa: BLE001
            self.errors.append(f'thiết bị {dev}: {e!r}')
        finally:
            server.close()

    def run(self):
        servers = self._listen()
        self.ready.set()
        self.stats.write({'kind': 'start', 'mode': getattr(self.channel, 'mode', None), 'chunk': self.chunk, 'ports': self.ports,
                          'held': list(self.held), 'ts': time.time()})
        threads = [threading.Thread(target=self._serve, args=(k, s)) for k, s in enumerate(servers, start=1)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.stats.close()
        if self.errors:
            raise RuntimeError('; '.join(self.errors))
