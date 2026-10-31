# FL nhận dạng khói và lửa qua UAV relay: so sánh lock (CKKS 100%, FAS) với không lock (đồ án Phan Hồng Quí, FPT)

> **Cập nhật 30/10/2026 (theo người dùng):** bỏ hướng cũ (CIFAR-10, `fixed10`, `adaptive`, chọn p theo SINR, mô hình 202.314 tham số,
> testbed `src/bs|iot|uav|common`). Mã cũ đã xoá khỏi working tree (còn trong lịch sử git, commit `823282b` trở về trước).
> Chỉ làm theo tài liệu này và `docs/kien_truc_testbed_moi.md`.
>
> **Cập nhật 30/10/2026 (theo người dùng): TẠM TẮT đánh giá tấn công.** Công tắc `lock.attack_enabled: false` (src/secure_fl/config.yaml). Khi tắt: `collect.py` không tính tấn công,
> `analyze.py` và `make_report.py` bỏ cổng 2 và hình rò rỉ, bảng chọn chỉ còn cổng 1 và chỉ là xếp hạng SƠ BỘ (chưa xét bảo mật). Mã tấn công KHÔNG bị xoá; `capture/` và `truth/` vẫn được ghi
> nên bật lại (`attack_enabled: true`) là tính được trên các lượt chạy hiện có. Chỉ bật lại khi người dùng yêu cầu. Khi bật lại cần sửa nhãn Δ trong `analyze.py` (nay là trọng số v_k).

## 1. Mục tiêu

Giả lập mạng 2 thiết bị biên (client1, client2) → 1 UAV relay AF đứng yên → trạm gốc (BS), chạy học liên kết (FedAvg) nhận dạng
ảnh 3 lớp (bình thường, khói, lửa). So sánh ba phương án bảo vệ cập nhật mô hình trên các chỉ số cụ thể, từ đó chọn phương pháp tốt nhất:

| Phương án | Bảo vệ | BS thấy |
|---|---|---|
| `none` (không lock) | gửi Δ rõ | Δ từng client |
| `ckks_full` (lock A) | mã hóa 100% bằng xMK-CKKS đa khóa 2-of-2 | chỉ ciphertext; sau khi ghép phần giải mã biết tổng |
| `fas` (lock B) | p = 10% đầu theo thứ tự ưu tiên mã hóa xMK-CKKS; phần còn lại cộng nhiễu N(0,(λ·RMS)²) rồi xáo vị trí bằng π_t | phần HE không đọc được; phần rõ đã nhiễu và xáo |

Biến thể `fas` với `key_holder='bs'` (BS cũng giữ khóa xáo K, như FAS gốc) chỉ là mốc yếu về bảo mật để tách tác dụng của việc ai giữ K.
Mô hình: SqueezeNet 1.1 đóng băng, chỉ huấn luyện lớp phân loại cuối (1.539 tham số = 512×3 + 3, vừa 1 ciphertext 4.096 ô).
Mở rộng tùy chọn: `fire9_classifier` (198.723 tham số, 49 ciphertext khi mã hóa 100%) để FAS có ý nghĩa về chi phí.

## 2. Mô hình đe dọa

- BS và UAV trung thực nhưng tò mò (thụ động); kẻ nghe lén thấy mọi gói. BS không có khóa bí mật HE, không có K (trừ biến thể `fas` mốc yếu).
- BS biết (chấp nhận, ghi là giới hạn): TỔNG sau khi ghép phần giải mã. Với 2 thiết bị, thiết bị này suy ra được cập nhật thiết bị kia.
- Phần giải mã đa bên dùng nhiễu mặc định `FIXED_NOISE_MULTIPARTY` của OpenFHE: về lý thuyết BS tò mò có thể suy thông tin về khóa. Không đổi sang
  `NOISE_FLOODING_MULTIPARTY` (cần modulus lớn hơn) — ghi vào hạn chế.
- FAS ở đây xáo VỊ TRÍ (không xáo bit); nhiễu có độ lệch chuẩn phụ thuộc dữ liệu và không có clipping nên KHÔNG có bảo đảm DP (không có ε).
- Khóa xáo K cài sẵn lúc triển khai, không có bảo mật chuyển tiếp.

## 3. Kiến trúc mã

```
src/model/            học máy (dữ liệu, SqueezeNet, huấn luyện cục bộ, FedAvg không mã hóa, thí nghiệm nhiều seed); config.yaml riêng
src/secure_fl/        PHẦN ĐANG ĐO: client <-> BS qua TCP, KHÔNG có UAV; config.yaml riêng (he, lock)
  common/             khung tin nhắn length-prefixed + msgpack
  security/           none, ckks_full, fas cùng giao diện chia theo vai trò (client: protect / client_share / client_finish;
                      BS: aggregate / bs_fuse / bs_view); he_backend (emulated | openfhe), mkckks, perm (HKDF + π_t)
  bs/server.py        BS: chỉ cộng, không có mô hình/khóa/K (trừ arm fasbs_*); ghi byte thật + capture (dữ liệu cho tấn công ngoại tuyến, hiện tạm không dùng)
  client/client.py    thiết bị: mỗi tiến trình chỉ đọc dữ liệu của mình
  arms.py             danh sách arm (mỗi arm = một lượt FL với một cấu hình bảo vệ)
  experiments/        run_fl_tcp (trên máy, emulated), run_fl_docker (3 container, OpenFHE thật), collect (gộp; tấn công ngoại tuyến tạm tắt), analyze, bench_train
src/uav_channel/      CHƯA ĐO: channel/ (hàm thuần: Al-Hourani, Rician, AF, NOMA + SIC, 3GPP UMa), uav/ (relay, bóp tốc độ), cost_time.py
src/data_understanding/  phân tích dữ liệu
tests/secure_fl/  tests/uav_channel/ (+ ref/)
docker/               Dockerfile + docker-compose (bs, client1, client2); OpenFHE chỉ có wheel Linux x86_64 nên mã hóa thật chạy trong container.
                      Giả lập Pi 4: mục `device` (cpus, mem_limit) trong src/secure_fl/config.yaml; BS không bị giới hạn. Giới hạn BẮT BUỘC và TỰ ÁP trong chính script (không có cờ tắt):
                      mọi script chạy trên thiết bị gọi `devicelimit.enforce` khi khởi động (src/model: `from common import pi4_guard`; client.py, bench_train.py: gọi trực tiếp), nên chỉ cần `python <file>`.
                      Windows: Job Object cho chính tiến trình, ghi outputs/device_runs/<tên>_<giờ>/ (client của run_fl_tcp.py: device_limits_client<k>.json trong thư mục arm);
                      Docker: compose áp (DEVICE_LIMIT_BY=docker), run_fl_docker.py ghi docker_limits.json mỗi arm; máy khác: từ chối chạy.
                      Danh sách lệnh từng bước: README mục "Chạy toàn bộ, từng bước".
```

Giai đoạn hiện tại chỉ đo giao thức client <-> BS (byte thật, độ chính xác FL, thời gian; rò rỉ tạm không đo). Tầng vật lý (kênh, UAV) là mô hình hóa và để giai đoạn sau;
khi đó UAV chỉ chuyển tiếp: không đọc nội dung, không giữ khóa. Đường xuống lý tưởng, không bóp tốc độ. Container iot/bs chưa dựng.

## 4. Luồng thí nghiệm và một vòng

Cái được BẢO VỆ và gửi lên BS là **trọng số mô hình** x_k = (n_k/n) · trọng số_k (không phải Δ), nên tổng chính là FedAvg.
- **Vòng 0:** client nạp trọng số đã huấn luyện cục bộ 150 epoch (`outputs/model/<client>/run/weights.npy`), bảo vệ, gửi BS; BS cộng; hai client giải mã -> mô hình toàn cục ban đầu
  (= "trung bình 1 lần" nhưng qua bảo vệ; nhánh `none` phải ra đúng acc trung bình 1 lần đã có, ≈ 97,0%).
- **Vòng 1..R** (R = `fl.rounds` = 50, `fl.local_epochs` = 1 trong `src/model/config.yaml`): client huấn luyện từ mô hình toàn cục -> trọng số -> bảo vệ -> UPLOAD -> BS cộng
  -> (có mã hóa: CSUM -> PARTIAL_DEC -> BS ghép) -> AGGREGATE -> client giải mã/giải xáo, mô hình toàn cục mới = tổng. Client1 đánh giá trên test mỗi vòng, gửi METRICS.
- Mọi arm (kể cả `none`, `none_rerun`) đi qua đúng quy trình này để so sánh công bằng. FedAvg 50 vòng cũ (`outputs/model/fedavg_50`) bắt đầu từ mô hình khởi tạo, chỉ là tham khảo.
- Không bỏ thiết bị nào khỏi vòng (giải mã đa khóa cần cả hai). Giai đoạn UAV sau này: UAV sinh kênh, đặt R_1, R_2 chiều lên (NOMA quasi-static) cho UPLOAD và PARTIAL_DEC.
- Hiện chỉ seed 42 (trọng số 150 epoch chỉ có cho seed này).
- Nhiễu FAS = λ·RMS(phần rõ) tính trên TRỌNG SỐ (to hơn nhiều so với Δ) nên lưới λ nhỏ: {0; 0,01; 0,03; 0,1; 0,3; 1}.

## 5. Kênh (chưa đo)

`channel.mode` (src/uav_channel/config.yaml): `uav_noma_pc` (AF + NOMA có điều khiển công suất, R_k = B·½·log2(1+γ_k)), `direct_noma` (không UAV, UMa NLoS
+ bóng râm 6 dB, R_k = B·log2(1+γ_k)). Hình học hiện tại: BS (0, 25 m), UAV (1.500, 100 m), thiết bị (1.800 và 2.200 m, 1,5 m), 23 dBm / 30 dBm, 1 MHz, 2 GHz.
Không UAV rất chậm (trung vị min(R1,R2) ≈ 4 kbit/s): báo cáo bằng trung vị, p90, p99, tỷ lệ trễ hạn, không chỉ trung bình.

## 6. Đánh giá lock với không lock

Mọi phương án chạy lại từ cùng g0, cùng seed, cùng dữ liệu (mỗi lượt là một "arm", xem `secure_fl/arms.py`), thêm arm `none_rerun` làm mốc nhiễu nền
(PyTorch không bảo đảm tất định nên hai lượt cùng cấu hình có thể lệch vài ảnh; lượt 31/10/2026 trùng hoàn toàn, 0 ảnh). Chỉ số:
- **FL:** accuracy, macro-F1, loss, recall từng lớp, ảnh sai, ảnh dự đoán khác `none`, ‖w − w_none‖, vòng đạt 97,5%, dao động 5 vòng cuối.
- **Truyền thông (byte thật trên dây):** UPLOAD, CSUM, PARTIAL_DEC, AGGREGATE; số ciphertext; phình so với dạng rõ (6.156 B).
- **Thời gian:** bảo vệ tại client, BS cộng, ghép, giải mã từng phần, vòng đầu-cuối trên localhost (backend emulated không phản ánh thời gian HE thật).
- **Bảo mật: TẠM CHƯA ĐO** (`attack_enabled: false`). Khi bật lại: BS dựng lại trọng số cục bộ của client k từ capture (cos, sai số, accuracy mô hình dựng lại, skill so với việc đoán bằng phần tổng BS vốn biết).
- **Đúng đắn:** sai số tổng < 1e-6; hai client giữ mô hình giống hệt; λ = 0 thì fas trùng none.
Chọn phương pháp tốt nhất qua các cổng (tham số ở `lock:`): (1) cận dưới KTC 95% của (acc − acc_none) theo cặp seed >= −δ (δ = 0,5 điểm; KHÔNG thua quá δ,
không phải "tương đương"; với 1 seed thì dùng ước lượng điểm của trung bình 10 vòng cuối và ghi rõ không có KTC); (2) skill rò rỉ <= `leak_skill_margin` — **TẠM BỎ** khi `attack_enabled: false`. Cổng 3 (tỷ lệ trễ hạn theo kênh) chờ giai đoạn UAV. Qua cổng thì xếp theo byte rồi thời gian vòng.
Khi cổng 2 đang tắt, kết quả chỉ là xếp hạng SƠ BỘ theo độ chính xác và byte; báo cáo không được gọi đó là "phương pháp tốt nhất" và phải nói rõ chưa xét bảo mật.
Ứng viên không gồm none, none_rerun, fas_lam0 (chỉ kiểm tra đúng), fasbs_* (mốc yếu: BS giữ K). Không chọn tham số (λ, p, δ) theo tập test.

## 7. Trạng thái và giới hạn của số liệu

- Máy Windows KHÔNG có OpenFHE (wheel chỉ có cho Linux x86_64). Chạy trực tiếp chỉ được `lock.backend: emulated`: mô hình hóa sai số CKKS (σ = `he.error_sigma`), đủ cho câu hỏi độ chính xác FL
  nhưng KHÔNG chứng minh mã hóa đúng và KHÔNG đo được kích thước/thời gian thật. Mã hóa thật: `run_fl_docker.py` (3 container, Docker Desktop đã cài). Đã kiểm chứng trong container (30/10/2026): `tests/secure_fl/test_openfhe.py` đạt
  (khóa đa bên qua socket, sai số giải mã 4,3e-7, một phần giải mã đơn lẻ không đủ) và chạy thử 3 container 2 vòng cho accuracy trùng `none`. Chưa chạy đủ 50 vòng × 10 arm.
- Giả lập Pi 4 chỉ giới hạn SỐ NHÂN (1,6) và RAM (4 GB, trần commit trên Windows) của client; KHÔNG làm nhân CPU chậm như Cortex-A72 1,5 GHz, nên thời gian đo vẫn nhanh hơn Pi thật. Chưa có hệ số quy đổi (cần đo, plan.md mục 13).
  Lượt chạy nào không có `device_limits.json` (trực tiếp) hoặc `docker_limits.json` (Docker) thì KHÔNG có bằng chứng đã giới hạn, phải ghi rõ như vậy. Kết quả cũ chưa giới hạn: `outputs/secure_fl/tcp_chua_gioi_han_20261030/` và `outputs/secure_fl/docker/` (lượt OpenFHE thật 20:00).
  Lượt MỚI NHẤT có bằng chứng (31/10/2026): các bước 1-11 trong README đã chạy lại từ đầu trong giả lập, bằng chứng ở `outputs/device_runs/` và `device_limits_client<k>.json` của từng arm trong `outputs/secure_fl/tcp/classifier/` (backend `emulated`); báo cáo `report/bao_cao_so_sanh_ma_hoa_khong_mahoa.md` sinh từ lượt này (`make_report.py`, đã kiểm bằng `audit_report.py`), lượt OpenFHE thật cũ chỉ để đối chiếu.
- `he.ct_bytes`, `share_bytes` (src/secure_fl/config.yaml) đã đo thật: 132.121 B và 66.388 B. `t_*_ct_s` vẫn là số CŨ (commit `0babbe5^`) cho tới khi có lượt chạy đủ trong container.
- `lock.delta_acc = 0,005` và `analysis.t_max_s = 60` (uav_channel) là giá trị tạm do trợ lý đặt, chưa được người dùng chốt.
- RAM của máy ảo Docker chỉ khoảng 3,9 GB; hai client mỗi bên giới hạn 4 GB nên nếu container bị tắt vì thiếu bộ nhớ thì tăng RAM trong Docker Desktop.
- (Chỉ khi bật lại tấn công) Kẻ tấn công trong `collect.py` (dựng lại TRỌNG SỐ cục bộ của client k) bỏ qua phần rõ đã xáo của FAS (không có K, không biết vị trí); skill của FAS giữ khóa ở thiết bị bằng 0 theo cách xây dựng,
  và skill của `ckks_full` cũng bằng 0 theo cách xây dựng (ước lượng = mốc). Giả định này cần nêu trong báo cáo. Ý tưởng tấn công mạnh hơn đã bàn nhưng chưa làm: đoán vị trí phần rõ FAS bằng mô hình công khai, thống kê phần rõ đã xáo (cùng π_t cho hai client), đo cos trên (v̂ − g).
- Báo cáo `report/bao_cao_so_sanh_ma_hoa_khong_mahoa.md` hiện KHÔNG có số liệu bảo mật (đã sinh lại với `attack_enabled: false`).
- Thứ tự ưu tiên mã hóa (`security.base.priority_order`) là giả định cố định: khối cuối trước (bias rồi weight), không theo độ lớn.

## 8. Quy ước

- Ngôn ngữ: comment, log, tài liệu bằng tiếng Việt. Mọi tham số nằm trong `config.yaml` tương ứng, không hard-code.
- Python 3.12; PyTorch CPU. Chạy lệnh từ thư mục gốc. Gói `common` trong `src/model` là `src/model/common` (khác `secure_fl.common`).
- KHÔNG tự đổi thiết kế (mô hình đe dọa, tham số CKKS, mô hình kênh, cách tính nhiễu, tiêu chí chọn phương án, thứ tự ưu tiên) khi chưa hỏi người dùng.
- Mỗi bước: viết test nhỏ trong `tests/secure_fl/` hoặc `tests/uav_channel/`, chạy và báo kết quả (kể cả test bị bỏ qua) trước khi sang bước sau.
- Báo cáo trung thực: kết quả từ backend mô phỏng phải ghi rõ là mô phỏng; số đo cũ chưa đo lại phải ghi rõ.
- Không commit hay xoá khi chưa được yêu cầu.
