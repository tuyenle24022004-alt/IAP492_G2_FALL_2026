# Kiến trúc testbed mới (viết lại, chỉ lớp cuối)

> **Cập nhật 30/10/2026:** tên thư mục đã đổi. Phần `channel/`, `uav/` nay ở `src/uav_channel/` (CHƯA ĐO trong đề tài hiện tại); `common/`, `security/` và phần mới
> `bs/`, `client/`, `experiments/` ở `src/secure_fl/` (đang đo giao thức client ↔ BS, không UAV). Mã cũ (`src/bs|iot|uav|common`, `tools/`, `scripts/`) đã xoá khỏi
> working tree, còn trong lịch sử git; các câu "giữ nguyên mã cũ" và `tests/ref/` bên dưới đã lỗi thời (nay là `tests/uav_channel/ref/`).
> Cổng quyết định, chỉ số và cách đánh giá hiện hành: `CLAUDE.md` mục 6 và `docs/plan.md`.
> **Tạm hoãn (30/10/2026):** đánh giá tấn công (BS dựng lại cập nhật/trọng số của client) và cổng rò rỉ; công tắc `lock.attack_enabled: false`. Thiết kế (mô hình đe dọa, vai trò BS/client, dữ liệu `capture/`) không đổi.

Tài liệu này thay thế phần BS, UAV và kênh của testbed cũ (`src/bs`, `src/uav`, `src/common`, `src/iot`), giữ lại làm tài liệu tham khảo. Mã mới nằm ở `src/testbed/`, phần học máy dùng lại `src/model/`.

## 1. Quyết định đã chốt

| Mục | Quyết định |
|---|---|
| Phần được huấn luyện | Chỉ lớp phân loại cuối, 1.539 tham số (vừa 1 ciphertext CKKS) |
| Số thiết bị | 2 thiết bị biên (client1, client2), 1 UAV chuyển tiếp, 1 trạm gốc (BS) |
| Ba chế độ bảo vệ so sánh | Không mã hóa, mã hóa 100% bằng xMK-CKKS, FAS |
| Hai kiểu kênh so sánh | Có UAV (AF + NOMA), không UAV (mặt đất trực tiếp) |
| Mã cũ | Giữ nguyên chỉ để đọc hiểu, không sửa, không chạy |

## 2. Nguyên tắc phân chia

Mỗi gói chỉ làm **một việc** và chỉ phụ thuộc vào gói bên dưới nó:

```
Tầng ứng dụng   iot/ , bs/          Giao thức học liên kết (ai gửi gì, khi nào)
                security/           Ba chế độ bảo vệ, cùng một giao diện
                (model/ có sẵn)     Mô hình, huấn luyện, đánh giá
Tầng truyền     uav/                Chuyển tiếp TCP và bóp tốc độ theo R_k
                common/             Khung tin nhắn, kiểu tin nhắn
Tầng vật lý     channel/            Mô hình kênh: suy hao, fading, AF, NOMA, SIC -> SINR, tốc độ
Đo đạc          metrics/            Ghi log mỗi vòng
```

Ba ranh giới quan trọng so với mã cũ:

1. **Kênh vật lý không biết gì về ổ cắm mạng.** `channel/` là hàm thuần (đầu vào: cấu hình, số vòng; đầu ra: SINR và tốc độ), kiểm tra được bằng số liệu mà không cần chạy container.
2. **UAV chỉ chuyển tiếp.** UAV hỏi `channel/` lấy tốc độ rồi bóp luồng; không biết nội dung tin nhắn, không chọn chính sách, không có khóa.
3. **Ba chế độ bảo vệ khác nhau chỉ ở một gói `security/`.** Client và BS gọi cùng một giao diện; thêm hay đổi chế độ không đụng tới giao thức hay mạng.

### Vai trò của UAV và hình học giả định

UAV là trạm **khuếch đại và chuyển tiếp (AF)**: nhận tín hiệu yếu từ hai thiết bị, khuếch đại với độ lợi biến đổi G = P_uav / (công suất nhận + nhiễu) rồi phát sang BS. Nhiễu tại UAV cũng bị khuếch đại theo. Đây là phần **mô hình hóa** (công thức, không đo tín hiệu thật); ở tầng ứng dụng, UAV được hiện thực bằng một bộ chuyển tiếp TCP có bóp tốc độ theo R_k mà mô hình kênh tính ra.

### Hình học và công suất đã chốt (cấu hình mới)

Bản cũ đặt hai thiết bị ở 900 m và 1.200 m so với BS. Bản mới đẩy hai thiết bị ra xa khoảng 2.000 m với khoảng cách khác nhau, đặt lại UAV, và chọn công suất, băng thông bằng cách quét mô hình kênh (kết quả ở mục 3.1). Mọi tọa độ tính bằng mét trên một trục ngang, đổi được trong `src/testbed/config.yaml`.

| Thành phần | Vị trí ngang | Độ cao | Ghi chú |
|---|---|---|---|
| BS | 0 | 25 | |
| UAV (đứng yên) | **1.500** | **100** | Dưới giới hạn bay 120 m; gần thiết bị hơn gần BS (xem 3.1) |
| Thiết bị 1 | **1.800** | 1,5 | Cách UAV 300 m |
| Thiết bị 2 | **2.200** | 1,5 | Cách UAV 700 m |

| Tham số | Giá trị | Lý do |
|---|---|---|
| Công suất phát thiết bị | 23 dBm | Mức tối đa của thiết bị đầu cuối cấp 3 |
| Công suất phát UAV | 30 dBm (1 W) | Tăng lên 33 dBm chỉ thêm khoảng 15% tốc độ |
| Băng thông B | 1 MHz, dùng chung cho cả hai thiết bị | NOMA cho hai thiết bị phát đồng thời trên toàn băng, không chia băng |
| Chia công suất giữa hai thiết bị | NOMA có điều khiển công suất, chọn hệ số giảm công suất của thiết bị mạnh mỗi vòng sao cho min(R1, R2) lớn nhất | Cân bằng tốc độ hai thiết bị (xem 3.1) |
| Tần số sóng mang | 2 GHz | Giữ như bản cũ (tham số Al-Hourani cho đô thị) |

### 3.1 Cơ sở chọn cấu hình (quét bằng mô hình kênh, 400 đến 2.000 vòng kênh ngẫu nhiên mỗi điểm)

Tốc độ dưới đây là **min(R1, R2) trung bình** (Mbit/s), vì thời gian vòng bị thiết bị chậm hơn quyết định và giải mã đa khóa cần cả hai thiết bị.

- **Vị trí UAV (thiết bị ở 1.800 và 2.200 m, độ cao 100 m):** tốc độ tăng dần khi UAV tiến về phía thiết bị, đạt cực đại phẳng ở 1.500 đến 1.600 m (1,12 đến 1,13 Mbit/s), giảm nhẹ khi UAV đi tiếp ra sau thiết bị (1,03 ở 2.000 m) và còn 0,93 khi UAV ở 1.000 m. Lý do: thiết bị phát yếu (23 dBm) còn UAV phát mạnh (30 dBm), nên chặng thiết bị đến UAV là nút thắt, UAV nên đứng gần thiết bị.
- **Độ cao UAV:** tăng độ cao có lợi nhẹ (300 m cho 1,33 Mbit/s so với 1,08 ở 100 m ở x = 1.400 m) nhờ xác suất đường nhìn thẳng cao hơn, nhưng vượt giới hạn bay 120 m nên giữ 100 m.
- **Độ nhạy theo khoảng cách hai thiết bị:** cho từng cặp (2.000 và 2.000), (1.800 và 2.200), (1.500 và 2.500), tốc độ qua UAV chỉ dao động 1,08 đến 1,13 Mbit/s nhờ điều khiển công suất; kênh trực tiếp luôn khoảng 0,011 đến 0,0125 Mbit/s. Cặp 1.800 và 2.200 (chênh khoảng 20%) đủ khác nhau để thể hiện tính không đồng đều mà không làm tốc độ giảm.
- **Điều khiển công suất NOMA:** không điều khiển thì hai thiết bị chênh nhau (1,56 và 0,85 Mbit/s, min trung bình 0,74); có điều khiển thì cân bằng (1,135 và 1,144, min trung bình 1,12), tăng 51% cho thiết bị chậm hơn.
- **Băng thông (UAV ở 1.500 m):** 0,2 MHz cho 0,33 Mbit/s, 1 MHz cho 1,12, 5 MHz cho 2,90, 10 MHz cho 3,82 (tăng dưới tuyến tính vì nhiễu tăng theo băng thông). Kênh trực tiếp gần như không đổi (0,011 đến 0,0125) vì ở SNR rất thấp tốc độ tỉ lệ với công suất chứ không với băng thông.
- **Công suất thiết bị:** giảm 3 dB làm kênh trực tiếp giảm một nửa (12,2, 6,2, 3,1 kbit/s ở 23, 20, 17 dBm) nhưng kênh qua UAV chỉ giảm từ 1,12 xuống 0,95 Mbit/s (23 xuống 17 dBm). Thiết bị càng yếu, lợi thế của UAV càng lớn.

| Cấu hình | Có UAV | Không UAV |
|---|---|---|
| Cũ (UAV 700 m, thiết bị 900 và 1.200 m): min(R1, R2) trung bình | 1,67 Mbit/s | 0,118 Mbit/s (trung vị 0,055) |
| **Mới (UAV 1.500 m, thiết bị 1.800 và 2.200 m)** | **1,11 Mbit/s** (phân vị 10%: 0,76) | **0,0115 Mbit/s** (trung vị 0,0046, phân vị 10%: 0,0005) |

Thời gian truyền mỗi vòng cho một thiết bị với cấu hình mới (từ phân bố kênh 2.000 vòng):

| Kiểu bảo vệ | Có UAV: trung vị / phân vị 99 | Không UAV: trung vị / trung bình / phân vị 99 |
|---|---|---|
| Không mã hóa (6.156 B) | 0,04 s / 0,2 s | 10,6 s / 123 s / 20 phút |
| CKKS 100% (198.153 B) | 1,4 s / 5,2 s | **341 s (5,7 phút) / 3.954 s (66 phút) / 10,9 giờ** |

Hệ quả cần ghi nhớ:
1. **Kênh trực tiếp ở 2.000 m gần như không dùng được cho mã hóa** và có đuôi phân bố rất dài (vài vòng fading sâu chi phối giá trị trung bình), nên báo cáo phải dùng trung vị, phân vị 90, 99 và tỉ lệ vòng trễ hạn, không chỉ trung bình.
2. **Cần chế độ thời gian ảo (`time_mode`)** cho kênh trực tiếp: chạy thời gian thật sẽ mất hàng chục giờ. Bản cũ dùng nén thời gian (dữ liệu đi nhanh k lần rồi nhân thời gian đo với k), nhưng cách này **khuếch đại sai số đo**: với k lên hàng nghìn, độ trễ luồng 30 ms thành 30 giây (đã gặp khi kiểm thử). Bản mới tính thời gian truyền ảo chính xác bằng byte chia R_k và cho dữ liệu đi ngay. Ba chế độ: `real` (chờ thật, dùng cho kênh có UAV), `virtual` (tính ảo), `auto` (ảo khi tốc độ thấp hơn một ngưỡng). Mỗi mục log đánh dấu có phải thời gian ảo hay không; thời gian vòng báo cáo là thời gian tính toán thật cộng thời gian truyền ảo.
3. Tỷ lệ tốc độ UAV so với không UAV là khoảng 97 lần (so với 14 lần ở bản cũ), nên đóng góp của UAV rất rõ.

## 3. Vai trò từng thành phần

| Thành phần | Việc làm | Không làm |
|---|---|---|
| **client (iot)** | Dựng mô hình, huấn luyện cục bộ 1 epoch, bảo vệ trọng số (`security`), gửi UPLOAD, tính phần giải mã nếu cần, cập nhật mô hình, client1 đánh giá trên test | Không biết kênh |
| **BS** | Điều phối vòng, thu UPLOAD, tổng hợp (`security`), ghép phần giải mã, gửi AGGREGATE, ghi log | Không có mô hình đầy đủ, không có khóa bí mật, không chọn kênh |
| **UAV** | Mỗi vòng sinh kênh từ `channel/`, báo CHANNEL_REPORT cho BS, bóp tốc độ chiều lên từng thiết bị, chuyển tiếp chiều xuống tự do | Không đọc nội dung, không giữ khóa |
| **channel/** | SINR và tốc độ R_k mỗi vòng theo chế độ kênh | Không mở ổ cắm |
| **security/** | `none`, `ckks_full`, `fas`: bảo vệ ở client, tổng hợp ở BS, khôi phục kết quả | Không biết mạng |

## 4. Giao diện của `security/`

Mỗi chế độ cài đặt hai nửa, cùng chữ ký:

```
ClientSide.protect(vector, round)  -> payload          # gửi lên BS
ClientSide.finish(aggregate_msg)   -> vector           # nhận lại tổng
ServerSide.aggregate(payloads)     -> aggregate_msg    # BS cộng
ServerSide.needs_decrypt_round     -> bool             # có lượt giải mã đa bên không
```

| Chế độ | UPLOAD chứa | BS thấy | Thêm lượt giải mã |
|---|---|---|---|
| `none` | Trọng số rõ (đã nhân n_k/n) | Trọng số từng client | Không |
| `ckks_full` | 1 ciphertext | Chỉ ciphertext, rồi tổng sau khi ghép | Có (`PARTIAL_DEC`) |
| `fas` | Phần HE (p%) + phần rõ đã thêm nhiễu và xáo | Phần HE không đọc được; phần rõ đã xáo | Có |

FAS có hai biến thể, chọn bằng tham số `key_holder`: `devices` (khóa xáo chỉ ở 2 thiết bị, BS cộng mù) hoặc `bs` (BS giữ khóa xáo như FAS gốc). Với mô hình chỉ 1.539 tham số, FAS có ít ý nghĩa thực tế (phần mã hóa p% vẫn chiếm một ciphertext); đây là điểm cần ghi vào báo cáo.

## 5. Một vòng học liên kết

1. UAV sinh kênh vòng t, đặt R_1, R_2, gửi `CHANNEL_REPORT {t, sinr, rate}` cho BS.
2. BS gửi `ROUND_START {t}` xuống hai client.
3. Client huấn luyện 1 epoch từ trọng số toàn cục, nhân n_k/n, bảo vệ, gửi `UPLOAD`.
4. BS chờ đủ hai UPLOAD, tổng hợp. Nếu chế độ cần giải mã: gửi `CSUM`, client trả `PARTIAL_DEC`, BS ghép.
5. BS gửi `AGGREGATE {w}` cho hai client; client cập nhật mô hình.
6. Client1 đánh giá trên test, gửi `METRICS {t, accuracy, loss}`.
7. BS ghi một bản ghi log của vòng, gửi `ROUND_DONE` cho UAV.

Tốc độ R_k áp cho cả `UPLOAD` và `PARTIAL_DEC`. Chiều xuống không bị bóp. Không bỏ thiết bị nào khỏi vòng: kênh xấu thì vòng chậm.

## 6. Cấu trúc thư mục

```
src/testbed/
  config.yaml           Cấu hình riêng của testbed
  channel/              Tầng vật lý (hàm thuần)
    params.py           Tham số kênh từ cấu hình
    links.py            Suy hao Al-Hourani, 3GPP UMa, fading Rician và Rayleigh
    sinr.py             Sinh SINR: AF, NOMA, SIC, điều khiển công suất
    model.py            ChannelModel: SINR và tốc độ theo vòng
  common/               Khung tin nhắn length-prefixed, kiểu tin nhắn
  security/             none.py  ckks_full.py  fas.py  base.py
  uav/                  relay.py (chuyển tiếp)  shaper.py (bóp tốc độ)
  bs/                   server.py (điều phối)  aggregator.py
  iot/                  client.py  (dùng src/model cho mô hình)
  metrics/              logger.py  bản ghi mỗi vòng
tests/testbed/          Một file kiểm thử cho mỗi bước
```

## 7. Thứ tự dựng, mỗi bước có kiểm thử

| Bước | Nội dung | Kiểm thử đạt khi |
|---|---|---|
| 1 | `channel/` | SINR trùng tới từng bit với kết quả testbed cũ (`tests/ref/channel_ref.json`), tốc độ trùng `channel_round` cũ |
| 2 | `common/` khung tin nhắn | Gửi nhận đủ kiểu, byte đo khớp |
| 3 | `uav/` chuyển tiếp, bóp tốc độ, thời gian ảo | 5 MB ở 1 Mbit/s mất khoảng 40 giây (sai lệch dưới 5%), hai thiết bị cùng lúc; thời gian ảo bằng đúng byte chia R_k |
| 4 | `iot/`, `bs/`, `security/none` | FL 4 container không mã hóa cho cùng độ chính xác với mô phỏng một tiến trình (khoảng 97,8%) |
| 5 | Giới hạn Pi 4 (container) | Thời gian huấn luyện một epoch ổn định (±10%), đo RAM |
| 6 | `security/ckks_full` | Sai số tổng sau giải mã dưới 1e-6, BS không có khóa bí mật |
| 7 | `security/fas` | Tổng đúng khi nhiễu bằng 0, hai client sinh cùng hoán vị |
| 8 | Thí nghiệm | Ma trận 3 chế độ bảo vệ × 2 kiểu kênh × nhiều seed |

## 8. Lấy gì từ mã cũ, bỏ gì

| Lấy lại (viết lại gọn) | Bỏ |
|---|---|
| Mô hình kênh, toàn bộ công thức (`src/uav/channel.py`) | Chọn p thích nghi theo SINR (`adaptive`), bảng chi phí `CostModel` |
| Định nhịp theo đầu tin nhắn (`src/uav/shaper.py`) | Chế độ `uav_oma` (cho kết quả sai trong testbed) |
| Khung tin nhắn, OpenFHE xMK-CKKS (`src/common/protocol.py`, `mkckks.py`, `crypto_setup.py`) | Mọi chế độ chọn p theo SINR |
| Ý tưởng log mỗi vòng, đo thông lượng thực so với R_k; thời gian ảo (thay cho nén `time_scale`, cần cho kênh trực tiếp ở 2.000 m) | Quy đổi thời gian Pi 4 nhét trong `server.py` (tách thành bước báo cáo riêng) |

## 9. Giới hạn cần ghi vào báo cáo

- Tầng vật lý được **mô hình hóa** bằng công thức, không đo tín hiệu thật. Tầng ứng dụng chạy thật.
- Với 2 thiết bị, mã hóa đa khóa không chống được thông đồng; thiết bị này suy ra được cập nhật của thiết bị kia từ tổng.
- BS biết tổng sau khi ghép phần giải mã (như mọi hệ tổng hợp an toàn).
- Độ chính xác không phụ thuộc kênh (giao thức không bỏ thiết bị). Ảnh hưởng của kênh nằm ở thời gian vòng và số vòng trễ hạn.
- Với hình học mới (thiết bị cách BS khoảng 2.000 m), UAV nhanh hơn kênh trực tiếp khoảng 97 lần; ngay cả gói mã hóa nhỏ của lớp cuối (khoảng 198 KB mỗi vòng) cũng mất trung vị 341 giây ở kênh trực tiếp so với 1,4 giây qua UAV. Kết quả phụ thuộc mạnh vào giả định hình học và công suất, cần nêu rõ trong báo cáo.
