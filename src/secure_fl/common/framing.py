import struct

HEADER = struct.Struct('>I')


class ProtocolError(RuntimeError):
    pass


def expect(cond, msg):
    if not cond:
        raise ProtocolError(msg)


def recv_exactly(sock, n):
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError('kết nối đóng khi đang đọc khung')
        buf.extend(chunk)
    return bytes(buf)


def read_header(sock):
    header = recv_exactly(sock, HEADER.size)
    return header, HEADER.unpack(header)[0]


def read_frame(sock):
    header, n = read_header(sock)
    return header + recv_exactly(sock, n)


def send_frame(sock, body):
    frame = HEADER.pack(len(body)) + body
    sock.sendall(frame)
    return len(frame)
