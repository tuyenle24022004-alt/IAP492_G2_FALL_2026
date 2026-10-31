# Kế hoạch thực hiện đồ án

**Đề tài:** Học liên kết (FL) bảo toàn quyền riêng tư cho thiết bị IoT qua UAV chuyển tiếp AF với đường lên NOMA: so sánh mã hóa đồng cấu đa khóa 100% (CKKS) và FAS với không mã hóa.
**Người thực hiện:** Phan Hồng Quí (FPT).
**Cập nhật:** 30/10/2026 (thay bản 29/10/2026, hướng `fixed10`/`adaptive` và CIFAR-10 đã bỏ).
**Tạm hoãn (30/10/2026, theo người dùng): đánh giá tấn công** (rò rỉ, cổng 2, Q4). Công tắc `lock.attack_enabled: false`; mã và dữ liệu `capture/`, `truth/` giữ nguyên để bật lại khi người dùng yêu cầu. Các mục liên quan bên dưới đánh dấu "(tạm hoãn)".

---

## 1. Mục tiêu

1. FL nhận dạng khói và lửa (3 lớp) giữa 2 thiết bị biên hạn chế tài nguyên, gửi cập nhật lên trạm gốc (BS) qua một UAV đứng yên làm nút khuếch đại–chuyển tiếp (AF), hai thiết bị dùng chung tài nguyên bằng NOMA.
2. So sánh ba phương án bảo vệ cập nhật mô hình:
   - **none** (không lock): gửi Δ rõ.
   - **ckks_full** (lock A): mã hóa 100% bằng xMK-CKKS đa khóa.
   - **fas** (lock B): p = 10% mã hóa xMK-CKKS, phần còn lại thêm nhiễu và xáo vị trí bằng khóa chỉ hai thiết bị giữ.
3. Đánh giá bằng chỉ số cụ thể (độ chính xác FL, truyền thông, thời gian, tài nguyên thiết bị; rò rỉ: tạm hoãn), rồi **chọn phương pháp mã hóa tốt nhất** theo ba cổng (độ chính xác, bảo mật (tạm hoãn), khả thi), có điều kiện áp dụng. Khi cổng bảo mật đang tắt, kết quả chỉ là xếp hạng sơ bộ.

## 2. Phạm vi

| Trong phạm vi | Ngoài phạm vi (hướng phát triển) |
|---|---|
| 2 thiết bị, 1 UAV đứng yên, 1 BS | Nhiều thiết bị, UAV di động, tối ưu quỹ đạo |
| Đường lên mô hình hóa (kênh, AF, NOMA, SIC); có UAV và không UAV | Mô hình hóa đường xuống (giả định lý tưởng) |
| Mô hình lớp cuối (1.539 tham số); `fire9_classifier` (198.723) là mở rộng tùy chọn | Chọn tỷ lệ mã hóa thích nghi theo kênh |
| Thiết bị giả lập giới hạn như Raspberry Pi 4 | Đo trên phần cứng thật, đo năng lượng |
| Mô hình đe dọa thụ động (BS tò mò) làm giả định thiết kế; **đánh giá tấn công BS dựng lại cập nhật của client: tạm hoãn** | Tấn công chủ động, thông đồng, trao đổi khóa X25519 |

## 3. Câu hỏi đánh giá

- **Q1.** UAV cải thiện đường lên bao nhiêu so với gửi thẳng tới BS (tốc độ, thời gian vòng, tỷ lệ vòng trễ hạn)? Mã hóa có khả thi khi không có UAV không?
- **Q2.** Lock làm giảm độ chính xác FL bao nhiêu so với không lock? (kiểm tra tương đương theo cặp seed, biên δ = 0,5 điểm)
- **Q3.** Chi phí của lock nằm ở tính toán hay ở truyền dữ liệu? Phương án nào rẻ hơn, ở mô hình nào?
- **Q4 (tạm hoãn).** Lock che được gì mà không lock để lộ? BS dựng lại được cập nhật của client k tốt đến đâu, và FAS khác `ckks_full` thế nào? Chưa có số liệu; chỉ có mô tả theo thiết kế.
- **Q5.** Phương pháp nào tốt nhất, trong điều kiện nào? (FAS có lợi khi nào, ví dụ khi số ciphertext tiết kiệm được lớn)

## 4. Tiến độ

| # | Hạng mục | Trạng thái | Ghi chú |
|---|---|---|---|
| 1 | Phân tích dữ liệu khói/lửa | Xong | `report/bao_cao_du_lieu.md` |
| 2 | Mô hình, huấn luyện cục bộ, giả lập thiết bị | Xong | `report/bao_cao_huan_luyen_mo_hinh.md`, `bao_cao_gia_lap_thiet_bi.md`; chưa chạy trong container giới hạn Pi 4 |
| 3 | FedAvg không mã hóa (mốc không lock), nhiều seed | Xong | `report/bao_cao_fedavg.md`, `bao_cao_so_sanh_nhieu_seed.md` (classifier 97,83 ± 0,42%) |
| 4 | Mô hình kênh (`src/uav_channel/channel`) | Xong, **chưa dùng để đo** | test_channel đạt, trùng tham chiếu |
| 5 | UAV relay, bóp tốc độ, thời gian ảo (`src/uav_channel/uav`) | Xong, **chưa dùng để đo** | test_uav_relay đạt (5 MB ở 1 Mbit/s: 40,02 s) |
| 6 | Gói `src/secure_fl/security/` (none, ckks_full, fas chia theo vai trò client/BS), test | Xong với backend mô phỏng | test_security, test_protocol đạt; test OpenFHE bị bỏ qua vì máy không có thư viện |
| 7 | FL client ↔ BS qua TCP: trọng số 150 epoch -> bảo vệ -> BS tổng hợp -> giải mã -> 50 vòng × 1 epoch (mỗi vòng bảo vệ trọng số); 10 arm, seed 42; cổng 1 (tấn công ngoại tuyến và cổng 2: tạm hoãn) | Đang chạy | `src/secure_fl/experiments/run_fl_tcp.py`; thiết kế cũ (Δ từ mô hình khởi tạo, 20 vòng) lưu ở `outputs/secure_fl/thiet_ke_cu_delta_tu_g0/` |
| 8 | Báo cáo so sánh lock và không lock | Đã sinh (không có phần bảo mật) | `report/bao_cao_so_sanh_ma_hoa_khong_mahoa.md` từ `make_report.py`, kết quả OpenFHE thật; phần rò rỉ ghi "chưa đánh giá" |
| 8b | Đánh giá tấn công (BS dựng lại trọng số client k; mở rộng: đoán vị trí phần rõ FAS bằng mô hình công khai, thống kê phần rõ đã xáo, cos trên (v̂ − g)) | **Tạm hoãn** | bật bằng `lock.attack_enabled: true` khi người dùng yêu cầu |
| 9 | Mã hóa THẬT bằng OpenFHE trong container: test_openfhe, chạy `run_fl_docker.py`, đo lại kích thước ciphertext, thời gian mã hóa/giải mã, RAM | **Đang làm: test_openfhe đạt, chạy thử 3 container đạt; chưa chạy đủ 10 arm × 50 vòng** | thay các số `he.*` cũ trong config bằng số đo |
| 10 | Chốt tham số chưa được duyệt: T_max, δ, λ, thứ tự ưu tiên mã hóa | Chờ người dùng | hiện T_max = 60 s, δ = 0,5 điểm là giá trị tạm |
| 11 | `fire9_classifier` (mở rộng) | Chưa | cần trích đặc trưng khác; chi phí byte đã tính trong `cost_time.py` |
| 12 | Thêm UAV và kênh vào luồng client ↔ BS | Chưa | client/BS đã là tiến trình/container riêng nói chuyện qua TCP |
| 13 | Đo thời gian huấn luyện trong container giới hạn Pi 4 (1,6 nhân, 4 GB) | Chưa | thay `bench_train.py` chạy ngoài container |
| 14 | Viết báo cáo/luận văn | Chưa | Chương 2 đã có bản nháp (`docs/Chuong2_Tong_quan_tai_lieu.docx`) |

## 5. Ma trận thí nghiệm

| | none | ckks_full | fas (p = 10%, λ ∈ {0; 0,5; 1; 3}) | fas, BS giữ K (mốc yếu) |
|---|---|---|---|---|
| **Độ chính xác FL** (không phụ thuộc kênh) | ✓ 5 seed | ✓ 5 seed | ✓ 5 seed | ✓ λ ∈ {1; 3} |
| **Byte thật trên dây, thời gian pha (localhost)** | ✓ | ✓ | ✓ | ✓ |
| **Có UAV / không UAV** — thời gian vòng theo kênh | chưa đo | chưa đo | chưa đo | — |
| **Rò rỉ** (BS dựng lại trọng số client k) — **tạm hoãn**, chưa có số liệu trong báo cáo | — | — | — | — |

Độ chính xác không phụ thuộc kênh vì giao thức không bỏ thiết bị nào, nên chỉ cần chạy một lần cho mỗi phương án; kênh chỉ tác động thời gian và tỷ lệ trễ hạn
(giai đoạn UAV: `src/uav_channel/cost_time.py` sinh 2.000 vòng kênh để lấy phân vị). Thêm arm `none_rerun` (chạy lại none) làm mốc nhiễu nền.

## 6. Quy tắc chọn phương án tốt nhất

Các cổng lần lượt (tham số ở `src/secure_fl/config.yaml` mục `lock`; hiện chỉ áp dụng **cổng 1**, cổng 2 tạm tắt), rồi xếp hạng theo chi phí:

1. **Độ chính xác:** cận dưới KTC 95% của (acc − acc_none) theo cặp seed ≥ −δ (không thua none quá δ).
2. **Rò rỉ (tạm hoãn, `attack_enabled: false`):** skill = 1 − (sai số BS dựng lại trọng số v_k / sai số khi đoán bằng phần tổng BS vốn biết)² ≤ `leak_skill_margin`.
3. **Khả thi (giai đoạn UAV, chưa đo):** tỷ lệ vòng trễ hạn ≤ `late_max` ở T_max, theo từng kênh.

Qua các cổng đang bật thì xếp theo byte lên mỗi vòng, rồi thời gian vòng p50. Khi cổng 2 đang tắt, kết quả chỉ là xếp hạng SƠ BỘ, không phải kết luận phương pháp tốt nhất. Báo cáo nêu điều kiện (mô hình, kênh) mà kết luận đúng; không kết luận chung nếu `classifier` và `fire9_classifier` cho kết quả khác nhau.

## 7. Rủi ro

| Rủi ro | Cách xử lý |
|---|---|
| OpenFHE không chạy trên Windows; Docker Desktop chưa cài | Kết quả hiện có dùng backend mô phỏng và ghi rõ; sau khi cài Docker chạy `run_fl_docker.py` để có kết quả mã hóa thật |
| Số đo kích thước ciphertext, thời gian HE là số cũ | Đo lại khi chạy trong container; trong lúc chờ ghi nguồn (commit `0babbe5^`) |
| FAS không có lợi với mô hình 1.539 tham số (cùng 1 ciphertext như `ckks_full`) | Nêu thẳng trong kết quả; thêm `fire9_classifier` để xem điều kiện FAS có lợi |
| Kênh không UAV có đuôi phân bố rất dài | Báo cáo trung vị, p90, p99 và tỷ lệ trễ hạn; dùng thời gian ảo |
| Chênh lệch độ chính xác nhỏ so với dao động giữa các seed | Kiểm tra tương đương theo cặp seed; không kết luận từ một seed |
| Đổi tham số giữa chừng | Tham số chốt ở `config.yaml`; đổi thì chạy lại thí nghiệm bị ảnh hưởng |
| Chọn tham số (λ, p) theo tập test làm kết quả lạc quan | Chọn theo tập val, chấm test một lần |
