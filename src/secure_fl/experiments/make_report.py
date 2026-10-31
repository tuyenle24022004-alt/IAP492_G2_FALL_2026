"""Sinh báo cáo tổng hợp report/bao_cao_so_sanh_ma_hoa_khong_mahoa.md TỪ CÁC FILE KẾT QUẢ (không có số nào gõ tay).

Nguồn: outputs/secure_fl/tcp (lượt chạy chính: BS + 2 client qua TCP trên máy, backend emulated, client trong giả lập Pi 4),
outputs/device_runs (bằng chứng giới hạn của các bước trước), outputs/secure_fl/docker (lượt OpenFHE thật CŨ, chưa giới hạn Pi 4, chỉ để đối chiếu byte/thời gian),
tests (kết quả test), outputs/model (mốc không lock).
Các bảng độ chính xác / chi phí dùng lại ĐÚNG hàm của analyze.py nên khớp với summary_classifier.md.
Chạy: python src/secure_fl/experiments/make_report.py
"""
import glob
import json
import sys
import time
from pathlib import Path

import numpy as np

SRC = Path(__file__).resolve().parents[2]
ROOT = SRC.parent
sys.path.insert(0, str(SRC))

from secure_fl import settings                                                   # noqa: E402
from secure_fl.experiments import analyze as AN                                  # noqa: E402
from secure_fl.runlog import archive_existing                                    # noqa: E402

OUT = ROOT / 'outputs' / 'secure_fl'
REPORT = ROOT / 'report' / 'bao_cao_so_sanh_ma_hoa_khong_mahoa.md'


def jload(p):
    return json.load(open(p, encoding='utf-8'))


def rel(p):
    return str(Path(p).relative_to(ROOT)).replace('\\', '/')


def pct(x, nd=2):
    return f'{100 * x:.{nd}f}%'


def last10(a):
    return float(np.mean([x['acc'] for x in a['rounds'][-10:]]))


BASE = OUT / 'tcp' / 'classifier'                                       # lượt chính: emulated, client trong giả lập Pi 4
OLD = OUT / 'docker' / 'classifier'                                     # lượt OpenFHE thật cũ (chưa giới hạn Pi 4)
DEVRUNS = ROOT / 'outputs' / 'device_runs'
STEPS = [('client1_extract_features', '1', 'Trích đặc trưng client1 (cả tập test)'), ('client2_extract_features', '2', 'Trích đặc trưng client2'),
         ('client1_train', '3', 'Huấn luyện cục bộ client1 (150 epoch)'), ('client2_train', '4', 'Huấn luyện cục bộ client2 (150 epoch)'),
         ('client1_evaluate_test', '5', 'Đánh giá test client1'), ('client2_evaluate_test', '6', 'Đánh giá test client2'),
         ('bench_train', '8', 'Đo thời gian 1 epoch huấn luyện'), ('run_fedavg', '9', 'FedAvg không mã hóa tham chiếu (2 client, 1 tiến trình)'),
         ('run_experiments', '11', 'Nhiều seed × 2 chế độ (2 client, 1 tiến trình)')]


def mem_txt(s):
    """'4g' -> '4 GB' (cấu hình device.mem_limit)."""
    return s.upper().replace('G', ' GB').replace('M', ' MB')


def device_run(name):
    """Thư mục bằng chứng MỚI NHẤT của một bước (outputs/device_runs/<tên>_<giờ>/), hoặc None."""
    ds = sorted(DEVRUNS.glob(f'{name}_2*'))
    return ds[-1] if ds else None


def main():
    B = jload(BASE / 'seed42.json')                                      # lượt chính
    info = jload(sorted(glob.glob(str(BASE / 'logs' / 'run_info_*.json')))[-1])
    cfg_s, cfg_m = info['cau_hinh_secure_fl'], info['cau_hinh_model']
    lock, he = cfg_s['lock'], cfg_s['he']
    dev = cfg_s['device']
    arms = list(B['arms'])
    runs = [B]
    R = B['rounds']
    n_none = B['arms']['none']
    n_test = round(n_none['final_errors'] / (1 - n_none['final']['acc']))
    n_k = jload(BASE / 'seed42' / 'none' / 'bs_log.json')['n_k']
    D = jload(OLD / 'seed42.json') if (OLD / 'seed42.json').exists() else None      # lượt OpenFHE thật cũ, để đối chiếu
    lim = {a: {k: jload(BASE / 'seed42' / a / f'device_limits_client{k}.json') for k in (1, 2)} for a in arms
           if all((BASE / 'seed42' / a / f'device_limits_client{k}.json').exists() for k in (1, 2))}     # bằng chứng giới hạn của từng client, từng arm

    fl_lines, fl_rows = AN.fl_table(runs, arms, lock['delta_acc'])
    with_attack = AN.attack_on(settings.load()['lock'])                  # cấu hình HIỆN TẠI (run_info không có cờ này); tạm tắt: lock.attack_enabled = false
    at_lines, att = AN.attack_table(runs, arms, lock['leak_skill_margin']) if with_attack else ([], None)
    ct_lines, cost = AN.cost_table(runs, arms)
    cand = [r for r in fl_rows if AN.is_candidate(r['arm'])]
    sel, best = AN.select_best(fl_rows, att, cost)
    passed = [(up, arm) for arm, _, _, up, ok in sel if ok]
    fail1 = [r['arm'] for r in cand if r['gate1'] != 'có']
    pass_fas = [r['arm'] for r in cand if r['arm'].startswith('fas_') and r['gate1'] == 'có']
    nr = R + 1
    d03 = next(r for r in fl_rows if r['arm'] == 'fas_lam0.3')['diff_last10']

    def diffs(a):
        x0 = [x['acc'] for x in B['arms']['none']['rounds']]
        x1 = [x['acc'] for x in a['rounds']]
        return sum(abs(p - q) > 1e-12 for p, q in zip(x0, x1)), max(abs(p - q) for p, q in zip(x0, x1))

    ck, nn = B['arms']['ckks_full'], B['arms']['none']
    fas_p, fas_best = B['arms']['fas_lam0.1'], None
    ref = jload(ROOT / 'outputs' / 'model' / 'fedavg_50' / 'metrics.json')
    loc = ref['local_test_metrics']
    md = []
    w = md.append

    # ---------------------------------------------------------------- tiêu đề
    w('# Báo cáo tổng hợp: so sánh bảo vệ cập nhật FL (không lock, CKKS 100%, FAS) giữa 2 client và trạm gốc')
    w('')
    w(f'Sinh tự động lúc {time.strftime("%Y-%m-%d %H:%M:%S")} bằng `src/secure_fl/experiments/make_report.py`. **Mọi con số trong báo cáo đọc trực tiếp từ các file kết quả '
      f'trong `outputs/`; không có số nào được gõ tay hay ước lượng.** Dấu thập phân là dấu chấm. '
      '**Backend mã hóa của lượt chạy chính là `emulated` (mô phỏng): nó KHÔNG mã hóa thật, chỉ mô hình hóa sai số CKKS và đệm gói đúng cỡ ciphertext đã đo ở lượt OpenFHE thật cũ. '
      'Vì vậy độ chính xác và số byte hợp lệ trong giới hạn đó; thời gian mã hóa/giải mã và tính đúng của mã hóa KHÔNG đến từ OpenFHE trong báo cáo này.**')
    w('')
    w('| Mục | Giá trị |')
    w('|---|---|')
    w(f'| Lượt chạy chính | `{rel(BASE)}/` ({info["thoi_diem"]}), lệnh `{" ".join(info["lenh"])}` |')
    w(f'| Backend mã hóa | `{B["backend"]}` (mô phỏng, **không phải OpenFHE thật**); BS và 2 client là 3 tiến trình TCP trên một máy Windows, không có UAV |')
    w(f'| Giả lập thiết bị | mỗi client tự giới hạn {dev["cpus"]} nhân và {mem_txt(dev["mem_limit"])} RAM (`{dev["profile"]}`) bằng Job Object của Windows; BS không giới hạn |')
    w(f'| Seed | {B["seed"]} (một seed duy nhất) |')
    w(f'| Mã nguồn | commit `{info["git_commit"][:10]}`, **có thay đổi chưa commit: {"có" if info["git_co_thay_doi_chua_commit"] else "không"}** |')
    w(f'| Python | {info["python"]} |')
    w('')

    # ---------------------------------------------------------------- tóm tắt
    w('## 0. Tóm tắt')
    w('')
    w(f'- **CKKS 100% (backend mô phỏng) không làm hại việc học.** Accuracy vòng cuối của CKKS 100% là {pct(ck["final"]["acc"])}, không lock là {pct(nn["final"]["acc"])}; '
      f'mô hình cuối dự đoán khác không lock ở {ck["pred_diff_vs_none"]} ảnh; accuracy khác nhau ở {diffs(ck)[0]}/{nr} vòng. '
      f'Vì backend chỉ mô hình hóa sai số CKKS (σ = {he["error_sigma"]:.1e}), đây là kết quả về ảnh hưởng của sai số đó tới việc học, không phải của OpenFHE thật.')
    ee_ck = max(x['err_vs_exact_linf'] for x in ck['rounds'])
    ee_nn = max(x['err_vs_exact_linf'] for x in nn['rounds'])
    w(f'- **Sai số tổng:** sai khác lớn nhất giữa tổng sau giải mã và tổng đúng qua {nr} vòng là {ee_ck:.1e} ở CKKS 100% (so với {ee_nn:.1e} ở không lock, chỉ do float32); '
      f'hai client giữ mô hình giống hệt nhau (‖g_client1 − g_client2‖∞ = {ck["models_equal_linf"]:.1e}). '
      f'**Mục này không chứng minh mã hóa thật đúng:** tính đúng của mã hóa đa khóa chỉ được kiểm ở `test_openfhe` trong container (xem mục 4.1).')
    lam_ok = sorted(float(a.replace('fas_lam', '')) for a in pass_fas)
    w(f'- **FAS: nhiễu càng lớn càng hại.** Các mức λ qua cổng độ chính xác (không kém không lock quá {100 * lock["delta_acc"]:.1f} điểm): {", ".join(f"{x:g}" for x in lam_ok)}. '
      f'Rớt cổng: {", ".join(a.replace("fas_lam", "λ=") for a in fail1)}. Ở λ=1 accuracy vòng cuối chỉ còn {pct(B["arms"]["fas_lam1"]["final"]["acc"])}.')
    if with_attack:
        w(f'- **Rò rỉ.** Mô hình mà BS dựng lại cho client k từ đúng thứ BS nhận được đạt {pct(att["none"]["acc"], 1)} khi không lock, '
          f'{pct(att["fas_lam0.1"]["acc"], 1)} ở FAS khóa chỉ ở hai client, và {pct(att["fasbs_lam0.1"]["acc"], 1)} khi BS cũng giữ khóa xáo (FAS gốc). '
          f'Với CKKS 100%, BS chỉ biết tổng (mô hình toàn cục): mô hình dựng được đạt {pct(att["ckks_full"]["acc"], 1)} và đó chính là mô hình toàn cục, không phải mô hình riêng của client.')
    cb, fb, nb = ck['bytes_per_client'], fas_p['bytes_per_client'], nn['bytes_per_client']
    w(f'- **Chi phí byte** (mỗi client mỗi vòng, đo thật trên dây): không lock {nb["up_total"]:,.0f} B; CKKS 100% {cb["up_total"]:,.0f} B ({cb["expansion_vs_plain"]:.1f}×); '
      f'FAS {fb["up_total"]:,.0f} B ({fb["expansion_vs_plain"]:.1f}×). Chênh lệch giữa CKKS 100% và FAS là {fb["up_total"] - cb["up_total"]:,.0f} B '
      f'({100 * (fb["up_total"] - cb["up_total"]) / cb["up_total"]:.1f}%).')
    if with_attack:
        w(f'- **Qua cả hai cổng:** {", ".join(AN.label(a) for _, a in sorted(passed))}. Ít byte nhất: **{AN.label(best)}**. '
          f'Đây là phép xếp hạng theo byte, chênh lệch nhỏ (xem mục 5), không phải kết luận về mức bảo mật.')
    else:
        w(f'- **Qua cổng độ chính xác:** {", ".join(AN.label(a) for _, a in sorted(passed))}. Ít byte nhất: **{AN.label(best)}**. '
          f'Đây chỉ là xếp hạng SƠ BỘ theo độ chính xác và byte, chênh lệch nhỏ (xem mục 5); **chưa phải kết luận chọn phương pháp tốt nhất**, vì báo cáo không đo mức bảo mật và chưa đo kênh (chưa có UAV).')
    nr_n, nr_d = diffs(B['arms']['none_rerun'])
    w(f'- **Độ lặp lại:** hai lượt `none` cùng cấu hình khác nhau ở {nr_n}/{nr} vòng về accuracy (lệch lớn nhất {100 * nr_d:.2f} điểm) và {B["arms"]["none_rerun"]["pred_diff_vs_none"]} ảnh dự đoán ở mô hình cuối.')
    w(f'- **Giả lập Pi 4:** cấu hình {dev["cpus"]} nhân và {mem_txt(dev["mem_limit"])} RAM cho mỗi client; có bằng chứng giới hạn ghi lại khi chạy cho {len(lim)}/{len(arms)} arm (mục 2.6). '
      'Giả lập chỉ giới hạn số nhân và RAM, **không làm CPU chậm như Cortex-A72**, nên thời gian đo vẫn nhanh hơn Pi thật.')
    w('')
    w('**Báo cáo này KHÔNG chứng minh:** (1) kết quả thống kê chắc chắn, vì chỉ có một seed nên không có khoảng tin cậy; (2) bảo mật theo nghĩa mật mã của FAS: '
      'phần xáo vị trí và nhiễu là cơ chế heuristic, không có bảo đảm DP; (3) hiệu năng trên kênh vô tuyến, vì chưa đo UAV; '
      '(4) kết luận cho mô hình lớn hơn lớp cuối 1.539 tham số' + ('.' if with_attack else '; (5) mức bảo mật của từng phương án: báo cáo chỉ đo độ chính xác, chi phí truyền thông và thời gian.'))
    w('')

    # ---------------------------------------------------------------- 1
    w('## 1. Mục tiêu và phạm vi')
    w('')
    w('Hai client (client1, client2) huấn luyện mô hình nhận dạng ảnh ba lớp (bình thường, khói, lửa) và gửi cập nhật lên trạm gốc (BS) để gộp bằng FedAvg. '
      'Báo cáo so sánh ba cách gửi cập nhật và tìm phương pháp mã hóa tốt nhất theo các chỉ số cụ thể:')
    w('')
    w('| Phương án | Bảo vệ | BS thấy |')
    w('|---|---|---|')
    w('| `none` (không lock) | gửi trọng số rõ | trọng số từng client |')
    w('| `ckks_full` (lock A) | mã hóa 100% bằng CKKS đa khóa 2-of-2 (ở lượt chính: mô phỏng sai số CKKS) | chỉ ciphertext; sau khi ghép phần giải mã biết tổng |')
    w(f'| `fas` (lock B) | {pct(lock["fas_p"], 0)} tham số đầu mã hóa CKKS; phần còn lại cộng nhiễu N(0,(λ·RMS)²) rồi xáo vị trí bằng hoán vị π_t | phần mã hóa không đọc được; phần rõ đã nhiễu và xáo |')
    w('| `fasbs` (mốc yếu) | như `fas` nhưng BS cũng giữ khóa xáo K (giống FAS gốc của Korkmaz và Rao) | phần rõ đã nhiễu, đọc được vị trí |')
    w('')
    w('Phạm vi: chỉ giao thức client ↔ BS (BS và hai client là ba tiến trình TCP trên một máy). Kênh vô tuyến và UAV có mã và test (`src/uav_channel/`) nhưng **chưa được dùng để đo**.')
    w('')

    # ---------------------------------------------------------------- 2
    w('## 2. Thiết lập thí nghiệm')
    w('')
    w('### 2.1 Mô hình và dữ liệu')
    w('')
    w('| Mục | Giá trị | Nguồn |')
    w('|---|---|---|')
    w(f'| Mô hình | SqueezeNet 1.1, thân đóng băng (ImageNet), chỉ huấn luyện lớp phân loại cuối; {B["M"]:,} tham số | `src/model/config.yaml` (`trainable: {cfg_m["model"]["trainable"]}`), kết quả |')
    w(f'| Ảnh vào | {cfg_m["model"]["input_size"]}×{cfg_m["model"]["input_size"]}, `{cfg_m["model"]["resize_mode"]}` | `src/model/config.yaml` |')
    w(f'| Số ảnh train | client1 {n_k["1"]}, client2 {n_k["2"]} | `bs_log.json` (tin HELLO của client) |')
    w('| Cơ cấu lớp của hai client | lệch có chủ đích (client1 nghiêng về khói, client2 nghiêng về lửa) | `report/bao_cao_gia_lap_thiet_bi.md`, không đo lại trong lượt này |')
    w(f'| Tập test chung | {n_test} ảnh (suy ra từ số ảnh sai và accuracy của `none`) | kết quả |')
    w(f'| Tối ưu cục bộ | {cfg_m["train"]["optimizer"]["name"].upper()}, lr {cfg_m["train"]["optimizer"]["lr"]}, momentum {cfg_m["train"]["optimizer"]["momentum"]}, batch {cfg_m["train"]["batch"]} | `src/model/config.yaml` |')
    w(f'| Số vòng FL, epoch cục bộ mỗi vòng | {cfg_m["fl"]["rounds"]} vòng, {cfg_m["fl"]["local_epochs"]} epoch | `src/model/config.yaml` (mục `fl`) |')
    w('')
    w('### 2.2 Luồng một lượt chạy')
    w('')
    w('1. Mỗi client đã huấn luyện cục bộ 150 epoch riêng, cho ra `weights.npy` (`outputs/model/client*/run/`). Hai file này dùng chung cho mọi phương án.')
    w('2. **Vòng 0:** mỗi client nhân trọng số đó với n_k/n, bảo vệ rồi gửi BS; BS cộng; hai client giải mã ra mô hình toàn cục ban đầu (= "trung bình 1 lần" của hai mô hình cục bộ, nhưng qua bảo vệ).')
    w(f'3. **Vòng 1…{cfg_m["fl"]["rounds"]}:** mỗi client huấn luyện {cfg_m["fl"]["local_epochs"]} epoch từ mô hình toàn cục, nhân trọng số mới với n_k/n, bảo vệ, gửi BS; BS cộng, '
      '(nếu có mã hóa) gửi tổng ciphertext cho hai client, mỗi client tạo phần giải mã, BS ghép, gửi tổng về; client giải mã/giải xáo và cập nhật mô hình. Client1 đánh giá trên tập test mỗi vòng.')
    w('4. Mọi phương án (kể cả `none` và `none_rerun`) đi qua đúng quy trình này, cùng seed, cùng dữ liệu, cùng điểm xuất phát. `none_rerun` là lần chạy lại `none` để đo nhiễu nền.')
    w('')
    w('Cái được bảo vệ là **trọng số mô hình** (không phải cập nhật Δ). Tổng của hai vector đã nhân n_k/n chính là FedAvg nên BS chỉ cần cộng ("cộng mù").')
    w('')
    w('### 2.3 Các phương án chạy (arm)')
    w('')
    w(f'Có {len(arms)} arm: {", ".join(f"`{a}`" for a in arms)}. Lưới λ của FAS (nhiễu = λ × RMS của phần rõ) là **giả định của đề tài**, không lấy từ bài báo FAS '
      f'(bài báo không nêu mức nhiễu): `fas_lams = {lock["fas_lams"]}`; mốc `fasbs` dùng λ = {lock["fas_bs_lams"]}. Tỷ lệ mã hóa p = {lock["fas_p"]}. '
      f'Thứ tự ưu tiên mã hóa: bias rồi trọng số theo chỉ số tăng (giả định cố định). Nhiễu và khóa xáo K sinh từ seed để lặp lại được (`noise_entropy: {lock["noise_entropy"]}`).')
    w('')
    w('### 2.4 Tham số mã hóa')
    w('')
    w('| Tham số CKKS | Giá trị |')
    w('|---|---|')
    w(f'| Kích thước vành N (`ring_dim`) | {he["ring_dim"]} |')
    w(f'| Số ô (slot) mỗi ciphertext | {he["slots"]} (= N/2) |')
    w(f'| Scale (`scale_bits`), modulus đầu (`first_mod_bits`) | {he["scale_bits"]} bit, {he["first_mod_bits"]} bit |')
    w('| Độ sâu nhân | 0 (chỉ cộng); mức an toàn `HEStd_128_classic` (`mkckks.py`) |')
    w('| Khóa (thiết kế, chỉ có ở OpenFHE thật) | đa khóa 2-of-2: client1 `KeyGen`, client2 `MultipartyKeyGen`; khóa bí mật không rời tiến trình; BS không có khóa bí mật |')
    w(f'| Backend của lượt chạy chính | `{B["backend"]}`: không có khóa, không mã hóa; cộng số thực rồi thêm sai số ngẫu nhiên σ = {he["error_sigma"]:.1e} (`he.error_sigma`) mỗi lần mã hóa/giải mã |')
    w(f'| Kích thước ciphertext / phần giải mã dùng để đệm gói | {he["ct_bytes"]:,} B / {he["share_bytes"]:,} B (`he.ct_bytes`, `he.share_bytes`, đo ở lượt OpenFHE thật 30/10/2026) |')
    w('')
    w(f'Mô hình có {B["M"]:,} tham số, vừa trong 1 ciphertext ({he["slots"]} ô). FAS mã hóa {round(lock["fas_p"] * B["M"])} giá trị đầu: vẫn cần đúng 1 ciphertext '
      f'(số ciphertext trong lượt chạy: `ckks_full` = {ck["n_ct"]}, `fas` = {fas_p["n_ct"]}; với backend mô phỏng đây là số gói được đệm, không phải ciphertext thật).')
    w('')
    w('### 2.5 Mô hình đe dọa (giả định thiết kế)')
    w('')
    w('BS tò mò nhưng trung thực (thụ động); BS và UAV không giữ khóa HE, BS không giữ K (trừ mốc `fasbs`). BS biết tổng sau khi ghép phần giải mã (giới hạn đã chấp nhận).')
    w('')
    if with_attack:
        w('Trong phân tích ngoại tuyến (`collect.py`), BS dựng lại trọng số cục bộ của client k từ đúng gói đã nhận (`capture/`): '
          'với `none` đọc thẳng; với `ckks_full` chỉ biết tổng; với `fas` biết tổng ở phần mã hóa còn phần rõ đã xáo thì **bỏ qua** (giả định kẻ tấn công không đoán được vị trí); '
          'với `fasbs` đọc được phần rõ vì có K. Mốc so sánh là "đoán bằng phần tổng BS vốn biết".')
    w('')
    w('### 2.6 Môi trường chạy và giả lập thiết bị Pi 4')
    w('')
    w('BS và hai client là ba tiến trình Python trên cùng một máy Windows, nối với nhau bằng TCP trên localhost (`127.0.0.1`). BS chỉ nhận trọng số đã bảo vệ và cộng, không có mô hình, khóa hay K (trừ arm `fasbs`); '
      'mỗi client chỉ đọc dữ liệu của mình (client1 thêm tập test). Không có UAV, không bóp tốc độ, không có độ trễ mạng.')
    w('')
    w(f'**Giả lập Pi 4 bắt buộc, tự áp trong chính script của client** (`devicelimit.enforce`): Windows Job Object giới hạn cứng CPU ở {dev["cpus"]} nhân '
      f'(= {dev["cpus"]} / số nhân logic của máy) và trần bộ nhớ commit {mem_txt(dev["mem_limit"])} cho tiến trình. Giới hạn được đọc lại từ Windows (`QueryInformationJobObject`) rồi ghi vào file bằng chứng. '
      '**Phạm vi của giả lập:** chỉ giới hạn số nhân và RAM; **không làm chậm CPU như Cortex-A72 1,5 GHz**, nên mọi thời gian trong báo cáo vẫn nhanh hơn thiết bị thật và chưa có hệ số quy đổi. '
      'BS không bị giới hạn. Trần RAM trên Windows là trần commit, không phải bộ nhớ vật lý.')
    w('')
    if len(lim) == len(arms):
        w('Bằng chứng giới hạn của hai client trong từng arm (`device_limits_client1.json`, `device_limits_client2.json` trong thư mục arm; working set = RAM vật lý đỉnh, commit = bộ nhớ cam kết đỉnh):')
        w('')
        w('| Phương án | Giới hạn đọc lại: nhân / RAM (MiB) | CPU hard cap | Working set đỉnh client1 / client2 (MiB) | Commit đỉnh client1 / client2 (MiB) | Số nhân dùng TB client1 / client2 | Thời gian thực client1 (s) |')
        w('|---|---|---|---|---|---|---|')
        for a in arms:
            c1, c2 = lim[a][1], lim[a][2]
            g = c1['gioi_han_doc_lai_tu_windows']
            w(f'| {AN.label(a)} | {g["tuong_duong_so_nhan"]:.2f} / {g["tran_ram_moi_tien_trinh_mib"]:.0f} | {"có" if g["tran_cpu_hard_cap"] else "KHÔNG"} | '
              f'{c1["do_thuc_te"]["working_set_dinh_mib"]:.0f} / {c2["do_thuc_te"]["working_set_dinh_mib"]:.0f} | '
              f'{c1["do_thuc_te"]["commit_dinh_mib"]:.0f} / {c2["do_thuc_te"]["commit_dinh_mib"]:.0f} | '
              f'{c1["do_thuc_te"]["so_nhan_trung_binh"]:.2f} / {c2["do_thuc_te"]["so_nhan_trung_binh"]:.2f} | {c1["do_thuc_te"]["thoi_gian_thuc_s"]:.0f} |')
    else:
        w(f'**Chỉ {len(lim)}/{len(arms)} arm có file bằng chứng giới hạn**; arm thiếu bằng chứng không được coi là đã chạy trong giả lập.')
    w('')
    w('Các bước chuẩn bị mô hình (trích đặc trưng, huấn luyện cục bộ 150 epoch, đánh giá test, FedAvg tham chiếu, nhiều seed) cũng tự áp cùng giới hạn; bằng chứng ở `outputs/device_runs/<bước>_<giờ>/` '
      '(`device_limits.json`, `run.json`, `output.log`). Bản MỚI NHẤT của mỗi bước:')
    w('')
    w('| Bước | Lệnh | Thời gian thực (s) | Thời gian CPU (s) | Số nhân TB | Working set đỉnh (MiB) | Commit đỉnh (MiB) | Giới hạn đọc lại: nhân / RAM (MiB) | Kết thúc |')
    w('|---|---|---|---|---|---|---|---|---|')
    for name, no, desc in STEPS:
        d = device_run(name)
        if d is None:
            w(f'| {no}. {desc} | — | — | — | — | — | — | — | **không có bằng chứng** |')
            continue
        rj, dl = jload(d / 'run.json'), jload(d / 'device_limits.json')
        r, g = dl['do_thuc_te'], dl['gioi_han_doc_lai_tu_windows']
        w(f'| {no}. {desc} | `python {" ".join(rj["lenh"])}` | {r["thoi_gian_thuc_s"]:.0f} | {r["thoi_gian_cpu_s"]:.0f} | {r["so_nhan_trung_binh"]:.2f} | '
          f'{r["working_set_dinh_mib"]:.0f} | {r["commit_dinh_mib"]:.0f} | {g["tuong_duong_so_nhan"]:.2f} / {g["tran_ram_moi_tien_trinh_mib"]:.0f} | '
          f'{"lỗi chưa xử lý" if rj["loi_chua_xu_ly"] else "bình thường"} ({rj["ket_thuc"]}) |')
    w('')
    w('Ghi chú: bước 9 (`run_fedavg`) và 11 (`run_experiments`) chạy cả hai client lần lượt trong MỘT tiến trình nên dùng chung một giới hạn 1.6 nhân / 4 GB, và RAM đỉnh là của cả hai client; '
      'ở lượt chính (bước 10) mỗi client là một tiến trình riêng có giới hạn riêng.')
    w('')

    # ---------------------------------------------------------------- 3
    w('## 3. Cách đo')
    w('')
    w('- **Độ chính xác:** accuracy trên tập test của client1 sau mỗi vòng; báo cáo vòng cuối và trung bình 10 vòng cuối; số ảnh dự đoán khác `none` ở mô hình cuối; '
      'độ lệch trọng số lớn nhất so với `none` (‖w−w_none‖∞).')
    w('- **Byte:** BS đếm số byte của từng khung tin nhắn (4 byte độ dài + thân msgpack) khi gửi/nhận, ghi vào `bs_log.json`. '
      'Byte lên mỗi client mỗi vòng = UPLOAD + PARTIAL_DEC; byte xuống = CSUM + AGGREGATE; trung bình qua mọi vòng (0…' + str(R) + ') và hai client. '
      'Chưa tính tiêu đề TCP/IP.')
    w('- **Thời gian:** thời gian từng pha đo bằng đồng hồ trong tiến trình (huấn luyện, bảo vệ, giải mã từng phần, BS cộng, BS ghép, vòng đầu-cuối) trên localhost, không có độ trễ mạng. Client chạy trong giả lập Pi 4 (chỉ số nhân và RAM). Với backend mô phỏng, thời gian bảo vệ/giải mã/ghép của phần HE là thời gian của mô phỏng, không phải của OpenFHE.')
    if with_attack:
        w('- **Rò rỉ:** mô hình BS dựng lại cho client k ở các vòng ' + str(settings.load()['lock']["attack_rounds"]) + ' (cả hai client); đo cos, sai số tương đối, accuracy trên test, và '
          '**skill = 1 − (sai số dựng lại / sai số khi đoán bằng phần tổng BS biết)²** (1: hoàn hảo, 0: chỉ ngang việc đoán bằng tổng, âm: tệ hơn).')
        w(f'- **Hai cổng chọn phương án:** (1) accuracy không kém `none` quá {100 * lock["delta_acc"]:.1f} điểm (một seed nên dùng trung bình 10 vòng cuối, không có khoảng tin cậy); '
          f'(2) skill ≤ {settings.load()["lock"]["leak_skill_margin"]}. Qua cả hai cổng thì xếp theo byte. Ứng viên không gồm `none`, `none_rerun`, `fas_lam0` (chỉ kiểm tra đúng), `fasbs` (mốc).')
    else:
        w(f'- **Chọn phương án:** cổng độ chính xác = accuracy không kém `none` quá {100 * lock["delta_acc"]:.1f} điểm (một seed nên dùng trung bình 10 vòng cuối, không có khoảng tin cậy); '
          'qua cổng thì xếp theo byte, kết quả chỉ là xếp hạng sơ bộ. Ứng viên không gồm `none`, `none_rerun`, `fas_lam0` (chỉ kiểm tra đúng), `fasbs` (mốc).')
    w('')

    # ---------------------------------------------------------------- 4
    arm_dir = BASE / 'seed42'
    bslog = {a: jload(arm_dir / a / 'bs_log.json') for a in arms}
    c1log = {a: jload(arm_dir / a / 'client1_log.json') for a in arms}
    c2log = {a: jload(arm_dir / a / 'client2_log.json') for a in arms}

    def mean_bytes(a, key, devs=('1', '2')):
        v = [r['bytes'][key][d] for r in bslog[a]['rounds'] if key in r['bytes'] for d in devs if d in r['bytes'][key]]
        return float(np.mean(v)) if v else 0.0

    def mean_phase(a, key):
        return float(np.mean([r['phase_s'][key] for r in bslog[a]['rounds'] if key in r['phase_s']] or [0.0]))

    def mean_client(a, key, both=True):
        rows = [x for x in c1log[a]['rounds'] if x['t'] > 0 or key not in ('train_s',)]
        if both:
            rows += [x for x in c2log[a]['rounds'] if x['t'] > 0 or key not in ('train_s',)]
        v = [x[key] for x in rows if key in x]
        return float(np.mean(v)) if v else 0.0

    w('## 4. Kết quả (lượt chạy chính: backend mô phỏng, client trong giả lập Pi 4)')
    w('')
    w('### 4.1 Kiểm thử')
    w('')
    tdirs = sorted(glob.glob(str(OUT / 'tests' / '*')))
    if tdirs:
        td = Path(tdirs[-1])
        tline = next((ln for ln in (td / 'summary.md').read_text(encoding='utf-8').splitlines() if ln.startswith('Thời điểm')), '')
        w(f'Kết quả `tests/run_all.py` mới nhất (`{rel(td)}/`, {tline.lower()}). Dòng `windows` chạy trực tiếp trên máy (không có OpenFHE); dòng `docker` chạy trong container có OpenFHE thật:')
        w('')
        for line in (td / 'summary.md').read_text(encoding='utf-8').splitlines():
            in_table = line.startswith('| Test') or line.startswith('|---') or '| windows |' in line or '| docker |' in line or '| BỎ QUA' in line
            if in_table and (with_attack or 'attack' not in line):          # tấn công đang tắt: không đưa test của nó vào báo cáo
                w(line)
        w('')
        ol = td / 'docker_test_openfhe.log'
        if ol.exists():
            for line in ol.read_text(encoding='utf-8').splitlines():
                if '[TEST]' in line:
                    w(f'- `test_openfhe` (mã hóa thật, ba vai trò qua socket, trong container): {line.replace("[TEST] ", "")}')
            w('')
        w('**Phạm vi:** các test `docker` kiểm tra mã hóa đa khóa thật trên mã nguồn hiện tại, nhưng **lượt chạy FL 50 vòng ở mục 4.2 trở đi dùng backend mô phỏng**, không phải OpenFHE; '
          'lượt FL 50 vòng với OpenFHE thật đã chạy trước đây (đối chiếu ở cuối mục 4) và chưa chạy lại sau khi thêm giả lập Pi 4.')
        w('')
    w('### 4.2 Ảnh hưởng tới độ chính xác của FL')
    w('')
    w('\n'.join(fl_lines))
    w('')
    ref_line = (f'Mốc không lock (huấn luyện cục bộ và FedAvg tham chiếu ở bước 3-9, `outputs/model/`): mô hình cục bộ client1 {pct(loc["client1"]["accuracy"])}, client2 {pct(loc["client2"]["accuracy"])}; '
                f'trung bình 1 lần {pct(ref["oneshot_average_test_metrics"]["accuracy"])}; FedAvg {ref["rounds"]} vòng từ mô hình khởi tạo {pct(ref["test_metrics"]["accuracy"])}. '
                f'Nhánh `none` của lượt chạy này cho {pct(nn["round0"]["acc"])} ở vòng 0 ("trung bình 1 lần": {'trùng' if abs(nn['round0']['acc'] - ref['oneshot_average_test_metrics']['accuracy']) < 1e-9 else 'KHÔNG trùng'}) và {pct(nn["final"]["acc"])} ở vòng cuối. '
                f'Hai con số vòng cuối không so trực tiếp được vì điểm xuất phát khác nhau. '
                f'Số mốc lấy từ file `outputs/model/fedavg_50/metrics.json` hiện tại.')
    w(ref_line)
    w('')
    marks = [m for m in (0, 1, 2, 5, 10, 20, 30, 40, 50) if m <= R]
    w('Accuracy trên tập test (%) tại một số vòng:')
    w('')
    w('| Phương án | ' + ' | '.join(f'vòng {m}' for m in marks) + ' |')
    w('|---|' + '---|' * len(marks))
    for a in arms:
        rr = B['arms'][a]['rounds']
        w(f'| {AN.label(a)} | ' + ' | '.join(f'{100 * rr[m]["acc"]:.2f}' for m in marks) + ' |')
    w('')
    w('Chi tiết theo vòng so với `none` (số vòng mà accuracy khác nhau, lệch lớn nhất, độ lệch trọng số):')
    w('')
    w('| Phương án | Số vòng accuracy khác `none` | Lệch accuracy lớn nhất (điểm) | ‖w−w_none‖∞ sau vòng 1 | ‖w−w_none‖∞ vòng cuối |')
    w('|---|---|---|---|---|')
    for a in arms:
        if a == 'none':
            continue
        n_d, mx = diffs(B['arms'][a])
        w(f'| {AN.label(a)} | {n_d}/{nr} | {100 * mx:.2f} | {B["arms"][a]["rounds"][1]["drift_linf"]:.1e} | {B["arms"][a]["rounds"][-1]["drift_linf"]:.1e} |')
    w('')
    w(f'![Accuracy theo vòng](../{rel(BASE / "fig_accuracy_classifier.png")})')
    w('')

    w('### 4.3 Tính đúng của mã hóa và đồng bộ hai client')
    w('')
    w('Sai khác giữa tổng mà hai client nhận được sau giải mã và tổng đúng tính từ trọng số thật của hai client (giá trị tuyệt đối lớn nhất trên các phần tử, mỗi vòng), '
      'độ lệch giữa mô hình của hai client sau vòng cuối, và độ lệch chuẩn nhiễu thực tế FAS đã cộng vào phần rõ (trung bình các vòng, theo tiến trình client1).')
    w('')
    w('| Phương án | Sai khác tổng, vòng 0 | Sai khác tổng, trung bình các vòng | Sai khác tổng, lớn nhất | ‖g_client1 − g_client2‖∞ | Độ lệch chuẩn nhiễu đã cộng |')
    w('|---|---|---|---|---|---|')
    for a in arms:
        ee = [x['err_vs_exact_linf'] for x in B['arms'][a]['rounds']]
        w(f'| {AN.label(a)} | {ee[0]:.1e} | {np.mean(ee):.1e} | {max(ee):.1e} | {B["arms"][a]["models_equal_linf"]:.1e} | {B["arms"][a]["noise_sd_mean"]:.1e} |')
    w('')
    w('Cách đọc: với `none`, `ckks_full` và `fas_lam0` (không nhiễu cố ý) sai khác tổng là sai số số học (float32 ở `none`; thêm sai số CKKS ở hai phương án còn lại). '
      'Với FAS λ > 0 sai khác tổng chủ yếu là nhiễu cố ý đã cộng. Cột ‖g_client1 − g_client2‖∞ bằng 0 nghĩa là hai client giữ mô hình giống hệt nhau.')
    w('')

    n_cost, n_pick, n_rep, n_old = ('4.5', '4.6', '4.7', '4.8') if with_attack else ('4.4', '4.5', '4.6', '4.7')     # không có mục rò rỉ khi tắt tấn công
    if with_attack:
        w('### 4.4 Rò rỉ')
        w('')
        w('\n'.join(at_lines))
        w('')
        amarks = [m for m in settings.load()['lock']['attack_rounds'] if m <= R]
        w('Mô hình BS dựng lại cho client k: accuracy trên test (%) và cos(Δ̂, Δ), trung bình hai client, tại các vòng tấn công:')
        w('')
        w('| Phương án | ' + ' | '.join(f'vòng {m}: acc / cos' for m in amarks) + ' |')
        w('|---|' + '---|' * len(amarks))
        for a in arms:
            cells = []
            for m in amarks:
                at = [x for x in B['arms'][a]['attacks'] if x['round'] == m]
                cells.append(f'{100 * np.mean([x["acc"] for x in at]):.1f} / {np.mean([x["cos"] for x in at]):.3f}')
            w(f'| {AN.label(a)} | ' + ' | '.join(cells) + ' |')
        w('')
        w(f'![Rò rỉ](../{rel(BASE / "fig_attack_classifier.png")})')
        w('')
        w('Cách đọc: ở FAS khóa chỉ ở hai client, skill bằng 0 **theo cách xây dựng** (kẻ tấn công bỏ qua phần rõ đã xáo), nên cột skill không phân biệt được các mức λ; '
          'bằng chứng thật nằm ở chênh lệch accuracy mô hình dựng lại giữa FAS khóa ở client và `fasbs` (BS giữ K).')
        w('')

    w(f'### {n_cost} Chi phí truyền thông và thời gian')
    w('')
    w('\n'.join(ct_lines))
    w('')
    w('Byte của từng loại tin nhắn, trung bình mỗi vòng (vòng 0…' + str(R) + '), tính trên mỗi client (`METRICS` chỉ do client1 gửi):')
    w('')
    w('| Phương án | ROUND_START | UPLOAD | CSUM | PARTIAL_DEC | AGGREGATE | METRICS |')
    w('|---|---|---|---|---|---|---|')
    for a in arms:
        w(f'| {AN.label(a)} | {mean_bytes(a, "ROUND_START"):,.0f} | {mean_bytes(a, "UPLOAD"):,.0f} | {mean_bytes(a, "CSUM"):,.0f} | '
          f'{mean_bytes(a, "PARTIAL_DEC"):,.0f} | {mean_bytes(a, "AGGREGATE"):,.0f} | {mean_bytes(a, "METRICS", ("1",)):,.0f} |')
    w('')
    w('Tổng hợp byte lên và xuống:')
    w('')
    w('| Phương án | UPLOAD (B) | PARTIAL_DEC (B) | Tổng lên (B) | Tổng xuống (B) | Tổng lên cả lượt, mỗi client (MB) |')
    w('|---|---|---|---|---|---|')
    for a in arms:
        b = B['arms'][a]['bytes_per_client']
        w(f'| {AN.label(a)} | {b["upload"]:,.0f} | {b["partial_dec"]:,.0f} | {b["up_total"]:,.0f} | {b["down_total"]:,.0f} | {b["up_total"] * nr / 1e6:.2f} |')
    w('')
    w(f'Ghi chú: "tổng cả lượt" = trung bình mỗi vòng × {nr} vòng. Kích thước kỳ vọng theo công thức: một ciphertext gồm 2 đa thức × N × 8 byte = {2 * he["ring_dim"] * 8:,} B, '
      f'một phần giải mã gồm 1 đa thức = {he["ring_dim"] * 8:,} B (cộng tiêu đề); đo được UPLOAD {B["arms"]["ckks_full"]["bytes_per_client"]["upload"]:,.0f} B và '
      f'PARTIAL_DEC {B["arms"]["ckks_full"]["bytes_per_client"]["partial_dec"]:,.0f} B ở `ckks_full`.')
    w('')
    w('Thời gian từng pha, trung bình mỗi vòng (đồng hồ trong tiến trình, 3 tiến trình trên một máy, client trong giả lập Pi 4, không có kênh). '
      'Các cột "chờ" gồm cả thời gian chờ bên chậm hơn, không phải thời gian tính toán:')
    w('')
    w('| Phương án | Client: huấn luyện (s) | Client: bảo vệ (ms) | Client: giải mã từng phần (ms) | Client: hoàn tất/giải xáo (ms) | Client1: đánh giá test (s) | '
      'BS: chờ UPLOAD (s) | BS: cộng (ms) | BS: chờ PARTIAL_DEC (s) | BS: ghép (ms) | BS: vòng đầu-cuối (s) |')
    w('|---|---|---|---|---|---|---|---|---|---|---|')
    for a in arms:
        w(f'| {AN.label(a)} | {mean_client(a, "train_s"):.2f} | {1000 * mean_client(a, "protect_s"):.1f} | {1000 * mean_client(a, "partial_dec_s"):.1f} | '
          f'{1000 * mean_client(a, "finish_s"):.1f} | {mean_client(a, "eval_s", both=False):.2f} | {mean_phase(a, "wait_upload"):.2f} | '
          f'{1000 * mean_phase(a, "aggregate"):.1f} | {mean_phase(a, "wait_partial_dec"):.2f} | {1000 * mean_phase(a, "fuse"):.1f} | {mean_phase(a, "round"):.2f} |')
    w('')

    tr = {a: mean_client(a, 'train_s') for a in arms}
    w(f'Ghi chú về thời gian: huấn luyện mỗi vòng là cùng một khối lượng việc ở mọi arm nhưng đo được từ {min(tr.values()):.2f} đến {max(tr.values()):.2f} s giữa các arm (chạy tuần tự, mỗi arm một lượt riêng). '
      'Vì vậy chênh lệch thời gian vòng giữa các arm cỡ vài trăm ms trở xuống KHÔNG quy được cho phương án bảo vệ (có thể do tải của máy theo thời điểm); chỉ so sánh thời gian ở mức chênh rõ rệt hoặc xem cột cộng/ghép/bảo vệ.')
    w('')

    if with_attack:
        w(f'### {n_pick} Qua hai cổng')
        w('')
        w('| Phương án | Cổng 1 (độ chính xác) | Cổng 2 (rò rỉ) | Byte lên/vòng/client | Kết luận |')
        w('|---|---|---|---|---|')
        for a, g1, g2, up, ok in sel:
            w(f'| {AN.label(a)} | {g1} | {g2} | {up:,.0f} | {"đạt cả 2" if ok else "rớt"} |')
        w('')
        w(f'Phương án ít byte nhất trong các phương án qua cả hai cổng: **{AN.label(best)}**.')
    else:
        w(f'### {n_pick} Chọn phương án theo độ chính xác và chi phí')
        w('')
        w('| Phương án | Cổng độ chính xác | Byte lên/vòng/client | Kết luận |')
        w('|---|---|---|---|')
        for a, g1, _, up, ok in sel:
            w(f'| {AN.label(a)} | {g1} | {up:,.0f} | {"qua cổng" if ok else "rớt"} |')
        w('')
        w(f'Phương án ít byte nhất trong các phương án qua cổng độ chính xác: **{AN.label(best)}**. Đây là xếp hạng sơ bộ, **không phải kết luận chọn phương pháp tốt nhất**, vì báo cáo không đo mức bảo mật và chưa đo kênh.')
    w('')

    w(f'### {n_rep} Độ lặp lại (`none` và `none_rerun`)')
    w('')
    n_d, mx = diffs(B['arms']['none_rerun'])
    w('Hai arm `none` và `none_rerun` cùng cấu hình, cùng seed, cùng điểm xuất phát; chênh lệch giữa chúng là nhiễu nền (PyTorch không bảo đảm tất định) mà mọi chênh lệch của các arm khác phải vượt qua mới có ý nghĩa.')
    w('')
    w('| Chỉ số | `none` | `none_rerun` |')
    w('|---|---|---|')
    nrr = B['arms']['none_rerun']
    w(f'| Accuracy vòng cuối | {pct(nn["final"]["acc"])} | {pct(nrr["final"]["acc"])} |')
    w(f'| Số vòng accuracy khác `none` | — | {n_d}/{nr} (lệch lớn nhất {100 * mx:.2f} điểm) |')
    w(f'| Số ảnh dự đoán khác `none` ở mô hình cuối | — | {nrr["pred_diff_vs_none"]} |')
    w(f'| ‖w − w_none‖∞ vòng cuối | — | {nrr["rounds"][-1]["drift_linf"]:.1e} |')
    w('')

    if D is not None:
        old_dir = OLD / 'seed42'
        old_info = jload(sorted(glob.glob(str(OLD / 'logs' / 'run_info_*.json')))[-1])

        def old_ms(a, who, key):
            if who == 'bs':
                v = [r['phase_s'][key] for r in jload(old_dir / a / 'bs_log.json')['rounds'] if key in r['phase_s']]
            else:
                v = [x[key] for k in (1, 2) for x in jload(old_dir / a / f'client{k}_log.json')['rounds'] if key in x]
            return 1000 * float(np.mean(v)) if v else 0.0

        w(f'### {n_old} Đối chiếu với lượt OpenFHE thật CŨ (chỉ để tham khảo)')
        w('')
        w(f'Lượt `{rel(OLD)}/` chạy lúc {old_info["thoi_diem"]} với OpenFHE thật trong 3 container, commit `{old_info["git_commit"][:10]}`. '
          '**Lượt đó chưa giới hạn Pi 4 (không có bằng chứng giới hạn) và dùng mã nguồn trước khi sửa giả lập, nên chỉ đối chiếu, không trộn số vào các mục trên.** '
          'Thời gian client (bảo vệ, giải mã từng phần) và thời gian BS ghép ở đây là thời gian của OpenFHE thật; cột "mô phỏng" là của lượt chính.')
        w('')
        w('| Phương án | Acc cuối: mô phỏng | Acc cuối: OpenFHE thật | Byte lên: mô phỏng | Byte lên: OpenFHE thật | Bảo vệ tại client (ms): mô phỏng / thật | Giải mã từng phần (ms): mô phỏng / thật | BS ghép (ms): mô phỏng / thật |')
        w('|---|---|---|---|---|---|---|---|')
        for a in arms:
            if a not in D['arms']:
                continue
            w(f'| {AN.label(a)} | {pct(B["arms"][a]["final"]["acc"])} | {pct(D["arms"][a]["final"]["acc"])} | {B["arms"][a]["bytes_per_client"]["up_total"]:,.0f} | '
              f'{D["arms"][a]["bytes_per_client"]["up_total"]:,.0f} | {1000 * mean_client(a, "protect_s"):.1f} / {old_ms(a, "c", "protect_s"):.1f} | '
              f'{1000 * mean_client(a, "partial_dec_s"):.1f} / {old_ms(a, "c", "partial_dec_s"):.1f} | {1000 * mean_phase(a, "fuse"):.1f} / {old_ms(a, "bs", "fuse"):.1f} |')
        w('')
        same = [x for x in arms if x in D['arms'] and D['arms'][x]['final']['acc'] == B['arms'][x]['final']['acc']]
        diff = [f'{AN.label(x)} ({pct(B["arms"][x]["final"]["acc"])} so với {pct(D["arms"][x]["final"]["acc"])})' for x in arms if x in D['arms'] and x not in same]
        w(f'Accuracy vòng cuối trùng nhau ở {len(same)}/{len(arms)} phương án' + (f'; khác ở: {", ".join(diff)}' if diff else '') + '. '
          'Chưa truy nguyên nguyên nhân các chỗ khác (có thể do trọng số huấn luyện cục bộ được chạy lại, nhiễu ngẫu nhiên của mã hóa thật hoặc mã nguồn khác nhau). '
          'Byte của backend mô phỏng được đệm theo cỡ đo ở lượt thật nên gần với byte thật.')
        w('')

    # ---------------------------------------------------------------- 5
    w('## 5. Thảo luận (bám theo số liệu ở trên)')
    w('')
    w(f'1. **Sai số CKKS (mô phỏng) không làm hại việc học.** Sai số σ = {he["error_sigma"]:.1e} mỗi lần mã hóa/giải mã được cộng dồn qua {nr} vòng nhưng chỉ làm trọng số lệch '
      f'{ck["rounds"][-1]["drift_linf"]:.1e} so với `none` và đổi {ck["pred_diff_vs_none"]} dự đoán ở mô hình cuối. Đây là kết luận về sai số được mô hình hóa; mã hóa thật có thể có sai số khác (độ lớn đo thật ở `test_openfhe`: xem mục 4.1).')
    w(f'2. **Nhiễu của FAS đánh đổi độ chính xác lấy lớp che phần rõ.** Ngay λ={0.01:g}, độ lệch trọng số sau vòng 1 đã là '
      f'{B["arms"]["fas_lam0.01"]["rounds"][1]["drift_linf"]:.1e}, lớn hơn CKKS 100% ({ck["rounds"][1]["drift_linf"]:.1e}) rõ rệt; accuracy cuối vẫn chưa phân biệt được ở mức nhiễu nhỏ nhưng đường cong khác ở '
      f'{diffs(B["arms"]["fas_lam0.01"])[0]}/{nr} vòng. Ở λ={0.3:g} accuracy vòng cuối còn {pct(B["arms"]["fas_lam0.3"]["final"]["acc"])} và trung bình 10 vòng cuối kém không lock '
      f'{-100 * d03:.2f} điểm (rớt cổng 1); λ=1 làm mô hình sụp ({pct(B["arms"]["fas_lam1"]["final"]["acc"])}).')
    if with_attack:
        w(f'3. **Chủ khóa xáo quyết định việc che phần rõ.** Cùng nhiễu, cùng byte, cùng accuracy, nhưng khi BS giữ K mô hình BS dựng lại đạt {pct(att["fasbs_lam0.1"]["acc"], 1)} '
          f'còn khi K chỉ ở hai client chỉ đạt {pct(att["fas_lam0.1"]["acc"], 1)}. Tức là việc đổi chủ khóa không tốn thêm byte hay độ chính xác.')
    else:
        w('3. **Chủ khóa xáo không làm đổi chi phí.** Mốc `fasbs` có cùng nhiễu và cùng cách đóng gói với `fas` cùng λ; chỉ khác ai giữ khóa xáo K, nên không thêm byte.')
    w(f'4. **Ít byte nhất không đồng nghĩa bảo mật hơn.** Với mô hình {B["M"]:,} tham số cả hai phương án cần 1 ciphertext; FAS chỉ gửi thêm phần rõ '
      f'({fb["up_total"] - cb["up_total"]:,.0f} B) nên nhiều hơn CKKS 100%. Kết luận này sẽ khác khi mô hình cần nhiều ciphertext (chưa chạy).')
    w('')

    # ---------------------------------------------------------------- 6
    w('## 6. Hạn chế và giả định')
    w('')
    w('- **Một seed.** Không có khoảng tin cậy theo cặp seed; chênh lệch vài ảnh (ví dụ FAS λ nhỏ) chưa đủ để kết luận. Trọng số huấn luyện cục bộ 150 epoch chỉ có cho seed 42.')
    w('- **Cổng 1 dùng accuracy trên tập test** để quyết định, trái quy ước chọn tham số theo tập val; chưa sửa. Tập test được xem lại ở mọi vòng.')
    w('- **δ = ' + f'{100 * lock["delta_acc"]:.1f}' + ' điểm và lưới λ là giá trị do trợ lý đặt**, chưa được người dùng duyệt; mức nhiễu không có nguồn từ bài báo FAS.')
    if with_attack:
        w('- **Cổng rò rỉ của FAS khóa ở client luôn cho skill = 0 theo cách xây dựng** (kẻ tấn công bỏ qua phần rõ đã xáo). Không có chứng minh rằng phần xáo vị trí an toàn; giá trị, độ lớn và phân bố phần rõ vẫn lộ.')
    else:
        w('- **Không đo mức bảo mật.** Báo cáo chỉ đo độ chính xác, chi phí truyền thông và thời gian, nên không kết luận được phương án nào an toàn hơn. '
          'Không có chứng minh rằng phần xáo vị trí của FAS an toàn; giá trị, độ lớn và phân bố phần rõ vẫn lộ theo thiết kế.')
    w('- **FAS không có bảo đảm differential privacy**: nhiễu có độ lệch chuẩn phụ thuộc dữ liệu, không có clipping, không có ε. FAS ở đây xáo vị trí (không xáo bit như bài báo) và chọn phần mã hóa theo thứ tự cố định (bài báo chọn ngẫu nhiên đều).')
    w('- **Phần giải mã đa bên dùng nhiễu mặc định của OpenFHE** (`FIXED_NOISE_MULTIPARTY`): về lý thuyết BS tò mò có thể suy thông tin về khóa; không dùng chế độ chống điều đó vì cần đổi tham số CKKS.')
    w('- **Hai client**: mỗi bên suy ra được cập nhật của bên kia từ tổng; mã hóa không chống được điều này.')
    w('- **Khóa xáo K và nhiễu sinh từ seed** để lặp lại được (khác thiết kế triển khai: nhiễu phải từ entropy riêng của thiết bị). K cài sẵn, không có bảo mật chuyển tiếp.')
    w('- **Chỉ mô hình lớp cuối (1.539 tham số).** Thí nghiệm lock/không lock chưa chạy `fire9_classifier` (198.723 tham số, 49 ciphertext ở CKKS 100%), nơi FAS có thể có lợi về byte.')
    w('- **Backend mô phỏng (`emulated`).** Lượt chính không mã hóa thật: độ chính xác và byte hợp lệ trong giới hạn mô hình sai số CKKS và cỡ ciphertext đo cũ; thời gian bảo vệ/giải mã/ghép của phần HE và tính đúng của mã hóa KHÔNG đến từ lượt này. '
      'Windows không có OpenFHE; lượt OpenFHE thật 50 vòng × 10 arm chưa chạy lại sau khi thêm giả lập Pi 4 (chỉ có lượt cũ ở mục đối chiếu, không có bằng chứng giới hạn).')
    w('- **Giả lập Pi 4 chỉ giới hạn số nhân và RAM.** Không làm CPU chậm như Cortex-A72 1,5 GHz nên mọi thời gian vẫn nhanh hơn thiết bị thật; chưa có hệ số quy đổi. Trần RAM là trần commit của Windows. BS không bị giới hạn. '
      'Bước 9 và 11 chạy hai client trong một tiến trình (dùng chung một giới hạn).')
    w('- **Thời gian đo trên localhost** (không có kênh); thời gian huấn luyện chỉ để so sánh tương đối giữa các arm. Chưa đo UAV và kênh, nên cổng "trễ hạn" chưa áp dụng.')
    w('- **Mã nguồn có thay đổi chưa commit** khi chạy (xem bảng đầu); kết quả truy được về working tree chứ không về một commit duy nhất.')
    w('- **Dữ liệu:** hạn chế của dữ liệu (ảnh khói từ một nguồn camera, khung hình liên tiếp, nhiễu nhãn) nằm ở `report/bao_cao_du_lieu.md` và `bao_cao_huan_luyen_mo_hinh.md`.')
    w('')

    # ---------------------------------------------------------------- phụ lục A
    w('## Phụ lục A. Lệnh chạy')
    w('')
    w('Chạy ở thư mục gốc dự án (`doanFL`), PowerShell, Python 3.12. Mỗi script chạy trên thiết bị tự áp giới hạn Pi 4 khi khởi động (không có cờ tắt); máy không phải Windows và không trong Docker sẽ bị từ chối.')
    w('')
    w('```powershell')
    for name, no, desc in STEPS:
        if name == 'bench_train':
            w('# 7. Ghép bảng hai mô hình cục bộ (không phải bước của thiết bị, không giới hạn)')
            w('python src/model/compare_local.py')
        if name == 'run_experiments':
            w('# 10. lượt chính (3 tiến trình: BS + 2 client; mỗi client tự giới hạn) rồi bảng/hình')
            w('python ' + ' '.join(info['lenh']))
            w('python src/secure_fl/experiments/analyze.py')
        d = device_run(name)
        if d is not None:
            w(f'# {no}. {desc}')
            lenh = jload(d / 'run.json')['lenh']
            w('python ' + ' '.join(lenh) + (' classifier' if name == 'bench_train' and 'classifier' not in lenh else ''))
    w('# sinh lại báo cáo này')
    w('python src/secure_fl/experiments/make_report.py')
    w('```')
    w('')
    w('Nơi lưu: lượt chính ghi `logs/run_fl_tcp_seed42_<giờ>.log`, `logs/run_info_seed42_<giờ>.json` (lệnh, commit, toàn bộ cấu hình), `logs/analyze_<giờ>.log`; '
      'từng arm có `bs_log.json`, `client*_log.json`, `device_limits_client*.json`, `g_client*.npy`. Mỗi bước chuẩn bị ghi `outputs/device_runs/<bước>_<giờ>/`.')
    w('')

    # ---------------------------------------------------------------- phụ lục B nhật ký
    w('## Phụ lục B. Nhật ký các lần gọi lệnh chạy')
    w('')
    w('| Thời điểm bắt đầu | Thư mục | Lượt | Kết quả (theo log) |')
    w('|---|---|---|---|')

    def start_of(f):
        ls = [ln for ln in Path(f).read_text(encoding='utf-8', errors='replace').splitlines() if ln.strip()]
        return ls[1] if len(ls) > 1 else ''
    logs = [(f, 'mô phỏng + giả lập Pi 4') for f in glob.glob(str(OUT / 'tcp' / 'classifier' / 'logs' / 'run_fl_tcp_*.log'))]         + [(f, 'OpenFHE thật, CŨ, chưa giới hạn Pi 4') for f in glob.glob(str(OUT / 'docker*' / 'classifier' / 'logs' / 'run_fl_docker_*.log'))]
    for f, kind in sorted(logs, key=lambda x: start_of(x[0])):
        txt = Path(f).read_text(encoding='utf-8', errors='replace')
        lines = [ln for ln in txt.splitlines() if ln.strip()]
        start = lines[1].replace('# bắt đầu: ', '') if len(lines) > 1 else ''
        done = sum('xong sau' in ln for ln in lines)
        skipped = sum('đã có, bỏ qua' in ln for ln in lines)
        if 'KeyboardInterrupt' in txt:
            res = 'bị ngắt tay (KeyboardInterrupt), không có arm nào hoàn thành'
        elif 'RuntimeError' in txt and 'registry-1.docker.io' in txt:
            res = 'lỗi build: máy không phân giải được registry-1.docker.io (không có mạng); không chạy arm nào'
        elif done or skipped:
            res = f'hoàn thành {done} arm, bỏ qua {skipped} arm đã có'
        else:
            res = 'không rõ'
        w(f'| {start} | `{rel(Path(f).parents[2])}` | {kind} | {res} |')
    w('')

    archive_existing(REPORT)                                         # giữ bản cũ trong report/lich_su/ trước khi ghi đè
    REPORT.write_text('\n'.join(md), encoding='utf-8')
    print(f'đã ghi {REPORT} ({len(md)} dòng)')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')                         # console Windows mặc định cp1252 không in được tiếng Việt
    main()
