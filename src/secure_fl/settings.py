"""Đọc src/secure_fl/config.yaml. Biến môi trường SECURE_FL_BACKEND (emulated | openfhe) ghi đè `lock.backend`,
để cùng một mã chạy được trên Windows (emulated) lẫn trong container Linux (openfhe) mà không sửa file config."""
import os
from pathlib import Path

import yaml

CONFIG = Path(__file__).resolve().parent / 'config.yaml'


def load():
    cfg = yaml.safe_load(open(CONFIG, encoding='utf-8'))
    backend = os.environ.get('SECURE_FL_BACKEND')
    if backend:
        cfg['lock']['backend'] = backend
    return cfg
