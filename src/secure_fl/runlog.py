"""Ghi mọi dòng in ra màn hình của một lệnh chạy vào file log (có dấu thời gian trong tên), vẫn in ra màn hình như thường.
Dùng: install_tee(thư_mục / 'logs' / f'tên_{stamp()}.log') ngay sau khi đọc tham số."""
import sys
import time
from pathlib import Path


def stamp():
    return time.strftime('%Y%m%d_%H%M%S')


class _Tee:
    def __init__(self, stream, f):
        self.stream, self.f = stream, f

    def write(self, s):
        self.stream.write(s)
        self.f.write(s)
        self.f.flush()
        return len(s)

    def flush(self):
        self.stream.flush()
        self.f.flush()

    def __getattr__(self, name):
        return getattr(self.stream, name)


def install_tee(path):
    """sys.stdout và sys.stderr được nhân đôi ra `path` cho tới hết tiến trình. Trả về đường dẫn file log."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    f = open(path, 'a', encoding='utf-8')
    f.write(f'# lệnh: {" ".join(sys.argv)}\n# bắt đầu: {time.strftime("%Y-%m-%d %H:%M:%S")}\n')
    sys.stdout, sys.stderr = _Tee(sys.stdout, f), _Tee(sys.stderr, f)
    return path


def write_run_info(path, **extra):
    """Ghi 'phiếu lý lịch' của lượt chạy: lệnh, giờ, commit git, toàn bộ cấu hình đang dùng. Để sau này biết kết quả sinh ra từ cấu hình nào."""
    import json
    import platform
    import subprocess

    from secure_fl import settings
    root = Path(__file__).resolve().parents[2]

    def git(*args):
        try:
            return subprocess.run(['git', *args], cwd=root, capture_output=True, text=True, timeout=20).stdout.strip()
        except Exception:                                                    # noqa: BLE001
            return None

    import yaml
    info = {'lenh': sys.argv, 'thoi_diem': time.strftime('%Y-%m-%d %H:%M:%S'), 'python': platform.python_version(),
            'git_commit': git('rev-parse', 'HEAD'), 'git_co_thay_doi_chua_commit': bool(git('status', '--porcelain', '--', 'src')),
            'cau_hinh_secure_fl': settings.load(),
            'cau_hinh_model': yaml.safe_load(open(root / 'src' / 'model' / 'config.yaml', encoding='utf-8')), **extra}
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(info, ensure_ascii=False, indent=1, default=str), encoding='utf-8')
    return path


def archive_existing(path):
    """Trước khi GHI ĐÈ một file kết quả: chép bản đang có sang <thư mục>/lich_su/<tên>_<giờ sửa lần cuối><đuôi>. Không bao giờ mất bản cũ."""
    import shutil
    path = Path(path)
    if not path.exists():
        return None
    hist = path.parent / 'lich_su'
    hist.mkdir(exist_ok=True)
    dst = hist / f'{path.stem}_{time.strftime("%Y%m%d_%H%M%S", time.localtime(path.stat().st_mtime))}{path.suffix}'
    if not dst.exists():
        shutil.copy2(path, dst)
    return dst
