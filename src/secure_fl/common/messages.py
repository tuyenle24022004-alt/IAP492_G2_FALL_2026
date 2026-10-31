import msgpack
import numpy as np

from .framing import HEADER, read_frame, send_frame

HELLO = 'HELLO'
HE_CONTEXT = 'HE_CONTEXT'
HE_PK1 = 'HE_PK1'
HE_PK = 'HE_PK'
CHANNEL_REPORT = 'CHANNEL_REPORT'
ROUND_START = 'ROUND_START'
UPLOAD = 'UPLOAD'
CSUM = 'CSUM'
PARTIAL_DEC = 'PARTIAL_DEC'
AGGREGATE = 'AGGREGATE'
METRICS = 'METRICS'
ROUND_DONE = 'ROUND_DONE'
UAV_STATS = 'UAV_STATS'


def encode(mtype, obj=None):
    d = {'type': mtype}
    d.update(obj or {})
    d['type'] = mtype
    return msgpack.packb(d, use_bin_type=True)


def send_msg(sock, mtype, obj=None):
    return send_frame(sock, encode(mtype, obj))


def recv_msg(sock):
    frame = read_frame(sock)
    return msgpack.unpackb(frame[HEADER.size:], raw=False), len(frame)


def peek_type(body_prefix):
    try:
        up = msgpack.Unpacker(raw=False)
        up.feed(body_prefix)
        up.read_map_header()
        if up.unpack() == 'type':
            return up.unpack()
    except Exception:
        pass
    return None


def pack_array(a, dtype=np.float32):
    a = np.ascontiguousarray(a, dtype=dtype)
    return {'shape': list(a.shape), 'dtype': a.dtype.str, 'data': a.tobytes()}


def unpack_array(d):
    return np.frombuffer(d['data'], dtype=np.dtype(d.get('dtype', '<f4'))).reshape(tuple(d['shape']))
