# HANDOFF — Vietsub-video-Trung & Dự Án Kênh `汪汪喵爸` (`wangwang-miaoba`)

> **Tài liệu bàn giao phiên làm việc (2026-11-15):** Dùng để tiếp nối ngay quá trình render còn dang dở của kênh `wangwang-miaoba` hoặc triển khai bộ skill/pipeline **Vietsub Karaoke `\kf` + Lồng Tiếng Smart Ducking** sang máy tính mới.

---

## 1. Tổng Quan Bàn Giao

### 1.1. Repository & Bộ Skill / Template (`Vietsub-video-Trung`)
- **GitHub Repository:** `https://github.com/trungcaha/Vietsub-video-Trung` (`PRIVATE`, nhánh `main`)
- **Thành phần đóng gói hoàn chỉnh:**
  - Skill Antigravity: `skills/vietsub-video-trung/` (`SKILL.md`, `scripts/init_project.py`, `references/technical-pitfalls.md`)
  - Workflow & QA Gate: `workflows/workflow_translate_qa.py`, `workflows/vietsub-karaoke-pipeline.md`
  - Rule bắt buộc: `rules/vietsub-video-trung.md` & `AGENTS.md`
  - Template 5 bước chuẩn: `template/` (`project.example.json`, `glossary.example.md`, `scripts/config_loader.py`, `step1_download_channel.py` → `step5_audit_report.py`)
  - Trình tải kênh nhúng sẵn: `vendor/MediaCrawler/` (mã nguồn sạch, không kèm `browser_data/`, `.venv/`, `logs/`, `*.db`)
  - Bộ cài đặt 1 lệnh đa nền tảng (Windows / macOS / Linux): `setup_machine.py`, `install.ps1`, `install.sh`
- **Vị trí cài skill cục bộ (Antigravity):** `~/.gemini/config/skills/vietsub-video-trung/` (đồng bộ 1:1 qua `setup_machine.py --skill-only`)

### 1.2. Dự Án Sản Xuất Thực Tế (`Du_an/wangwang-miaoba/`)
- **Kênh nguồn:** Douyin `汪汪喵爸` (`sec_uid`: `MS4wLjABAAAAGuavi8wyW962QXOA9yKQyGxPuoa_jhQSplhf6KA3Yos`)
- **Thông số gốc:** `2560x1440` (16:9), `46` video trong `raw/posts_manifest.json` (`42` tập lẻ + `4` hợp tập tổng hợp `39`–`42`).
- **Phân vai giọng đọc (`edge-tts` PC voices) & màu Karaoke `\kf`:**
  - `bo_cho` (Bố Chó): `vi-VN-NamMinhNeural`, `rate=+0%`, `pitch=-10Hz` — Vàng Hoàng Kim (`&H0000E5FF`)
  - `meo_con` (Mèo Con): `vi-VN-HoaiMyNeural`, `rate=+6%`, `pitch=+18Hz` — Cam Vàng Tươi (`&H0028AEFF`)
  - `bien_muc` (Anh Biên): `vi-VN-NamMinhNeural`, `rate=+4%`, `pitch=+2Hz` — Xanh Ngọc Sáng (`&H00FFFF2E`)
  - `ke_xau` (Kẻ Xấu): `vi-VN-NamMinhNeural`, `rate=-2%`, `pitch=-18Hz` — Đỏ Cam Nổi (`&H005555FF`)
  - `dan_chuyen` (Dẫn Chuyện): `vi-VN-HoaiMyNeural`, `rate=+2%`, `pitch=+0Hz` — Vàng Kem Sáng (`&H0078F0FF`)

---

## 2. Trạng Thái Hiện Tại Của Dự Án `wangwang-miaoba`

| Bước | Trạng thái | Kết quả đã xác minh | Ghi chú |
|---|---|---|---|
| **Bước 1** — Tải kênh (`step1_download_all.py`) | **Hoàn tất 100%** | **46 / 46** MP4 gốc trong `raw/` | `42` tập lẻ (`01..38`, `43..46`) + `4` hợp tập (`39..42`) tự động loại khỏi khâu lồng tiếng |
| **Bước 2** — Whisper GPU + F0 + RapidOCR (`step2_transcribe_all.py`) | **Hoàn tất 100%** | **42 / 42** file `transcripts/*_zh.json` | Đạt **42 / 42** `ocr_detected` (tọa độ chính xác `hardsub_band` & `hardsub_x_band`) |
| **Bước 3** — Dịch phân vai + QA Gate (`/run-workflow`) | **Hoàn tất 100%** | **42 / 42** file `translations/*_vi.json` | QA Gate 0 lỗi (khớp đủ câu, không sót chữ Hán, `vi_file_stem` không trùng lặp) |
| **Bước 4** — TTS + Karaoke `\kf` + Smart Ducking + NVENC (`step4_dub_and_render.py`) | **Đã xong 25 / 42** | **25** bộ `.mp4` + `.vi.srt` + `.vi.ass` trong `output/` (`6.51 GiB`) | Kiểm định `ffprobe` **25 / 25** đạt `h264 + aac`, lệch thời lượng `< 0.1s`, **0** file hỏng; ổ `C:` còn `23.64 GiB` trống |
| **Tập đang xử lý dở (giữ cache)** | **Đã lưu cache an toàn** | `26_7696491722666200354` (`26_Tap_26_Ngay_Sau`) | Đã cache **`27 / 100`** cặp `.mp3` + `.words.json` trong `_tmp/26_7696491722666200354/` |
| **Bước 5** — Kiểm toán cuối & xuất `BAO_CAO_SAN_XUAT.md` | **Chờ hoàn tất 17 tập còn lại** | — | Chạy kiểm định `ffprobe` toàn bộ `42/42` tập sau khi Bước 4 chạy xong |

### Danh sách chi tiết 25 tập đã hoàn tất (đã qua kiểm định `ffprobe`)

| STT | File thành phẩm (`output/*.mp4`) | Thời lượng ra / gốc (s) | Dung lượng (MB) | Phụ đề `.vi.srt` / `.vi.ass` |
|---:|---|---:|---:|:---:|
| 1 | `01_Hanh_Trinh_Tim_Sua.mp4` | 110.07 / 110.09 | 174.5 | Có đủ |
| 2 | `02_Dong_Sua_Bac_De.mp4` | 122.37 / 122.37 | 138.4 | Có đủ |
| 3 | `03_Mua_Lanh_Va_Man_Thau.mp4` | 133.93 / 133.96 | 153.5 | Có đủ |
| 4 | `04_Bai_Hoc_Dau_Tien.mp4` | 120.70 / 120.70 | 85.8 | Có đủ |
| 5 | `05_Chu_Meo_Cam_Ben_Thung_Rac.mp4` | 114.53 / 114.54 | 136.6 | Có đủ |
| 6 | `06_Soi_Den_Roi.mp4` | 130.93 / 130.94 | 161.3 | Có đủ |
| 7 | `07_Mot_Ngay_Dai.mp4` | 146.43 / 146.45 | 197.6 | Có đủ |
| 8 | `08_Bi_Quyet_Chan_Cuu.mp4` | 157.73 / 157.73 | 314.2 | Có đủ |
| 9 | `09_Dau_Moi_La_Nha.mp4` | 151.40 / 151.42 | 256.0 | Có đủ |
| 10 | `10_Cuoc_Vay_San.mp4` | 181.40 / 181.42 | 303.4 | Có đủ |
| 11 | `11_Da_Thu_Mac_Ket.mp4` | 157.77 / 157.78 | 223.9 | Có đủ |
| 12 | `12_Cai_Gia_Truong_Thanh.mp4` | 180.10 / 180.12 | 229.3 | Có đủ |
| 13 | `13_Dua_Con_Ngo_Nghich.mp4` | 140.67 / 140.67 | 199.6 | Có đủ |
| 14 | `14_Suc_Manh_Diu_Dang.mp4` | 233.87 / 233.87 | 324.5 | Có đủ |
| 15 | `15_Cung_Ngam_Trang_Tron.mp4` | 252.80 / 252.82 | 346.2 | Có đủ |
| 16 | `16_Cu_Khoai_Nuong.mp4` | 204.23 / 204.24 | 273.3 | Có đủ |
| 17 | `17_Khong_Chut_Phong_Bi.mp4` | 226.63 / 226.65 | 299.6 | Có đủ |
| 18 | `18_Chuyen_Cai_Sua.mp4` | 210.13 / 210.14 | 296.7 | Có đủ |
| 19 | `19_Ban_Dong_Hanh.mp4` | 228.07 / 228.07 | 360.0 | Có đủ |
| 20 | `20_Hiem_Hoa_Dai_Bang_Vang.mp4` | 221.80 / 221.82 | 344.2 | Có đủ |
| 21 | `21_Tap_21_O_Am_Hay_Dong_Hoang.mp4` | 216.57 / 216.57 | 365.1 | Có đủ |
| 22 | `22_Tap_22_Gio_Va_Lua.mp4` | 211.97 / 211.98 | 329.5 | Có đủ |
| 23 | `23_Tap_23_Don_Doc_Vo_Vong.mp4` | 216.60 / 216.62 | 363.9 | Có đủ |
| 24 | `24_Tap_24_Trai_Tim_Lua_Do.mp4` | 221.20 / 221.22 | 364.7 | Có đủ |
| 25 | `25_Tap_25_Goi_Gio.mp4` | 235.77 / 235.78 | 419.4 | Có đủ |

### Danh sách 17 tập lẻ còn lại (`26`–`38` và `43`–`46`)

| STT | `ep_key` | Tên file đầu ra dự kiến | Tiêu đề tiếng Việt | Thời lượng (s) | Số câu thoại |
|---:|---|---|---|---:|---:|
| 26 | `26_7696491722666200354` | `26_Tap_26_Ngay_Sau` | Tập 26: Ngày Sau | 203.9 | 100 *(đã cache 27)* |
| 27 | `27_7697228387785444671` | `27_Tap_27_Khoi_Thieng_Cau_An` | Tập 27: Khói Thiêng Cầu An | 213.0 | 70 |
| 28 | `28_7697608155810925874` | `28_Tap_28_Ke_Trom_Dem` | Tập 28: Kẻ Trộm Đêm | 189.3 | 81 |
| 29 | `29_7698338855618940202` | `29_Bao_An` | Tập 29: Báo Ân | 156.9 | 28 |
| 30 | `30_7699081282545913122` | `30_Cao_Biet` | Tập 30: Cáo Biệt | 221.2 | 30 |
| 31 | `31_7699825579905781011` | `31_Hop_Tan` | Tập 31: Hợp Tan | 208.9 | 68 |
| 32 | `32_7700207343522286886` | `32_Ban_Be` | Tập 32: Bạn Bè | 186.8 | 77 |
| 33 | `33_7700545563514785058` | `33_Meo_Con_Va_Soi_Xam` | Tập 33: Mèo Con Và Sói Xám | 218.4 | 22 |
| 34 | `34_7700941733684595987` | `34_Bat_Dong_Quan_Diem` | Tập 34: Bất Đồng Quan Điểm | 203.6 | 90 |
| 35 | `35_7701686392128032009` | `35_Dem_Mua_Than_The_Anh_Bien` | Tập 35: Đêm Mưa Thân Thế Anh Biên | 207.6 | 132 |
| 36 | `36_7702426082468711706` | `36_Nguoi_Chu_Nhan_Tam` | Tập 36: Người Chủ Nhẫn Tâm | 219.1 | 121 |
| 37 | `37_7702786444577836351` | `37_Lua_Chon_So_Phan` | Tập 37: Lựa Chọn Của Số Phận | 203.8 | 80 |
| 38 | `38_7703550541770607913` | `38_Gia_Dinh_Tron_Ven` | Tập 38: Gia Đình Trọn Vẹn | 236.9 | 32 |
| 43 | `43_7706136540044463414` | `43_Con_Duong_Tro_Ve` | Tập 43: Con Đường Trở Về | 210.0 | 73 |
| 44 | `44_7706876919630908672` | `44_Noi_Giac_Mo_Bat_Dau` | Tập 44: Nơi Giấc Mơ Bắt Đầu | 181.3 | 92 |
| 45 | `45_7707616460473994505` | `45_Tap_45_Can_Nha_Mo_Uoc` | Tập 45: Căn Nhà Mơ Ước | 162.5 | 66 |
| 46 | `46_7707913138116578587` | `46_Tap_46_Dua_Nho_Ky_La` | Tập 46: Đứa Nhỏ Kỳ Lạ | 195.5 | 56 |

*(Lưu ý: 4 video index `39`–`42` trong `raw/` là các bản gộp `汪汪喵爸（1-13/14-21/22-29/30-37合集）` thời lượng `1629s`–`1819s`, đã gắn cờ `is_compilation: true` nên không lồng tiếng lại.)*

---

## 3. Lệnh Chạy Nối Tiếp (Resume Trong 1 Lệnh)

Đứng tại thư mục gốc workspace `<WORKSPACE>` (ví dụ `c:\Users\PC\Downloads\MUSE`):

```bash
# 1. Chạy tiếp toàn bộ 17 tập còn lại (tự động [SKIP] 25 tập đã xong & tái sử dụng 27 câu đã cache ở Tập 26)
python -u Du_an/wangwang-miaoba/scripts/step4_dub_and_render.py --all

# Hoặc chạy riêng lẻ 1 tập bất kỳ (thêm --force nếu muốn render đè lại):
python -u Du_an/wangwang-miaoba/scripts/step4_dub_and_render.py --ep 26_7696491722666200354
```

Sau khi `step4_dub_and_render.py --all` chạy xong **42 / 42** tập:

```bash
# 2. Kiểm toán ffprobe toàn bộ 42 tập & xuất báo cáo tổng hợp BAO_CAO_SAN_XUAT.md (dùng script Bước 5 từ template)
python vietsub-video-trung/template/scripts/step5_audit_report.py --project-dir Du_an/wangwang-miaoba
```

*(Lưu ý: Nếu chạy `step5_audit_report.py` của template cho thư mục `Du_an/wangwang-miaoba`, cần có file `project.json` tối thiểu hoặc kiểm tra `output/*.mp4` bằng `ffprobe` đối chiếu `raw/posts_manifest.json` để xác nhận đủ 42 `.mp4` + `.vi.srt` + `.vi.ass` và `abs(out_dur - raw_dur) < 0.6s`.)*

---

## 4. Hướng Dẫn Triển Khai Sang Máy Mới (Cross-Machine Onboarding)

### 4.1. Cài bộ Skill + Workflow + Rule + Template + MediaCrawler cho kênh mới

```bash
# 1. Clone repo (yêu cầu đã đăng nhập GitHub có quyền truy cập repo private)
git clone https://github.com/trungcaha/Vietsub-video-Trung.git
cd Vietsub-video-Trung

# 2. Cài toàn bộ skill vào ~/.gemini/config/, cài .venv cho vendor/MediaCrawler & thư viện pipeline, rồi chạy --doctor
python setup_machine.py
# Windows PowerShell: .\install.ps1
# macOS / Linux:      ./install.sh

# 3. Đăng nhập QR Douyin một lần (lưu session vào browser_data/)
python setup_machine.py --login dy

# 4. Kiểm tra lại trạng thái hệ thống (phải báo 0 lỗi nghiêm trọng)
python setup_machine.py --doctor
```

### 4.2. Khởi tạo nhanh một kênh Douyin mới

```bash
python skills/vietsub-video-trung/scripts/init_project.py \
  --slug ten-kenh-moi \
  --dest ./Du_an \
  --channel-url "https://www.douyin.com/user/<sec_uid>"
```

Sau đó mở `<dest>/ten-kenh-moi/project.json` (chỉnh `roles` với `voice`/`rate`/`pitch` Hz/`color_bgr`) và `glossary.md`, rồi chạy tuần tự Bước 1 → Bước 5 (bắt buộc qua cổng Pilot `--ep <ep_1> --pilot-frames` + `read_file` 2 ảnh `_pilot/*.jpg` trước khi chạy `--all`).

### 4.3. Nếu muốn mang dự án `wangwang-miaoba` sang máy khác để render tiếp

Chép các thư mục sau của `Du_an/wangwang-miaoba/` sang máy mới:
- Bắt buộc: `raw/`, `transcripts/`, `translations/`, `scripts/`
- Giữ tiến độ & cache: `output/`, `_tmp/`

Lưu ý: `Du_an/wangwang-miaoba/scripts/step4_dub_and_render.py` có đường dẫn `PROJ_DIR` và `FFMPEG`/`FFPROBE` đang trỏ cố định theo máy hiện tại (hoặc fallback `ffmpeg`/`ffprobe` trên `PATH`). Nếu chạy ở thư mục khác trên máy mới, chỉ cần cập nhật `PROJ_DIR` đầu file `step4_dub_and_render.py` hoặc dùng `vietsub-video-trung/template/scripts/step4_dub_karaoke_render.py --project-dir <duong_dan_moi>` (đã hỗ trợ `config_loader.py` tự dò đa máy).

---

## 5. 7 Chốt Kỹ Thuật & Bài Học Thực Chiến Đã Khóa Trong Code

1. **Mặt nạ làm mờ hardsub grayscale `"L"` (tránh nhòe toàn màn hình):** FFmpeg `alphamerge` đọc kênh luma thay vì alpha trên PNG RGB/RGBA nền trắng. Bắt buộc xuất `mask.png` mode `"L"` (`fill=248`, `GaussianBlur(12)`) và nối `[bg]gblur=sigma=24,eq=brightness=-0.08,format=yuva420p[blurred];[1:v]format=gray[msk];[blurred][msk]alphamerge[cover]`.
2. **Crop dải đáy trước khi chạy `RapidOCR`:** Video 2K/4K đưa nguyên khung hình vào OCR dễ trượt box chữ. Luôn crop dải đáy `(0.12*W, 0.75*H, 0.88*W, H)` (hoặc `0.60*H` với video dọc) rồi cộng bù tọa độ về khung gốc để lấy chính xác `hardsub_band` & `hardsub_x_band`.
3. **Đường dẫn Windows cho filter `ass=` trong FFmpeg:** Dấu `:` trong `C:\...` làm gãy parser filtergraph của FFmpeg. Bắt buộc truyền `cwd=tmp_ep` cho `subprocess.run` và dùng đường dẫn tương đối `ass=vi_karaoke.ass`.
4. **Đơn vị & định dạng `edge-tts` (`7.3.1`):** Tham số `pitch` chỉ nhận đơn vị `Hz` (không dùng `%`); timestamp `WordBoundary` tính theo 100-nanosecond ticks (`offset / 10_000_000.0`).
5. **Chống treo vô hạn WebSocket half-open (`edge-tts` + `aiohttp`):** `Communicate.__stream()` truyền `sock_read` cho `ClientSession`, không giới hạn khung WebSocket trên `ws_connect`, dễ treo vĩnh viễn khi kết nối nửa đóng (đã gặp ở Tập 25 `seg_019`). Bắt buộc truyền `connect_timeout=8, receive_timeout=12/15`, bọc mọi lượt stream trong `asyncio.wait_for(..., timeout=20.0)` (`12.0s` cho warmup), và đặt `timeout=` tường minh cho toàn bộ `subprocess.run` (`60s` / `120s` / `600s` NVENC / `900s` CPU).
6. **Cơ chế 11 tầng chống `NoAudioReceived` & chống chặn burst IP (đã gặp ở Tập 22 & Tập 26):**
   - **Smart Boundary:** Câu ngắn `<= 4` từ bỏ qua `WordBoundary`, vào thẳng `SentenceBoundary` ngay từ tầng 1 để tránh đốt burst quota WebSocket vô ích; chia nhịp `\kf` bằng `align_display_words` theo trọng số độ dài từ + dấu ngắt câu.
   - **Cache fast-path `0ms`:** Câu đã có `.mp3` (`> 200 bytes`) + `.words.json` trả về ngay không `sleep`; chỉ `sleep(0.32s)` sau mỗi lần tổng hợp mới qua mạng.
   - **10 tầng `edge-tts` + Backoff lũy tiến + Đổi giọng dự phòng:** Nếu thất bại, giãn nhịp `1.0s → 15.0s` (tổng ~74s), tự hạ `rate/pitch` về `+0%/+0Hz`, lọc sạch dấu câu, và thử đổi sang giọng tiếng Việt còn lại (`vi-VN-HoaiMyNeural` ↔ `vi-VN-NamMinhNeural`).
   - **Tầng 11 `gTTS` độc lập (`lang='vi'`):** Giải pháp cứu hộ cuối cùng qua Google Translate TTS trong `asyncio.to_thread(..., timeout=20.0)` để batch hàng chục tập không bao giờ sập giữa chừng.
7. **Smart Ducking `O(N)` bằng NumPy & chạy tuần tự từng tập:** Giữ nền gốc `0.85` ngoài vùng thoại, dìm mượt về `0.08` tại `union(zh, vi)` qua 2 lượt `boxcar_smooth` `45ms` (~`90ms` ramp) rồi trộn `voice_track * 1.05` + soft limiter `tanh` (`peak > 0.90`). Luôn chạy GPU/TTS/FFmpeg tuần tự từng tập và xóa `_tmp/<ep_key>` ngay sau khi encode xong để giữ trống ổ đĩa.

---

## 6. Sơ Đồ File Cốt Lõi Cần Đọc Đầu Tiên Ở Phiên Sau

| Mục đích | File cần đọc |
|---|---|
| Hiểu nhanh toàn bộ skill, quy tắc & cảnh báo | `skills/vietsub-video-trung/SKILL.md`, `rules/vietsub-video-trung.md`, `skills/vietsub-video-trung/references/technical-pitfalls.md` |
| Cài máy mới / sửa môi trường / login Douyin | `setup_machine.py` |
| Chuẩn template dùng lại cho kênh mới | `template/project.example.json`, `template/glossary.example.md`, `template/scripts/config_loader.py`, `template/scripts/step4_dub_karaoke_render.py`, `template/scripts/step5_audit_report.py` |
| Tiếp tục render nốt 17 tập kênh `wangwang-miaoba` | `Du_an/wangwang-miaoba/scripts/step4_dub_and_render.py`, `Du_an/wangwang-miaoba/raw/posts_manifest.json` |
