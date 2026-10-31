"""Kiểm thử giới hạn Pi 4 trên Windows (Job Object, secure_fl/devicelimit.py) — chạy: python tests/secure_fl/test_devicelimit.py
Có kiểm tra THẬT: trần CPU làm tiến trình dùng ít nhân hơn, trần RAM làm cấp phát vượt trần thất bại. Máy không phải Windows thì bỏ qua."""
import subprocess
import sys
sys.stdout.reconfigure(encoding="utf-8")
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))

from secure_fl import devicelimit as DL

BUSY = 'import time\nt=time.time()\nwhile time.time()-t<4: pass'                 # đốt đúng 1 nhân trong 4 giây
ALLOC = 'import time\ntime.sleep(1.5)\nx=bytearray(400*2**20)\nprint("cap phat duoc")'   # đợi gắn job rồi xin 400 MiB


def run_in_job(code, cpus, mem):
    job = DL.JobLimit('thu', cpus, mem)
    p = subprocess.Popen([sys.executable, '-c', code], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    job.assign(p)
    out, _ = p.communicate(timeout=60)
    return p.returncode, out.decode(), job.finish()


def test_parse_and_rate():
    assert DL.parse_mem('4g') == 4 * 2**30 and DL.parse_mem('512m') == 512 * 2**20 and DL.parse_mem(1024) == 1024
    assert DL.cpu_rate_units(1.6, 12) == 1333 and DL.cpu_rate_units(12, 12) is None and DL.cpu_rate_units(0.0001, 12) == 1


def test_limits_read_back_from_windows():
    rc, _, ev = run_in_job('import time; time.sleep(1)', 1.6, '4g')
    rb = ev['gioi_han_doc_lai_tu_windows']
    assert rc == 0
    assert rb['tran_ram_moi_tien_trinh_mib'] == 4096.0, rb
    assert rb['tran_cpu_hard_cap'] is True and abs(rb['tuong_duong_so_nhan'] - 1.6) < 0.05, rb       # Windows làm tròn 1/100 %


def test_cpu_cap_is_enforced():
    _, _, free = run_in_job(BUSY, 64, '4g')                    # cpus >= số nhân: không có trần (đối chứng)
    _, _, capped = run_in_job(BUSY, 0.5, '4g')
    f, c = free['do_thuc_te']['so_nhan_trung_binh'], capped['do_thuc_te']['so_nhan_trung_binh']
    print(f'  nhân trung bình: không trần {f:.2f}, trần 0,5 nhân {c:.2f}')
    assert f > 0.5, f                                          # đối chứng phải chạy được gần 1 nhân (máy đang rất bận thì kết quả không có nghĩa)
    assert c < 0.7 and c < 0.75 * f, (c, f)                    # có trần thì dùng ít nhân hơn rõ rệt, kể cả khi máy hơi bận


def test_ram_cap_is_enforced():
    rc_ok, out_ok, _ = run_in_job(ALLOC, 64, '4g')
    rc_bad, out_bad, ev = run_in_job(ALLOC, 64, '200m')
    print(f'  trần 4g: mã thoát {rc_ok}; trần 200m: mã thoát {rc_bad}')
    assert rc_ok == 0 and 'cap phat duoc' in out_ok
    assert rc_bad != 0 and 'cap phat duoc' not in out_bad


if __name__ == '__main__':
    if not DL.available():
        print('BỎ QUA: không phải Windows (Job Object); dùng Docker cho giả lập Pi 4')
        sys.exit(0)
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith('test_'):
            try:
                fn()
                print(f'ĐẠT  {name}')
            except AssertionError as e:
                fails += 1
                print(f'LỖI  {name}: {e}')
    sys.exit(1 if fails else 0)
