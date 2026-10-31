# Báo cáo giả lập hai thiết bị biên và cấu hình client

## 1. Mục tiêu

Báo cáo mô tả cách một máy tính cá nhân được dùng để giả lập hai thiết bị biên có giới hạn tương đương Raspberry Pi 4, cùng với cấu hình của hai client (client1, client2) trong bài toán học liên kết nhận dạng khói và lửa. Phần này làm nền cho bước huấn luyện cục bộ, tổng hợp trọng số và so sánh lock/không lock. Số liệu về dữ liệu lấy từ báo cáo dữ liệu (`bao_cao_du_lieu.md`); cấu hình huấn luyện lấy từ `src/model/config.yaml`; giới hạn tài nguyên lấy từ mục `device` của `src/secure_fl/config.yaml`.

Trạng thái hiện tại:
- Đã làm: định nghĩa mô hình, finetune (đóng băng lớp), trích đặc trưng, huấn luyện cục bộ, FedAvg tham chiếu và lượt so sánh lock/không lock; **mọi script chạy trên thiết bị đều tự áp giới hạn Pi 4 (1,6 nhân, 4 GB) khi khởi động và ghi bằng chứng** (mục 8).
- Giới hạn của giả lập: chỉ giới hạn số nhân và RAM, **không làm CPU chậm như Cortex-A72 1,5 GHz**; chưa có hệ số quy đổi thời gian sang thiết bị thật. Không dùng Docker cho phần huấn luyện và lượt so sánh chính (Docker chỉ còn cho mã hóa OpenFHE thật, chưa chạy lại sau khi thêm giả lập).

## 2. Thiết bị tham chiếu và máy giả lập

Thiết bị tham chiếu là Raspberry Pi 4 Model B như trong bài báo Priv-FedTL (Osmani và cộng sự, Computer Networks 286, 2026). Bài báo giả lập client bằng nhóm điều khiển tài nguyên (cgroup) của Linux và nhân hệ số quy đổi 1,4 để đổi thời gian đo được sang thời gian ước tính trên thiết bị thật. Đề án chạy trên Windows nên dùng Job Object của Windows thay cho cgroup (mục 8).

| Thông số | Pi 4 theo bài báo | Máy giả lập của đề án |
|---|---|---|
| CPU | 4 nhân, giới hạn 40% mỗi nhân, tương đương khoảng 1,6 nhân | Intel Core i7-1255U, 10 nhân vật lý, 12 luồng; mỗi client bị giới hạn cứng ở 1,6 nhân bằng Job Object |
| RAM | 4096 MB | 7,7 GB tổng; mỗi client có trần bộ nhớ cam kết (commit) 4096 MiB |
| GPU | Tắt | Không dùng GPU |
| Hệ số quy đổi thời gian | 1,4 | Chưa áp dụng (cần đo, vì máy giả lập khác máy dùng trong bài báo và giả lập không làm chậm CPU) |
| Thư viện | PyTorch trên CPU | PyTorch trên CPU |

Hai client mỗi bên 1,6 nhân là 3,2 nhân trên 12 luồng logic nên ít tranh tài nguyên về CPU. Về RAM, hai trần 4 GB cộng lại (8 GB) lớn hơn RAM thật của máy (7,7 GB); trần chỉ là mức tối đa, và các lượt đo cho thấy mỗi client chỉ dùng đỉnh dưới 700 MiB RAM vật lý ở lượt so sánh lock/không lock (xem `bao_cao_so_sanh_ma_hoa_khong_mahoa.md`, mục 2.6).

## 3. Nguyên tắc giả lập hai thiết bị

1. **Tách dữ liệu.** Mỗi client chỉ đọc thư mục dữ liệu của mình (`data/clients/client1`, `data/clients/client2`). Tập test dùng chung nằm ngoài cả hai client và không dùng trong huấn luyện cục bộ.
2. **Tách tiến trình và đầu ra.** Ở lượt so sánh lock/không lock, BS và hai client là ba tiến trình riêng nối bằng TCP, mỗi client ghi kết quả vào thư mục riêng. Ở các bước huấn luyện cục bộ, mỗi client là một lần chạy riêng (`outputs/model/client1`, `outputs/model/client2`). **Ngoại lệ:** `run_fedavg.py` và `run_experiments.py` chạy cả hai client lần lượt trong MỘT tiến trình (dùng chung một giới hạn).
3. **Tách tài nguyên.** Mỗi tiến trình thiết bị tự giới hạn CPU và RAM theo Pi 4 ngay khi khởi động (mục 8); BS không bị giới hạn. Cách ly bằng container không dùng ở các bước này.
4. **Cùng điểm xuất phát.** Hai client dựng cùng mô hình, cùng trọng số ImageNet và cùng đầu phân loại khởi tạo (seed 42), để việc lấy trung bình trọng số có ý nghĩa.

Phần cách ly dữ liệu chỉ dựa vào quy ước thư mục, chưa bị ép buộc bởi hệ điều hành: tiến trình client có quyền đọc cả thư mục của client kia nếu mã bị sửa. Giới hạn CPU/RAM thì do hệ điều hành ép buộc.

## 4. Cấu hình chung của hai client

Tất cả tham số nằm trong một tệp duy nhất, dùng chung cho hai client, nên hai thiết bị luôn cùng cấu hình.

### 4.1 Mô hình

| Tham số | Giá trị | Nguồn |
|---|---|---|
| Kiến trúc | SqueezeNet 1.1 | Bài báo |
| Trọng số khởi tạo | ImageNet (torchvision, IMAGENET1K_V1) | Bài báo |
| Số lớp phân loại | 3 (bình thường, khói, lửa) | Đề án |
| Phần được huấn luyện | Chỉ lớp phân loại cuối (`classifier`) | Bài báo |
| Tham số huấn luyện | 1.539 (512 × 3 + 3) | Tính từ cấu hình |
| Tham số đóng băng | 722.496 | Tính từ cấu hình |
| Tổng tham số | 724.035 | Tính từ cấu hình |
| Kích thước ảnh vào | 128 × 128 | Bài báo |
| Cách đổi kích thước | Kéo giãn về vuông (`squash`) | Bài báo |

Với 2 lớp phân loại, bài báo có 1.026 tham số huấn luyện và 723.522 tham số tổng; với 3 lớp, cùng kiến trúc cho 1.539 và 724.035, chênh đúng 513 tham số. Số tham số của đề án khớp với cách dựng mô hình trong bài báo.

Thân mạng được đóng băng hoàn toàn nên đặc trưng của ảnh không đổi giữa các epoch. Vì vậy đặc trưng được trích một lần và lưu lại (dạng float16, kích thước 512 × 7 × 7 mỗi ảnh), mỗi epoch chỉ chạy phần đầu phân loại. Cách làm này cho kết quả giống hệt chạy lại cả mạng mỗi epoch vì không dùng tăng cường dữ liệu.

### 4.2 Huấn luyện cục bộ

| Tham số | Giá trị | Nguồn |
|---|---|---|
| Trình tối ưu | SGD | Bài báo |
| Tốc độ học | 0,01 | Bài báo |
| Momentum | 0 | Bài báo không nêu (mặc định của SGD) |
| Weight decay | 0 | Bài báo không nêu |
| Điều chỉnh tốc độ học | StepLR, bước 7 epoch, hệ số 0,1 | Bài báo |
| Hàm mất mát | Cross-entropy | Bài báo |
| Kích thước lô | 64 | Đề án (bài báo không nêu) |
| Số epoch | 150, huấn luyện đủ, không dừng sớm | Đề án |
| Mô hình cuối | Trọng số của epoch cuối | Đề án (theo cách làm của bài báo, không chọn theo val) |
| Seed | 42 | Bài báo |
| Số luồng PyTorch | 2 | Đề án, khớp với khoảng 1,6 nhân |

Bài báo chạy 1 epoch cục bộ mỗi vòng trên phần cứng thật và 10 epoch mỗi vòng trong giả lập. Đề án chạy 150 epoch ở bước huấn luyện cục bộ ban đầu, tương ứng với baseline "TL" của bài báo (một thiết bị tự fine-tune đầu mô hình), chưa phải số epoch cục bộ trong từng vòng học liên kết.

Một lưu ý về lịch giảm tốc độ học: StepLR giảm tốc độ học 10 lần sau mỗi 7 epoch (0,01, 0,001, 0,0001, ...). Sau khoảng 25 đến 30 epoch tốc độ học nhỏ đến mức mô hình gần như ngừng thay đổi, nên phần lớn trong 150 epoch không còn làm thay đổi đáng kể trọng số. Đây là hệ quả của việc giữ nguyên lịch của bài báo, không phải lỗi.

## 5. Điểm khác nhau giữa hai client

Cấu hình mô hình và huấn luyện giống hệt nhau. Hai client chỉ khác ở dữ liệu cục bộ.

| | client1 | client2 |
|---|---|---|
| Ảnh train | 2.620 | 2.414 |
| Ảnh val | 363 | 320 |
| Bình thường (train / val) | 777 / 104 | 777 / 103 |
| Khói (train / val) | 1.529 / 217 | 382 / 50 |
| Lửa (train / val) | 314 / 42 | 1.255 / 167 |
| Cơ cấu lớp trong train (bình thường / khói / lửa) | 29,7% / 58,4% / 12,0% | 32,2% / 15,8% / 52,0% |
| Đặc điểm | Nghiêng về khói | Nghiêng về lửa |
| Thư mục dữ liệu | `data/clients/client1/{train,val}` | `data/clients/client2/{train,val}` |
| Thư mục kết quả | `outputs/model/client1` | `outputs/model/client2` |
| Đặc trưng train đã trích | 2.620 × 512 × 7 × 7, 132 MB | 2.414 × 512 × 7 × 7, 122 MB |
| Đặc trưng val đã trích | 363 ảnh, 18 MB | 320 ảnh, 16 MB |

Dùng chung cho cả hai: tập test 1.005 ảnh (311 bình thường, 380 khói, 314 lửa), đặc trưng đã trích 51 MB, lưu một lần tại `outputs/model/shared`. Tập test chỉ được dùng sau khi hai mô hình đã tổng hợp và cập nhật trọng số, không dùng trong huấn luyện cục bộ.

Mức lệch giữa hai client (khói 80/20, lửa 20/80, bình thường 50/50) tạo ra phân bố không đồng nhất có chủ đích. Mỗi client vẫn có đủ ba lớp để học ranh giới giữa các lớp. Hai tập val nhỏ ở lớp thiểu số (client2 chỉ 50 ảnh khói, client1 chỉ 42 ảnh lửa) nên các chỉ số từng lớp ở những ô này sẽ dao động.

## 6. Cấu trúc mã nguồn

```
src/model/
  config.yaml          cấu hình dùng chung cho hai client
  common/
    paths.py           đường dẫn dữ liệu và kết quả theo từng client
    define_model.py    dựng SqueezeNet, thay đầu 3 lớp, tách thân và đầu
    finetune.py        nạp trọng số ImageNet, đóng băng lớp, thống kê tham số
    data.py            nạp ảnh, trích đặc trưng, lưu và đọc cache
    evaluate.py        loss, accuracy, precision, recall, F1, ma trận nhầm lẫn
    train.py           vòng huấn luyện 150 epoch, lưu kết quả
    pi4_guard.py       import là tự áp giới hạn Pi 4 (gọi secure_fl/devicelimit.py), đặt ở đầu mọi script chạy trên thiết bị
  client1/  define_model.py  finetune.py  extract_features.py  train.py  evaluate_test.py
  client2/  define_model.py  finetune.py  extract_features.py  train.py  evaluate_test.py
  run_fedavg.py  run_experiments.py  compare_local.py
```

Phần xử lý nằm ở `common/`, mỗi thư mục client chỉ là lớp mỏng gắn đúng dữ liệu và đầu ra của client đó, nên sửa một chỗ thì cả hai client cùng đổi.

## 7. Quy trình chạy

Chạy từ thư mục gốc của dự án, PowerShell, lần lượt từng lệnh. Mọi lệnh đều là `python <tên file>`; giới hạn Pi 4 được script tự áp (mục 8).

| Bước | Lệnh | Kết quả |
|---|---|---|
| 1-2. Trích đặc trưng | `python src/model/client1/extract_features.py`, `python src/model/client2/extract_features.py` | Cache `.npz` đặc trưng train/val của từng client; client1 còn trích tập test dùng chung |
| 3-4. Huấn luyện cục bộ | `python src/model/client1/train.py`, `python src/model/client2/train.py` | `outputs/model/<client>/run/` |
| 5-6. Đánh giá test | `python src/model/client1/evaluate_test.py`, `python src/model/client2/evaluate_test.py` | `outputs/model/<client>/test/` |
| 7. Ghép bảng | `python src/model/compare_local.py` | `outputs/model/shared/` (không phải bước của thiết bị, không giới hạn) |
| 8. Đo thời gian 1 epoch | `python src/secure_fl/experiments/bench_train.py classifier` | `outputs/secure_fl/timing_classifier.json` |
| 9. FedAvg tham chiếu | `python src/model/run_fedavg.py` | `outputs/model/fedavg_50/` |
| 10. So sánh lock/không lock | `python src/secure_fl/experiments/run_fl_tcp.py --seed 42` rồi `python src/secure_fl/experiments/analyze.py` | `outputs/secure_fl/tcp/` |
| 11. Nhiều seed (tùy chọn, lâu) | `python src/model/run_experiments.py` | `outputs/model/experiments/so_sanh/` |

Kết quả huấn luyện lưu ở `outputs/model/<client>/run/`: `history.csv` (từng epoch), `metrics.json` (tổng kết và ma trận nhầm lẫn), `curves.png` (đường cong loss, accuracy, tốc độ học), `final_head.pt` và `weights.npy` (trọng số của mô hình cuối, vector 1.539 số dùng cho bước tổng hợp). Kết quả huấn luyện 150 epoch trình bày ở `bao_cao_huan_luyen_mo_hinh.md`.

Hai script kiểm tra riêng lẻ: `python src/model/client1/define_model.py` in 724.035 tham số tổng và 198.723 ở đầu `fire9` + classifier (chỉ in cấu trúc, không gọi giới hạn); `python src/model/client1/finetune.py` cho thấy chỉ `classifier` ở trạng thái huấn luyện, 1.539 tham số (chạy trong giới hạn).

## 8. Giới hạn tài nguyên Pi 4: cách làm và bằng chứng

| Tài nguyên | Giới hạn mỗi tiến trình thiết bị | Cách áp |
|---|---|---|
| CPU | 1,6 nhân tương đương | Windows Job Object, CPU rate hard cap = 1,6 / 12 luồng logic = 13,33% tổng CPU máy (đọc lại: tương đương 1,5996 nhân) |
| RAM | 4 GB | Trần bộ nhớ cam kết (commit) 4096 MiB cho tiến trình; cấp phát vượt trần thì lỗi bộ nhớ |
| Số luồng PyTorch | 2 | `threads: 2` trong `src/model/config.yaml` |
| GPU | Không dùng | Chỉ chạy CPU |

**Cách áp.** Mã ở `src/secure_fl/devicelimit.py` (`enforce`): tạo Job Object bằng `ctypes`, gán chính tiến trình đang chạy vào job, rồi đọc lại giới hạn bằng `QueryInformationJobObject`. Các script trong `src/model` gọi qua `from common import pi4_guard` (chỉ cần import); `client.py` và `bench_train.py` gọi `devicelimit.enforce` trực tiếp. Giới hạn **bắt buộc và không có cờ tắt**: nếu không áp được thì script dừng; máy không phải Windows và không chạy trong Docker (biến `DEVICE_LIMIT_BY=docker`) thì từ chối chạy. Giá trị lấy từ mục `device` của `src/secure_fl/config.yaml` (profile `raspberry_pi_4b`, 1,6 nhân, 4g). Job được gán sau khi tiến trình đã khởi động (vài mili giây), nên đoạn nạp thư viện ban đầu chưa nằm trong giới hạn.

**Bằng chứng mỗi lần chạy.** `outputs/device_runs/<bước>_<giờ>/` gồm `output.log` (toàn bộ đầu ra), `run.json` (lệnh, giờ bắt đầu/kết thúc, có lỗi chưa xử lý hay không) và `device_limits.json` (giới hạn đọc lại từ Windows cùng mức dùng thực tế). Ở lượt so sánh lock/không lock, mỗi client ghi `device_limits_client<k>.json` vào thư mục từng arm.

Kết quả đo ở lượt chạy mới nhất (đọc từ các file trên; giới hạn đọc lại đều là 1,60 nhân / 4096 MiB, CPU hard cap bật):

| Bước | Thời gian thực (s) | Thời gian CPU (s) | Số nhân TB | RAM vật lý đỉnh (MiB) | Commit đỉnh (MiB) |
|---|---|---|---|---|---|
| 1. Trích đặc trưng client1 (cả test) | 35 | 40 | 1,13 | 855 | 1.718 |
| 2. Trích đặc trưng client2 | 26 | 29 | 1,11 | 1.142 | 1.628 |
| 3. Huấn luyện 150 epoch client1 | 254 | 274 | 1,08 | 468 | 856 |
| 4. Huấn luyện 150 epoch client2 | 237 | 254 | 1,07 | 456 | 845 |
| 5. Đánh giá test client1 | 7 | 6 | 0,80 | 376 | 769 |
| 6. Đánh giá test client2 | 4 | 4 | 0,98 | 376 | 769 |
| 8. Đo thời gian 1 epoch | 24 | 29 | 1,18 | 498 | 859 |
| 9. FedAvg tham chiếu (2 client, 1 tiến trình) | 176 | 189 | 1,07 | 649 | 1.034 |
| 11. Nhiều seed (2 client, 1 tiến trình) | 1.977 | 2.682 | 1,36 | 1.273 | 2.262 |

Số đo này chỉ cho biết các bước chạy được trong giới hạn 1,6 nhân / 4 GB và mức RAM cần; **không phải thời gian trên Pi 4 thật**. Hai bước 9 và 11 gồm cả hai client trong một tiến trình nên RAM đỉnh là của cả hai.

**Kiểm thử cơ chế.** `tests/secure_fl/test_device_guard.py` (5 bài) kiểm tra mọi script thiết bị đều có dòng áp giới hạn, không có công tắc tắt, và chạy thật: cùng một đoạn mã xin 400 MiB thì lỗi bộ nhớ dưới trần 200 MiB và qua dưới trần 4 GiB. `test_devicelimit.py` (4 bài) kiểm tra việc đọc lại giới hạn và trần CPU.

Việc còn lại:
1. Đo hệ số quy đổi thời gian máy giả lập → Pi 4 thật (giả lập hiện không làm chậm CPU).
2. Chạy lại mã hóa OpenFHE thật trong Docker (compose đã đặt `cpus`/`mem_limit` và `run_fl_docker.py` ghi `docker_limits.json`); lượt OpenFHE thật ngày 30/10/2026 chưa có bằng chứng giới hạn.
3. Giai đoạn UAV và kênh vô tuyến.

## 9. Hạn chế

1. Giả lập không phải phần cứng thật: tốc độ, bộ nhớ đệm và tần số của Pi 4 khác máy giả lập; giả lập **chỉ giới hạn số nhân và RAM**, không làm CPU chậm, nên mọi thời gian đo vẫn nhanh hơn thiết bị thật và chưa có hệ số quy đổi.
2. Trần RAM trên Windows là trần bộ nhớ cam kết, không phải RAM vật lý; giới hạn được gán sau khi tiến trình đã khởi động.
3. Bước 9 và 11 chạy hai client trong một tiến trình, dùng chung một giới hạn; thời gian và RAM của chúng không tách được theo client.
4. Chỉ cách ly dữ liệu theo quy ước thư mục; hệ điều hành chỉ ép buộc giới hạn CPU/RAM.
5. Dữ liệu ảnh khói đến từ một nguồn camera nên mô hình có thể học đặc trưng nguồn thay vì khói; ảnh khói bị kéo giãn khi đổi về 128 × 128 khác với hai lớp còn lại. Các hạn chế dữ liệu chi tiết nằm ở báo cáo dữ liệu.
6. Báo cáo này mô tả cấu hình và cách giả lập, không kết luận về độ chính xác; kết quả độ chính xác nằm ở `bao_cao_huan_luyen_mo_hinh.md`, `bao_cao_fedavg.md`, `bao_cao_so_sanh_nhieu_seed.md` và `bao_cao_so_sanh_ma_hoa_khong_mahoa.md`.
