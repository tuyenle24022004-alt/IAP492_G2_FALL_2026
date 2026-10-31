"""Giả lập thiết bị biên kiểu Raspberry Pi 4 khi chạy TRỰC TIẾP trên Windows (không Docker): mỗi tiến trình client nằm trong một Job Object
với trần CPU và trần RAM lấy từ mục `device` của src/secure_fl/config.yaml. BS không bị giới hạn.

- CPU: trần cứng (HARD_CAP) = cpus / số nhân logic của máy, tính theo tỷ lệ tổng CPU của máy (vd. 1,6 / 12 nhân = 13,3%). Chỉ giới hạn SỐ NHÂN dùng được,
  KHÔNG làm nhân chậm đi như Cortex-A72 1,5 GHz của Pi thật, nên thời gian đo vẫn nhanh hơn Pi thật.
- RAM: trần commit mỗi tiến trình (JOB_OBJECT_LIMIT_PROCESS_MEMORY): cấp phát quá trần thì lỗi bộ nhớ (giống bị OOM). Đây là bộ nhớ commit, không phải RSS.
- Bằng chứng: đọc NGƯỢC giới hạn từ hệ điều hành (QueryInformationJobObject) và đo thực tế (working set đỉnh, commit đỉnh, thời gian CPU) -> device_limits.json.
Chỉ chạy trên Windows; nơi khác dùng Docker (docker-compose.yml, cùng mục `device`).
"""
import atexit
import ctypes
import json
import os
import re
import sys
import threading
import time
from ctypes import c_longlong, c_size_t, c_ulonglong, c_void_p, wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

_BASIC_ACCOUNTING, _EXTENDED_LIMIT, _CPU_RATE = 1, 9, 15
_LIMIT_PROCESS_MEMORY = 0x00000100
_CPU_RATE_ENABLE, _CPU_RATE_HARD_CAP = 0x1, 0x4
_UNITS = {'': 1, 'b': 1, 'k': 2**10, 'm': 2**20, 'g': 2**30}


class _Basic(ctypes.Structure):
    _fields_ = [('PerProcessUserTimeLimit', c_longlong), ('PerJobUserTimeLimit', c_longlong), ('LimitFlags', wintypes.DWORD),
                ('MinimumWorkingSetSize', c_size_t), ('MaximumWorkingSetSize', c_size_t), ('ActiveProcessLimit', wintypes.DWORD),
                ('Affinity', c_size_t), ('PriorityClass', wintypes.DWORD), ('SchedulingClass', wintypes.DWORD)]


class _Io(ctypes.Structure):
    _fields_ = [(n, c_ulonglong) for n in ('ReadOps', 'WriteOps', 'OtherOps', 'ReadBytes', 'WriteBytes', 'OtherBytes')]


class _Extended(ctypes.Structure):
    _fields_ = [('Basic', _Basic), ('Io', _Io), ('ProcessMemoryLimit', c_size_t), ('JobMemoryLimit', c_size_t),
                ('PeakProcessMemoryUsed', c_size_t), ('PeakJobMemoryUsed', c_size_t)]


class _CpuRate(ctypes.Structure):
    _fields_ = [('ControlFlags', wintypes.DWORD), ('CpuRate', wintypes.DWORD)]


class _Accounting(ctypes.Structure):
    _fields_ = [('TotalUserTime', c_longlong), ('TotalKernelTime', c_longlong), ('ThisPeriodTotalUserTime', c_longlong),
                ('ThisPeriodTotalKernelTime', c_longlong), ('TotalPageFaultCount', wintypes.DWORD), ('TotalProcesses', wintypes.DWORD),
                ('ActiveProcesses', wintypes.DWORD), ('TotalTerminatedProcesses', wintypes.DWORD)]


class _Pmc(ctypes.Structure):
    _fields_ = [('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD), ('PeakWorkingSetSize', c_size_t), ('WorkingSetSize', c_size_t),
                ('QuotaPeakPagedPoolUsage', c_size_t), ('QuotaPagedPoolUsage', c_size_t), ('QuotaPeakNonPagedPoolUsage', c_size_t),
                ('QuotaNonPagedPoolUsage', c_size_t), ('PagefileUsage', c_size_t), ('PeakPagefileUsage', c_size_t)]


def available():
    return os.name == 'nt'


def parse_mem(s):
    """'4g' -> 4294967296 (byte); chấp nhận số nguyên (byte), '512m', '4G', '4GiB'."""
    m = re.fullmatch(r'\s*([\d.]+)\s*([kmgb]?)(?:i?b)?\s*', str(s).lower())
    if not m:
        raise ValueError(f'không hiểu giới hạn RAM: {s!r}')
    return int(float(m.group(1)) * _UNITS[m.group(2)])


def cpu_rate_units(cpus, n_logical):
    """Trần CPU theo đơn vị của Windows (1/100 phần trăm tổng CPU máy); None nếu cpus >= số nhân (không cần trần)."""
    if cpus >= n_logical:
        return None
    return max(1, round(cpus / n_logical * 10000))


if available():
    _k32 = ctypes.WinDLL('kernel32', use_last_error=True)
    _psapi = ctypes.WinDLL('psapi', use_last_error=True)
    _k32.CreateJobObjectW.restype = c_void_p
    _k32.CreateJobObjectW.argtypes = [c_void_p, wintypes.LPCWSTR]
    _k32.SetInformationJobObject.argtypes = [c_void_p, ctypes.c_int, c_void_p, wintypes.DWORD]
    _k32.QueryInformationJobObject.argtypes = [c_void_p, ctypes.c_int, c_void_p, wintypes.DWORD, c_void_p]
    _k32.AssignProcessToJobObject.argtypes = [c_void_p, c_void_p]
    _k32.CloseHandle.argtypes = [c_void_p]
    _k32.GetCurrentProcess.restype = c_void_p
    _psapi.GetProcessMemoryInfo.argtypes = [c_void_p, ctypes.POINTER(_Pmc), wintypes.DWORD]


def _check(ok, what):
    if not ok:
        raise OSError(f'{what} lỗi (mã Windows {ctypes.get_last_error()})')


class JobLimit:
    """Một Job Object cho MỘT tiến trình client: đặt trần, gắn tiến trình, đo, rồi đọc kết quả bằng finish()."""

    def __init__(self, name, cpus, mem_limit):
        if not available():
            raise OSError('JobLimit chỉ chạy trên Windows')
        self.name, self.cpus, self.mem_bytes = name, float(cpus), parse_mem(mem_limit)
        self.n_logical = os.cpu_count()
        self.rate = cpu_rate_units(self.cpus, self.n_logical)
        self.h = _k32.CreateJobObjectW(None, None)
        _check(self.h, 'CreateJobObject')
        ext = _Extended()
        ext.Basic.LimitFlags = _LIMIT_PROCESS_MEMORY
        ext.ProcessMemoryLimit = self.mem_bytes
        _check(_k32.SetInformationJobObject(self.h, _EXTENDED_LIMIT, ctypes.byref(ext), ctypes.sizeof(ext)), 'đặt trần RAM')
        if self.rate:
            cr = _CpuRate(_CPU_RATE_ENABLE | _CPU_RATE_HARD_CAP, self.rate)
            _check(_k32.SetInformationJobObject(self.h, _CPU_RATE, ctypes.byref(cr), ctypes.sizeof(cr)), 'đặt trần CPU')
        self._proc, self._peak_ws, self._peak_commit = None, 0, 0
        self._stop, self._t0, self._thread = threading.Event(), None, None

    def assign(self, popen):
        """Gắn tiến trình con (đối tượng Popen) vào job ngay sau khi tạo và bắt đầu đo working set."""
        self._attach(c_void_p(int(popen._handle)))

    def assign_self(self):
        """Tự gắn CHÍNH tiến trình đang chạy (và mọi tiến trình con nó tạo ra sau này) vào job. Không gỡ ra được cho tới khi tiến trình kết thúc."""
        self._attach(c_void_p(_k32.GetCurrentProcess()))

    def _attach(self, handle):
        self._proc = handle
        _check(_k32.AssignProcessToJobObject(self.h, self._proc), f'gắn tiến trình {self.name} vào job')
        self._t0 = time.time()
        self._thread = threading.Thread(target=self._poll, daemon=True)
        self._thread.start()

    def _sample(self):
        pmc = _Pmc()
        pmc.cb = ctypes.sizeof(pmc)
        if _psapi.GetProcessMemoryInfo(self._proc, ctypes.byref(pmc), pmc.cb):
            self._peak_ws, self._peak_commit = max(self._peak_ws, pmc.PeakWorkingSetSize), max(self._peak_commit, pmc.PeakPagefileUsage)

    def _poll(self):
        while not self._stop.is_set():
            self._sample()
            self._stop.wait(0.5)

    def _query(self, cls, struct):
        s = struct()
        _check(_k32.QueryInformationJobObject(self.h, cls, ctypes.byref(s), ctypes.sizeof(s), None), 'đọc thông tin job')
        return s

    def finish(self):
        """Dừng đo, đọc ngược giới hạn từ hệ điều hành và số đo thực tế. Gọi sau khi tiến trình đã kết thúc."""
        wall = time.time() - self._t0 if self._t0 else float('nan')
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        self._sample()
        ext, cr, acc = self._query(_EXTENDED_LIMIT, _Extended), self._query(_CPU_RATE, _CpuRate), self._query(_BASIC_ACCOUNTING, _Accounting)
        cpu_s = (acc.TotalUserTime + acc.TotalKernelTime) / 1e7                                   # đơn vị 100 ns
        out = {'ten': self.name, 'so_nhan_logic_may': self.n_logical,
               'gioi_han_cau_hinh': {'cpus': self.cpus, 'mem_limit_mib': self.mem_bytes / 2**20},
               'gioi_han_doc_lai_tu_windows': {
                   'tran_ram_moi_tien_trinh_mib': ext.ProcessMemoryLimit / 2**20 if ext.Basic.LimitFlags & _LIMIT_PROCESS_MEMORY else None,
                   'tran_cpu_hard_cap': bool(cr.ControlFlags & _CPU_RATE_ENABLE and cr.ControlFlags & _CPU_RATE_HARD_CAP),
                   'tran_cpu_phan_tram_tong_cpu_may': cr.CpuRate / 100 if cr.ControlFlags & _CPU_RATE_ENABLE else None,
                   'tuong_duong_so_nhan': cr.CpuRate / 10000 * self.n_logical if cr.ControlFlags & _CPU_RATE_ENABLE else None},
               'do_thuc_te': {'working_set_dinh_mib': self._peak_ws / 2**20, 'commit_dinh_mib': max(self._peak_commit, ext.PeakProcessMemoryUsed) / 2**20,
                              'thoi_gian_cpu_s': cpu_s, 'thoi_gian_thuc_s': wall, 'so_nhan_trung_binh': cpu_s / wall if wall else float('nan')}}
        _k32.CloseHandle(self.h)
        return out


class _Tee:
    """Ghi mọi chữ in ra màn hình đồng thời vào file log; mọi thuộc tính khác chuyển cho luồng gốc (vd. reconfigure)."""

    def __init__(self, stream, fh):
        self._s, self._f = stream, fh

    def write(self, s):
        n = self._s.write(s)
        self._f.write(s)
        return n

    def flush(self):
        self._s.flush()
        self._f.flush()

    def __getattr__(self, name):
        return getattr(self._s, name)


_STATE = {}


def enforce(name, out_dir=None, cpus=None, mem=None):
    """BẮT BUỘC: đưa tiến trình HIỆN TẠI vào giả lập thiết bị (giới hạn lấy từ mục `device` của config) rồi mới chạy tiếp; không áp được thì dừng hẳn, không có cách bỏ qua.
    Gọi ở đầu mọi script chạy trên thiết bị (script của src/model dùng `from common import pi4_guard`). Gọi lại trong cùng tiến trình thì không làm gì thêm.
    - Windows: Job Object cho chính tiến trình này; khi thoát ghi bằng chứng (giới hạn đọc ngược từ Windows + số đo thực tế).
    - Chạy trong container Docker (Linux): Docker áp giới hạn (docker-compose.yml), compose đặt DEVICE_LIMIT_BY=docker; bằng chứng là docker_limits.json của run_fl_docker.py.
    - Nơi khác: từ chối chạy.
    Mặc định ghi vào outputs/device_runs/<name>_<giờ>/ (output.log, run.json, device_limits.json) và sao luồng in ra vào output.log;
    nếu cho out_dir thì chỉ ghi device_limits_<name>.json ở đó (client của run_fl_tcp đã có log riêng).
    `cpus`/`mem` chỉ dành cho test, script thật không truyền."""
    if _STATE:
        return _STATE['job']
    if not available():
        if os.environ.get('DEVICE_LIMIT_BY') == 'docker':
            print(f'[giả lập thiết bị] {name}: giới hạn do Docker áp (docker-compose.yml)', flush=True)
            _STATE['job'] = None
            return None
        raise SystemExit(f'[giả lập thiết bị] {name}: cần chạy trong giả lập Pi 4 (Windows Job Object hoặc container Docker) nhưng máy này không hỗ trợ; từ chối chạy')
    from . import settings
    dev = settings.load()['device']
    cpus, mem = cpus or dev['cpus'], mem or dev['mem_limit']
    stamp = time.strftime('%Y%m%d_%H%M%S')
    job = JobLimit(name, cpus, mem)
    try:
        job.assign_self()
    except OSError as e:
        raise SystemExit(f'[giả lập thiết bị] {name}: không áp được giới hạn Pi 4 ({e}); từ chối chạy ngoài giả lập')
    per_run_dir = out_dir is None
    out = Path(out_dir) if out_dir else ROOT / 'outputs' / 'device_runs' / f'{name}_{stamp}'
    out.mkdir(parents=True, exist_ok=True)
    log = None
    if per_run_dir:
        log = open(out / 'output.log', 'w', encoding='utf-8')
        sys.stdout, sys.stderr = _Tee(sys.stdout, log), _Tee(sys.stderr, log)
    state = {'loi_chua_xu_ly': False, 't0': time.strftime('%Y-%m-%d %H:%M:%S')}
    prev_hook = sys.excepthook

    def hook(*a):
        state['loi_chua_xu_ly'] = True
        prev_hook(*a)

    sys.excepthook = hook
    print(f'[giả lập {dev["profile"]}] {name}: tối đa {cpus} nhân, RAM {mem}; bằng chứng: {out}', flush=True)

    def finish():
        ev = job.finish()
        suffix = '' if per_run_dir else f'_{name}'
        (out / f'device_limits{suffix}.json').write_text(json.dumps(ev, ensure_ascii=False, indent=1), encoding='utf-8')
        if per_run_dir:
            (out / 'run.json').write_text(json.dumps({'ten': name, 'lenh': sys.argv, 'bat_dau': state['t0'], 'ket_thuc': time.strftime('%Y-%m-%d %H:%M:%S'),
                                                      'loi_chua_xu_ly': state['loi_chua_xu_ly'], 'python': sys.version.split()[0],
                                                      'thu_muc_chay': os.getcwd()}, ensure_ascii=False, indent=1), encoding='utf-8')
        m = ev['do_thuc_te']
        print(f'[giả lập] xong {name}: {m["thoi_gian_thuc_s"]:.0f}s thực, {m["thoi_gian_cpu_s"]:.0f}s CPU ({m["so_nhan_trung_binh"]:.2f} nhân TB), '
              f'RAM đỉnh {m["working_set_dinh_mib"]:.0f} MiB (working set) / {m["commit_dinh_mib"]:.0f} MiB (commit)', flush=True)
        if log:
            sys.stdout, sys.stderr = sys.__stdout__, sys.__stderr__
            log.close()

    atexit.register(finish)
    _STATE['job'] = job
    return job
