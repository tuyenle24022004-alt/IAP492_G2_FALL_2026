"""Kiểm thử giới hạn Pi 4 BẮT BUỘC tự áp trong script (devicelimit.enforce + common/pi4_guard) — chạy: python tests/secure_fl/test_device_guard.py
Có chạy thật tiến trình con trong Job Object; máy không phải Windows thì bỏ qua phần chạy thật nhưng vẫn kiểm tra tĩnh."""
import json
import subprocess
import sys
import tempfile
sys.stdout.reconfigure(encoding="utf-8")
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))

from secure_fl import devicelimit as DL

# Mọi script chạy trên thiết bị phải tự áp giới hạn: thiếu dòng này thì có thể chạy ngoài giả lập mà không ai biết
MODEL_ENTRY = [f'src/model/{c}/{f}.py' for c in ('client1', 'client2') for f in ('extract_features', 'train', 'evaluate_test', 'finetune')] \
    + ['src/model/run_fedavg.py', 'src/model/run_experiments.py']
SECURE_ENTRY = ['src/secure_fl/client/client.py', 'src/secure_fl/experiments/bench_train.py']


def child(code):
    r = subprocess.run([sys.executable, '-c', f'import sys; sys.path.insert(0, r"{ROOT / "src"}")\nfrom secure_fl import devicelimit as d\n{code}'],
                       capture_output=True, text=True, encoding='utf-8', timeout=120)
    return r


def test_entry_scripts_apply_the_limit():
    for p in MODEL_ENTRY:
        t = (ROOT / p).read_text(encoding='utf-8')
        assert 'from common import pi4_guard' in t, f'{p} thiếu pi4_guard'
        assert t.index('pi4_guard') < t.find('import torch') or 'import torch' not in t, f'{p}: pi4_guard phải đứng trước import torch'
    for p in SECURE_ENTRY:
        assert 'devicelimit.enforce(' in (ROOT / p).read_text(encoding='utf-8'), f'{p} thiếu devicelimit.enforce'


def test_no_switch_to_disable():
    cfg = (ROOT / 'src' / 'secure_fl' / 'config.yaml').read_text(encoding='utf-8')
    assert 'local_limits' not in cfg
    assert 'no-limit' not in (ROOT / 'src' / 'secure_fl' / 'experiments' / 'run_fl_tcp.py').read_text(encoding='utf-8')


def test_enforce_applies_and_writes_evidence():
    with tempfile.TemporaryDirectory() as d:
        r = child(f'd.enforce("thu", out_dir=r"{d}")\nprint("xin chao")')
        assert r.returncode == 0, r.stderr
        lim = json.loads((Path(d) / 'device_limits_thu.json').read_text(encoding='utf-8'))
        rb = lim['gioi_han_doc_lai_tu_windows']
        assert rb['tran_ram_moi_tien_trinh_mib'] == 4096.0 and rb['tran_cpu_hard_cap'] is True, rb
        assert abs(rb['tuong_duong_so_nhan'] - 1.6) < 0.05, rb
        assert 'giả lập' in r.stdout


def test_limit_really_binds_the_script_itself():
    """Cùng đoạn mã xin 400 MiB: trần 200 MiB làm nó lỗi bộ nhớ, trần 4 GiB thì qua. Chứng tỏ giới hạn áp lên CHÍNH tiến trình script."""
    with tempfile.TemporaryDirectory() as d:
        ok = child(f'd.enforce("a", out_dir=r"{d}")\nx = bytearray(400 * 2**20)\nprint("cap phat duoc")')
        bad = child(f'd.enforce("b", out_dir=r"{d}", mem="200m")\nx = bytearray(400 * 2**20)\nprint("cap phat duoc")')
        assert ok.returncode == 0 and 'cap phat duoc' in ok.stdout, ok.stderr
        assert bad.returncode != 0 and 'cap phat duoc' not in bad.stdout
        assert (Path(d) / 'device_limits_b.json').exists()                            # bằng chứng vẫn được ghi dù script lỗi


def test_default_run_dir_gets_log_and_run_json():
    with tempfile.TemporaryDirectory() as d:
        r = child(f'import secure_fl.devicelimit as m\nm.ROOT = __import__("pathlib").Path(r"{d}")\nd.enforce("buoc")\nprint("dong in ra")')
        assert r.returncode == 0, r.stderr
        run_dirs = list((Path(d) / 'outputs' / 'device_runs').glob('buoc_*'))
        assert len(run_dirs) == 1, run_dirs
        assert 'dong in ra' in (run_dirs[0] / 'output.log').read_text(encoding='utf-8')
        assert json.loads((run_dirs[0] / 'run.json').read_text(encoding='utf-8'))['loi_chua_xu_ly'] is False
        assert (run_dirs[0] / 'device_limits.json').exists()


if __name__ == '__main__':
    fails = 0
    for name, fn in sorted(globals().items()):
        if not name.startswith('test_'):
            continue
        if not DL.available() and name not in ('test_entry_scripts_apply_the_limit', 'test_no_switch_to_disable'):
            print(f'BỎ QUA {name}: không phải Windows')
            continue
        try:
            fn()
            print(f'ĐẠT  {name}')
        except AssertionError as e:
            fails += 1
            print(f'LỖI  {name}: {e}')
    sys.exit(1 if fails else 0)
