import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common import pi4_guard                                                       # noqa: F401,E402  bắt buộc: tự đưa tiến trình vào giả lập Pi 4

from common import train

CLIENT = 'client2'

if __name__ == '__main__':
    train.run(CLIENT)
