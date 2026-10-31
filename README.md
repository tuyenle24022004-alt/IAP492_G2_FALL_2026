# FL nhận dạng khói và lửa: so sánh bảo vệ cập nhật (CKKS 100%, FAS) với không lock

Đồ án (Phan Hồng Quí, FPT): học liên kết (FedAvg) giữa 2 client và trạm gốc (BS), bảo vệ cập nhật mô hình bằng mã hóa đồng cấu đa khóa
xMK-CKKS. Giai đoạn hiện tại **chỉ đo giao thức client ↔ BS**; kênh vô tuyến và UAV relay đã có mã nhưng **chưa đo** (`src/uav_channel/`).

| Phương án | Bảo vệ |
|---|---|
| **none** (không lock) | gửi trọng số rõ |
| **ckks_full** (lock A) | mã hóa 100% bằng xMK-CKKS |
| **fas** (lock B) | p = 10% mã hóa xMK-CKKS; phần còn lại thêm nhiễu λ·RMS rồi xáo vị trí bằng π_t (khóa chỉ ở 2 client) |

Mô hình: SqueezeNet 1.1 đóng băng, chỉ huấn luyện lớp phân loại cuối (1.539 tham số, vừa 1 ciphertext). Thiết kế: [docs/kien_truc_testbed_moi.md](docs/kien_truc_testbed_moi.md).

## Cấu trúc thư mục

```
src/
  model/              học máy: dữ liệu, mô hình, huấn luyện cục bộ, FedAvg không mã hóa, thí nghiệm nhiều seed; config.yaml riêng
  secure_fl/          PHẦN ĐANG ĐO: client ↔ BS (config.yaml riêng: he, lock)
    common/           khung tin nhắn length-prefixed + msgpack
    security/         none, ckks_full, fas (cùng giao diện chia theo vai trò client/BS); he_backend (emulated | openfhe), mkckks, perm
    bs/server.py      trạm gốc: chỉ cộng, không có mô hình/khóa; ghi byte thật từng tin nhắn, capture phần rõ nhận được
    client/client.py  thiết bị: huấn luyện, bảo vệ, giải mã/giải xáo, cập nhật mô hình (mỗi tiến trình chỉ đọc dữ liệu của mình)
    arms.py           danh sách "arm" (mỗi arm = một lượt FL với một cấu hình bảo vệ)
    experiments/      run_fl_tcp (BS + 2 client trên máy, emulated), run_fl_docker (3 container, OpenFHE THẬT), collect (gộp; tấn công ngoại tuyến tạm tắt), analyze (bảng, cổng 1, hình),
                      bench_train
  uav_channel/        CHƯA ĐO: channel/ (Al-Hourani, Rician, AF, NOMA + SIC, 3GPP UMa), uav/ (relay, bóp tốc độ), cost_time.py; config.yaml riêng
  data_understanding/ phân tích dữ liệu khói/lửa
docker/               Dockerfile + docker-compose (bs, client1, client2) + override cho arm fasbs_*
tests/
  secure_fl/          test_security (3 chế độ, gói tin, vai trò), test_protocol (BS thật + 2 client giả qua TCP)
  uav_channel/        test_channel, test_uav_relay, ref/
docs/  report/        thiết kế, kế hoạch, báo cáo
data/clients/         ảnh theo client (không lưu git)
outputs/              model/ (huấn luyện, FedAvg), data_understanding/, secure_fl/ (tcp/ = kết quả chính; thiet_ke_cu_delta_tu_g0/ = thiết kế cũ, chỉ tham khảo)
```

Mọi lệnh chạy từ **thư mục gốc repo**.

## Luồng thí nghiệm

1. Mỗi client huấn luyện cục bộ 150 epoch (đã có `outputs/model/client*/run/weights.npy`).
2. **Vòng 0:** mỗi client bảo vệ TRỌNG SỐ đó (nhân n_k/n) rồi gửi BS; BS cộng; hai client giải mã -> mô hình toàn cục ban đầu (= "trung bình 1 lần" nhưng qua bảo vệ).
3. **Vòng 1..50** (`fl.rounds`, `fl.local_epochs` = 1 trong `src/model/config.yaml`): mỗi client huấn luyện 1 epoch từ mô hình toàn cục, bảo vệ trọng số mới, BS cộng, client giải mã.
4. Client1 đánh giá trên tập test mỗi vòng. So lock (`ckks_full`, `fas`) với không lock (`none` chạy lại qua đúng quy trình này).

```sh
pip install -r requirements.txt
python src/secure_fl/experiments/run_fl_tcp.py --seed 42     # 10 arm × (vòng 0 + 50 vòng); chạy lại được nếu bị dừng (arm đã xong thì bỏ qua)
python src/secure_fl/experiments/analyze.py                  # -> outputs/secure_fl/tcp/classifier/summary_classifier.md + hình
```

Hiện chỉ có seed 42 vì chỉ seed này có trọng số huấn luyện cục bộ 150 epoch. Mỗi arm = 1 tiến trình BS + 2 tiến trình client nói chuyện qua TCP trên 127.0.0.1.
`lock.backend: emulated` (mặc định) KHÔNG mã hóa: chỉ mô hình hóa sai số CKKS và đệm gói đúng cỡ ciphertext đã đo, nên chạy được trên Windows nhưng không chứng minh mã hóa
đúng. Mã hóa thật (OpenFHE đa khóa) chỉ chạy trong container Linux:

```sh
winget install -e --id Docker.DockerDesktop          # một lần; cần quyền quản trị, có thể phải khởi động lại; rồi mở Docker Desktop
python src/secure_fl/experiments/run_fl_docker.py --seed 42     # 10 arm × 3 container; -> outputs/secure_fl/docker/
python src/secure_fl/experiments/analyze.py --out outputs/secure_fl/docker
```

Trong container: BS chỉ thấy `src` và thư mục kết quả của nó; mỗi client chỉ thấy đặc trưng/trọng số của mình (client1 thêm tập test); khóa xáo K chỉ mount vào hai client
(BS chỉ nhận ở arm `fasbs_*`); mỗi client giới hạn 1,6 CPU và 4 GB RAM như Raspberry Pi 4. Phần thiết lập khóa đa bên và (de)serialize OpenFHE (`security/he_backend.py`)
port từ mã cũ; đã kiểm chứng trong container: `docker run --rm -v "${PWD}:/app" doanfl-securefl python tests/secure_fl/test_openfhe.py` (build: `docker build -f docker/Dockerfile -t doanfl-securefl .`).

## Test

```sh
python tests/secure_fl/test_security.py     # test OpenFHE tự bỏ qua nếu máy không có thư viện
python tests/secure_fl/test_protocol.py
python tests/secure_fl/test_attack_switch.py   # công tắc lock.attack_enabled và hàm chọn phương án
python tests/secure_fl/test_device_profile.py  # mục device nối đúng vào docker-compose
python tests/secure_fl/test_devicelimit.py     # giới hạn Pi 4 trên Windows (Job Object): trần CPU/RAM có hiệu lực thật
python tests/secure_fl/test_device_guard.py    # script tự áp giới hạn bắt buộc, mọi script chạy trên thiết bị đều có
python tests/secure_fl/test_openfhe.py     # chỉ chạy được trong container
python tests/uav_channel/test_channel.py
python tests/uav_channel/test_uav_relay.py
```

## Giả lập thiết bị Pi 4

Mục `device` trong `src/secure_fl/config.yaml` (cpus 1,6; mem_limit 4g) áp cho client, BS không bị giới hạn. Giới hạn là **BẮT BUỘC và tự áp trong chính script**, không có cờ hay
biến môi trường để tắt: mọi script chạy trên thiết bị gọi `devicelimit.enforce` (qua `from common import pi4_guard` hoặc trực tiếp) ngay khi khởi động; không áp được thì script dừng hẳn.
Vì vậy chỉ cần chạy `python <tên file>`:
- **Windows (chạy trực tiếp):** Job Object cho chính tiến trình đó (`src/secure_fl/devicelimit.py`). Script ghi `outputs/device_runs/<tên>_<giờ>/` gồm `output.log`, `run.json`, `device_limits.json`
  (giới hạn đọc ngược từ Windows, RAM/CPU đỉnh thực tế). Client của `run_fl_tcp.py` ghi `device_limits_client<k>.json` vào thư mục từng arm.
- **Docker:** compose áp giới hạn (`run_fl_docker.py` truyền từ mục `device`), mỗi arm ghi `docker_limits.json`.
- Máy khác (không Windows, không Docker): script từ chối chạy.
Chỉ giới hạn số nhân và RAM, không làm CPU chậm như Pi thật nên thời gian đo vẫn nhanh hơn thiết bị thật.

### Chạy toàn bộ, từng bước (PowerShell, từ thư mục gốc)

Bước 0: đổi tên kết quả cũ (không xoá) để không bị dùng lại nhầm (cache đặc trưng, `weights.npy`, arm đã có kết quả):

```powershell
Rename-Item outputs\model model_chua_gioi_han_20261030
Rename-Item outputs\secure_fl\tcp tcp_gioi_han_chi_vong_fl_20261030      # chỉ nếu thư mục tcp còn
```

Chạy lần lượt, mỗi lần một lệnh, kiểm tra không lỗi rồi mới sang lệnh sau:

```powershell
# 1-2. trích đặc trưng SqueezeNet (thân đóng băng) cho dữ liệu của từng client (client1 còn trích tập test dùng chung)
python src/model/client1/extract_features.py
python src/model/client2/extract_features.py
# 3-4. huấn luyện cục bộ 150 epoch -> outputs\model\clientK\run\weights.npy
python src/model/client1/train.py
python src/model/client2/train.py
# 5-6. đánh giá mô hình cục bộ trên tập test -> outputs\model\clientK\test\
python src/model/client1/evaluate_test.py
python src/model/client2/evaluate_test.py
# 7. tổng hợp hai mô hình cục bộ (chỉ ghép bảng, không phải thiết bị) -> outputs\model\shared\
python src/model/compare_local.py
# 8. đo thời gian 1 epoch huấn luyện cục bộ -> outputs\secure_fl\timing_classifier.json
python src/secure_fl/experiments/bench_train.py classifier
# 9. FedAvg không mã hóa tham chiếu (hai client huấn luyện lần lượt trong MỘT tiến trình, dùng chung một giới hạn) -> outputs\model\fedavg_50\
python src/model/run_fedavg.py
# 10. so sánh lock / không lock qua BS + 2 client (mỗi client tự giới hạn) -> outputs\secure_fl\tcp\
python src/secure_fl/experiments/run_fl_tcp.py --seed 42
python src/secure_fl/experiments/analyze.py
# 11. (tuỳ chọn, rất lâu) nhiều seed, hai chế độ mô hình -> outputs\model\experiments\so_sanh\
python src/model/run_experiments.py
```

Lưu ý: bước 1 và 2 đều trích ảnh; tập test dùng chung chỉ được trích ở bước 1 (bước 2 dùng cache). Bước 9 và 11 chạy cả hai client trong một tiến trình nên RAM đỉnh là của cả hai client cộng lại.

## Giới hạn đã biết

- **Đánh giá tấn công đang tạm tắt** (`lock.attack_enabled: false` trong `src/secure_fl/config.yaml`): chưa có số liệu về mức rò rỉ, nên bảng chọn phương án chỉ xét độ chính xác và byte và chỉ là xếp hạng sơ bộ.
  Mã tấn công (`collect.py`) và dữ liệu `capture/`, `truth/` vẫn còn, bật lại bằng `attack_enabled: true` khi cần (nhãn Δ trong `analyze.py` cần sửa thành trọng số).
- BS biết TỔNG sau khi ghép phần giải mã; với 2 thiết bị, thiết bị này suy ra được cập nhật thiết bị kia.
- Phần giải mã đa bên dùng nhiễu mặc định của OpenFHE (xem `security/mkckks.py`).
- Kích thước ciphertext và thời gian mã hóa trong config là số đo CŨ, chưa đo lại; đo khi chạy trong container.
- Nhiễu và khóa K trong thí nghiệm sinh từ seed để lặp lại được (`lock.noise_entropy: seeded`); khi triển khai phải dùng entropy hệ điều hành.
- Dữ liệu của hai client tách bằng quy ước thư mục, chưa bị ép bởi hệ điều hành (chưa có container).
