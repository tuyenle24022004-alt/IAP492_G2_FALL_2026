"""Import module này ở ĐẦU mọi script chạy trên thiết bị (trích đặc trưng, huấn luyện, đánh giá, FedAvg tham chiếu...):

    from common import pi4_guard    # noqa: F401  (bắt buộc, phải đứng trước các import khác của dự án)

Việc import tự đưa tiến trình vào giả lập Raspberry Pi 4 (giới hạn nhân và RAM trong mục `device` của src/secure_fl/config.yaml) trước khi làm gì khác.
Không áp được giới hạn thì script dừng hẳn; không có cờ hay biến môi trường để bỏ qua. Chi tiết và bằng chứng: src/secure_fl/devicelimit.py.
"""
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2]
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from secure_fl import devicelimit                                                # noqa: E402

_script = Path(sys.argv[0]).resolve() if sys.argv and sys.argv[0] else Path('interactive.py')
NAME = f'{_script.parent.name}_{_script.stem}' if _script.parent.name.startswith('client') else _script.stem       # vd. client1_train, run_fedavg
devicelimit.enforce(NAME)
