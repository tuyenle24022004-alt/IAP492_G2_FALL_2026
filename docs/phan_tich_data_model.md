# Phân tích dữ liệu và mô hình

Nguồn: `tools/prep_data.py`, `src/common/model.py`, `src/iot/train.py`, `config.yaml`, bảng đo `data/costs/` (máy i9-11950H, giới hạn 1,6 CPU / 4 GB, quy đổi Pi 4 ×1,4).
Ngày 30/10/2026. Máy phân tích không có `data/features/`, `data/weights/`: các số dưới đây tính từ code và bảng đo, chưa chạy lại mô hình.

---

## 1. Dữ liệu

### 1.1 Luồng xử lý

```
CIFAR-10 (ảnh JPEG 32×32, repo YoongiKim)
  → resize 112×112 (bilinear), chuẩn hóa mean/std ImageNet
  → thân SqueezeNet 1.1 ĐÓNG BĂNG (features[0:12], trọng số ImageNet)
  → đặc trưng 512 × 6 × 6, lưu float16            (trích MỘT LẦN, ~6,75 ms/ảnh thang Pi 4)
  → tách 3 tập + chia 2 thiết bị
```

### 1.2 Các tập

| Tập | Số ảnh | Cách tạo | Ai dùng | Dung lượng (fp16) |
|---|---|---|---|---|
| train / client1 | 22.500 | 45.000 ảnh còn lại sau khi tách val, chia đôi (IID: hoán vị ngẫu nhiên theo seed) | chỉ iot1 | ≈ 829 MB |
| train / client2 | 22.500 | như trên | chỉ iot2 | ≈ 829 MB |
| val | 5.000 | 500 ảnh/lớp, rút từ 50.000 ảnh train gốc, nguồn ngẫu nhiên riêng `[seed, 31]` | iot1, theo dõi mỗi vòng | ≈ 184 MB |
| test | 10.000 | tập test gốc CIFAR-10 | iot1, chỉ để báo cáo | ≈ 369 MB |

Mỗi ảnh: 512 × 36 = 18.432 giá trị × 2 byte = **36.864 byte**. Ba tập không trùng ảnh. IID: 2 thiết bị bằng nhau nên trọng số FedAvg = 0,5 / 0,5.
Non-IID (Dirichlet α = 0,5 theo từng lớp) có trong code nhưng không thuộc phạm vi hiện tại.

### 1.3 Nhận xét về dữ liệu

1. **Không có tăng cường dữ liệu.** Đặc trưng được trích một lần rồi dùng lại mọi epoch, nên không áp được lật, cắt ngẫu nhiên… Đây là đánh đổi có chủ đích (huấn luyện nhẹ cho Pi 4), nhưng làm trần độ chính xác thấp hơn và mô hình dễ quá khớp khi tăng số epoch. Nên ghi vào giới hạn ở Chương 3.
2. **Ảnh phóng 32 → 112.** Thân SqueezeNet huấn luyện ở 224×224; dùng 112×112 giảm 4 lần tính toán nhưng đặc trưng chỉ còn lưới 6×6. Ảnh CIFAR gốc 32×32 nên phóng thêm cũng không thêm thông tin; lựa chọn hợp lý, nên nêu lý do trong luận văn.
3. **Nguồn ảnh là JPEG** (repo YoongiKim), không phải bản nhị phân gốc của CIFAR-10, nên có nén mất mát nhẹ. Ảnh hưởng nhỏ nhưng cần ghi đúng nguồn để tái lập.
4. **Bộ nhớ:** đặc trưng mỗi thiết bị ≈ 0,83 GB, đọc kiểu mmap theo lô nên không phải nạp hết vào RAM. RSS đỉnh đo được 1,35 GB < giới hạn 4 GB.
5. **Tách val theo lớp đều (500/lớp)** và cố định khi đổi IID/non-IID — tốt, vì đường val giữa các cấu hình so được với nhau.

---

## 2. Mô hình

### 2.1 Kiến trúc

Đầu vào thiết bị là đặc trưng 512×6×6. Phần **được huấn luyện và truyền đi** gồm fire9 + classifier của SqueezeNet 1.1:

| Khối | Lớp | Hình dạng trọng số | Số tham số | Tỷ lệ |
|---|---|---|---|---|
| fire9 | squeeze 1×1 (512 → 64) | 64×512×1×1 + 64 | 32.832 | 16,2% |
| fire9 | expand 1×1 (64 → 256) | 256×64×1×1 + 256 | 16.640 | 8,2% |
| fire9 | expand 3×3 (64 → 256) | 256×64×3×3 + 256 | 147.712 | **73,0%** |
| classifier | Dropout 0,5 → conv 1×1 (512 → 10) → ReLU → AvgPool | 10×512×1×1 + 10 | 5.130 | 2,5% |
| **Tổng** | | | **202.314** | 100% |

- Lớp conv cuối (10 lớp) khởi tạo N(0; 0,01) bằng generator riêng theo `seed` → hai thiết bị tự dựng ra **cùng w0**, không cần gửi mô hình qua mạng.
- Không có BatchNorm → cập nhật chỉ gồm trọng số, không có thống kê chạy cần đồng bộ.
- Huấn luyện: SGD lr 0,01, momentum 0,9, weight decay 5e-4, lô 64; bộ tối ưu **tạo mới mỗi vòng** (momentum không mang sang vòng sau — chuẩn trong FL). 1 epoch = 352 lô.

### 2.2 Vùng được mã hóa ở p = 10%

`priority_order` đảo thứ tự các khối tham số (khối gần đầu ra trước). Với m = round(0,1 × 202.314) = **20.231** giá trị:

| Thứ tự | Khối | Số giá trị lấy | Lũy kế |
|---|---|---|---|
| 1 | classifier bias + weight | 5.130 | 5.130 |
| 2 | expand 3×3 bias | 256 | 5.386 |
| 3 | expand 3×3 weight (một phần) | 14.845 / 147.456 | 20.231 |

→ Phần HE gồm **toàn bộ classifier** và khoảng **26 / 256 bộ lọc đầu tiên của expand 3×3** (mỗi bộ lọc 576 giá trị). Toàn bộ squeeze, expand 1×1 và ~90% expand 3×3 đi dạng rõ (nhiễu + xáo).
Ý nghĩa: classifier là phần mang thông tin lớp rõ nhất và là phần đầu tiên kẻ tấn công nhắm tới, nên được che hoàn toàn. Nhưng 26 bộ lọc được chọn chỉ do vị trí trong bộ nhớ, không phải do độ nhạy. Nên ghi rõ điều này khi so với FedML-HE / MaskCrypt (chọn theo độ nhạy).

### 2.3 Nhận xét về mô hình

1. **ReLU trên logit.** Classifier của torchvision kết thúc bằng ReLU rồi AvgPool, nên logit luôn ≥ 0. Đây là thiết kế gốc của SqueezeNet, chạy được, nhưng làm gradient bằng 0 khi logit âm và có thể làm chậm hội tụ ở các vòng đầu. Giữ nguyên để khớp SqueezeNet gốc là hợp lý; nên nhắc một câu.
2. **Tỷ lệ mã hóa có ý nghĩa nhờ khối huấn luyện lớn.** Nếu chỉ huấn luyện classifier (5.130 tham số) thì mã hóa toàn bộ cũng chỉ 2 ciphertext, ba phương án gần như không khác nhau. Với 202.314 tham số, mã hóa toàn bộ là 50 ciphertext, p = 10% là 5 ciphertext.
3. **Dropout 0,5** trước conv cuối là biện pháp chống quá khớp duy nhất ngoài weight decay (không có tăng cường dữ liệu, mục 1.3).

---

## 3. Dữ liệu và mô hình quy ra chi phí truyền thông (từ bảng đo)

### 3.1 Dung lượng mỗi thiết bị mỗi vòng

Một ciphertext (4.096 slot): **131.819 byte**; phần giải mã δ: **66.334 byte**; một giá trị rõ: 4 byte (float32).
Mỗi ciphertext chở 4.096 × 4 = 16.384 byte dữ liệu → **phình ≈ 8,0 lần**.

| Phương án | Số ct | UPLOAD (byte) | PARTIAL_DEC (byte) | Tổng chiều lên | So với no_he |
|---|---|---|---|---|---|
| no_he | 0 | 809.256 | 0 | 0,81 MB | 1,0× |
| **fixed10** | 5 | 1.387.427 | 331.670 | **1,72 MB** | **2,1×** |
| full_he | 50 | 6.590.950 | 3.316.700 | 9,91 MB | 12,2× |

Kiểm tra: fixed10 UPLOAD = 5 × 131.819 + 182.083 × 4 = 1.387.427 byte, khớp đúng bảng đo.
Chỉ mã hóa 10% tham số nhưng dung lượng chiều lên tăng **2,1 lần**, vì mỗi giá trị mã hóa nặng gấp 8 và phải gửi thêm lượt PARTIAL_DEC.

### 3.2 Thời gian tính toán mỗi vòng (thang Pi 4)

| Pha | no_he | fixed10 | full_he |
|---|---|---|---|
| Huấn luyện 1 epoch (22.500 ảnh) | ≈ 31–32 s | ≈ 31–32 s | ≈ 31–32 s |
| Mã hóa | 0 | 0,05 s | 0,33 s |
| Giải mã từng phần | 0 | 0,04 s | 0,29 s |
| bs cộng + ghép | ≈ 0 | 0,008 s | 0,085 s |

→ **Tính toán HE gần như không đáng kể** (< 1% thời gian huấn luyện, kể cả mã hóa toàn bộ). Chi phí của HE nằm gần như hoàn toàn ở **dung lượng truyền**. Đây là câu trả lời sơ bộ cho câu hỏi Q3, testbed cần xác nhận bằng số đo trên kênh.

### 3.3 Thời gian truyền theo tốc độ kênh

Thời gian = tổng chiều lên × 8 / R (thiết bị chậm hơn quyết định):

| R (Mbit/s) | no_he | fixed10 | full_he |
|---|---|---|---|
| 0,1 (không UAV, kênh xấu) | 65 s | 138 s | 793 s (≈ 13 phút) |
| 0,25 (không UAV, kênh tốt) | 26 s | 55 s | 317 s |
| 1 | 6,5 s | 13,8 s | 79 s |
| 2 | 3,2 s | 6,9 s | 40 s |

Với T_max ≈ 62,9 s và huấn luyện ≈ 31–32 s, còn khoảng **31 s cho truyền**. Muốn kịp hạn cần R tối thiểu:
- no_he ≈ 0,21 Mbit/s;
- fixed10 ≈ 0,44 Mbit/s;
- full_he ≈ 2,6 Mbit/s.

Không UAV (0,09–0,25 Mbit/s) thì fixed10 và full_he gần như luôn trễ hạn. Có UAV thì fixed10 kịp nếu R ≥ 0,44 Mbit/s.

---

## 4. Vấn đề phát hiện

| # | Mức | Vấn đề | Đề xuất |
|---|---|---|---|
| 1 | **Nghiêm trọng** | `config.yaml` đặt `local_epochs: 5`, nhưng toàn bộ bảng chi phí (`cost_fixed.json`, `train_time.json`) đo với **1 epoch** (`train_time.json` ghi `local_epochs: 1`). bs dùng bảng này để tính T_max auto (≈ 62,9 s) và dự báo thời gian vòng. Với 5 epoch, huấn luyện thật ≈ 155–160 s → **mọi vòng đều vượt T_max** và dự báo sai. `scripts/demo.sh` chỉ đo lại khi số epoch khác giá trị trong config, nên không bắt được lỗi này. | Chốt số epoch. Chọn 1 → sửa `config.yaml`. Chọn 5 → đo lại `data/costs/` với 5 epoch. |
| 2 | Trung bình | `cost_fixed.json` đo T_train trên **25.000 ảnh** (thời 2 tập), trong khi mỗi thiết bị hiện có 22.500 ảnh. bs ưu tiên `train_time.json` (đo đúng 22.500 ảnh) nên dự báo vòng vẫn đúng, nhưng T_max auto vẫn lấy 36,93 s từ bảng cũ. | Đo lại `cost_fixed.json` với 3 tập, hoặc cho T_max auto dùng `train_time.json`. |
| 3 | Thấp | Thời gian huấn luyện thô dao động 24,6 – 35,3 s (một lần lệch +40%). | Báo trung vị và độ lệch; chạy đo khi máy không làm việc khác. |
| 4 | Ghi chú | Không có tăng cường dữ liệu; ReLU trên logit; vùng HE chọn theo vị trí chứ không theo độ nhạy. | Nêu trong phần thiết kế / giới hạn. |
