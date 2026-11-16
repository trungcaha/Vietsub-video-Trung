# G-OmniVoice Studio — Clone Giọng & Làm Trong 48kHz Đa Máy

Bộ công cụ chạy local trên GPU (hỗ trợ fallback CPU / Apple MPS) để tạo giọng đọc tiếng Việt & tiếng Anh chất lượng cao từ **20 giọng đã clone/tinh chỉnh sẵn** trong `voices/`, tích hợp chuẩn hóa số/ngày/tiền tiếng Việt (`vn_textnorm.py`), khử tạp âm + phục hồi dải cao 48kHz qua **ClearerVoice**, và trang thư viện nghe thử offline `giong-clone.html`.

---

## 1. Yêu cầu hệ thống

- **Python**: `3.10+` trên PATH (bộ cài dùng `uv` tự động tạo `.venv` Python `3.12` tách rời).
- **GPU khuyến nghị**: NVIDIA GPU VRAM `>= 6–8 GB` (CUDA 12.x) để tổng hợp giọng nhanh gần thời gian thực; vẫn chạy được trên CPU hoặc macOS Apple Silicon (MPS).
- **FFmpeg & FFprobe**: Đã cài trên `PATH` (hoặc truyền qua `FFMPEG_BIN` / `FFPROBE_BIN`).
- **Ổ cứng trống**: ~`12 GB` cho bản đầy đủ (~`6 GB` cho bản `--minimal`), không tính mã nguồn repo.

---

## 2. Cài đặt trên máy mới chỉ 1 lệnh

Sau khi clone repo `Vietsub-video-Trung`:

### Bản đầy đủ (2 `.venv` + toàn bộ model Việt/Anh + tách nhạc RoFormer + ClearerVoice 48kHz)
- **Windows (PowerShell):**
  ```powershell
  .\tools\g-omnivoice\install_omnivoice.ps1
  ```
- **macOS / Linux:**
  ```bash
  ./tools/g-omnivoice/install_omnivoice.sh
  ```
- **Hoặc gọi Python trực tiếp (mọi OS):**
  ```bash
  python tools/g-omnivoice/setup_omnivoice.py
  ```

### Các tùy chọn cài đặt khác
| Lệnh | Tác dụng |
|---|---|
| `python tools/g-omnivoice/setup_omnivoice.py --minimal` | Chỉ tải model tiếng Việt (`g-group-ai-lab/g-omnivoice`, ~3.1 GB) + ClearerVoice 48kHz (~2.3 GB), bỏ qua `model-goc` & `sep_models` |
| `python tools/g-omnivoice/setup_omnivoice.py --skip-models` | Chỉ tạo 2 `.venv` + đồng bộ skill `g-omnivoice` (model sẽ tự tải khi chạy lần đầu) |
| `python tools/g-omnivoice/setup_omnivoice.py --doctor` | Kiểm tra sức khỏe GPU, `.venv`, ffmpeg, 20 giọng và trạng thái model |
| `python tools/g-omnivoice/setup_omnivoice.py --smoke-test` | Tạo thử 1 câu WAV ngắn bằng giọng `dinh-soan` để xác nhận chạy thật thành công |

---

## 3. Thư viện 20 giọng đã train / clone sẵn (`voices/`)

Mở trực tiếp file [giong-clone.html](giong-clone.html) bằng trình duyệt để nghe từng mẫu gốc (`ref.wav`) và bản demo clone (`demo.wav`), hoặc liệt kê bằng lệnh:

```bash
tools/g-omnivoice/.venv/Scripts/python.exe tools/g-omnivoice/clone.py --list-voices
```

| STT | ID giọng | Tên hiển thị | Giới tính · Vùng | Trạng thái | Thể loại phù hợp |
|---:|---|---|---|---|---|
| 1 | `dinh-soan` | **Đình Soạn** | Nam · Miền Nam | Mặc định | Truyện ma dân gian, kể chuyện đêm khuya |
| 2 | `ngoc-ly` | **Ngọc Ly** | Nữ | Dự phòng | Tâm sự, truyện ma |
| 3 | `adam-top-top` | **Adam Tốp Tốp** | Nam · Miền Nam | Đang dùng | Hoạt hình y khoa hài, nhiều vai qua `@speed` (`0.85..1.14`) |
| 4 | `duyen-ha-my` | **Duyên Hà My** | Nữ · Miền Nam | Đang dùng | Drama công sở (sếp / nhân vật đanh) |
| 5 | `mai-be-phuong` | **Mai Bé Phương** | Nữ · Miền Nam | Đang dùng | Drama công sở (nhân viên / giọng trẻ) |
| 6 | `en-playful-story` | **Playful Story (EN)** | Nữ · Tiếng Anh Mỹ | Mới clone | Học tiếng Anh, stories (`lang="en"`, dùng `model-goc`) |
| 7 | `anh` | **Anh** | Nam | Mới clone | Thuyết minh tài liệu, tin tức / phát thanh |
| 8 | `dung` | **Dũng** | Nam | Mới clone | Thơ, ca dao, tâm sự |
| 9 | `giang` | **Giang** | Nữ · Miền Bắc | Mới clone | Kể chuyện dài, truyền cảm hứng |
| 10 | `hien` | **Hiền** | Nữ | Mới clone | Tin tức / phát thanh, kể chuyện dài |
| 11 | `hoang-dang` | **Hoàng Đặng** | Nam | Mới clone | Truyện ma, review / quảng cáo |
| 12 | `huyen` | **Huyền** | Nữ | Mới clone | Truyền cảm hứng, tin tức / phát thanh |
| 13 | `mai` | **Mai** | Nữ | Mới clone | Review / quảng cáo, drama công sở |
| 14 | `ngan-bubbly` | **Ngân (trong trẻo)** | Nữ | Mới clone | Thiếu nhi / vui nhộn, review / quảng cáo |
| 15 | `ngan-nguyen` | **Ngân Nguyễn** | Nữ | Mới clone | Truyền cảm hứng, tâm sự |
| 16 | `nhat-phong` | **Nhật Phong** | Nam | Mới clone | Kể chuyện dài, truyện ma |
| 17 | `nhu` | **Như** | Nữ · Miền Bắc | Mới clone | Tin tức / phát thanh, review / quảng cáo |
| 18 | `quang-nguyen` | **Quang Nguyên** | Nam | Mới clone | Review sản phẩm / affiliate, Shorts |
| 19 | `thao` | **Thảo** | Nữ | Mới clone | Tản văn, tâm sự chữa lành |
| 20 | `trung` | **Trung** | Nam | Mới clone | Truyện ma, kể chuyện đêm khuya |

---

## 4. Hướng dẫn tạo voice ngay

### A. Đọc 1 câu hoặc file văn bản từ giọng có sẵn
```bash
# Windows (trên macOS/Linux thay .venv/Scripts/python.exe bằng .venv/bin/python)
tools/g-omnivoice/.venv/Scripts/python.exe tools/g-omnivoice/clone.py ^
  --voice dinh-soan ^
  --text "Tăng 15% lên 6.3 tỷ đồng vào ngày 16/11/2026." ^
  --out demo_dinh_soan.wav ^
  --enhance
```
*(Bỏ `--enhance` nếu chỉ cần xuất nhanh 24kHz; thêm `--lang en` hoặc chọn `en-playful-story` để đọc tiếng Anh bằng `model-goc`.)*

### B. Tạo hội thoại nhiều vai / nhiều tốc độ
```bash
tools/g-omnivoice/.venv/Scripts/python.exe tools/g-omnivoice/dialogue.py \
  tools/g-omnivoice/examples/hoi_thoai_stickman.txt out_stickman.wav --enhance
```
Hoặc dùng 1 giọng chia nhiều vai bằng `@tốc độ` với `examples/hoi_thoai_adam.txt`.

### C. Lồng tiếng hàng loạt cho dự án video
- **Kiểu truyện kể / drama (`script.json` -> `audio/NNN.wav`, `voice.wav`, `timings.json`, `timings.js`):**
  ```bash
  python tools/g-omnivoice/pipelines/tts_omnivoice.py path/to/project
  ```
- **Kiểu word-timing chi tiết (`work/script.json` -> `work/voiceover.wav`, `work/phrases.json`, `web/phrases_data.js`):**
  ```bash
  python tools/g-omnivoice/pipelines/tts_phrases.py path/to/project
  ```

### D. Tách nhạc & clone thêm giọng mới
1. Chạy tách giọng & khử tạp âm 48kHz:
   ```bash
   tools/g-omnivoice/.venv/Scripts/python.exe tools/g-omnivoice/clean_voice.py source.mp4 tmp_clean/
   ```
2. Cắt đoạn nói rõ dài **5–10 giây** vào `voices/<id-moi>/ref.wav`, chép lời chính xác vào `ref.txt`, tạo `meta.json` (theo mẫu `voices/dinh-soan/meta.json`).
3. Cập nhật lại trang thư viện offline `giong-clone.html`:
   ```bash
   tools/g-omnivoice/.venv/Scripts/python.exe tools/g-omnivoice/build_dashboard.py
   ```

---

## 5. Kiến trúc 2 `.venv` & Biến môi trường tùy chọn

- **Vì sao cần tách 2 `.venv` riêng (`tools/g-omnivoice/.venv` và `tools/voice-enhance/.venv`)?**
  `omnivoice==0.2.1` và `audio-separator` yêu cầu `numpy>=2` cùng `transformers>=5`, trong khi `clearvoice==0.1.2` bắt buộc `numpy==1.26.4` và `soundfile==0.12.1`. Việc tách riêng 2 `.venv` Python `3.12` giúp chạy nối tiếp hoàn toàn tự động qua `omni_env.run_enhance()` mà không xung đột thư viện.
- **Biến môi trường ghi đè đường dẫn (tùy chọn):**
  - `OMNIVOICE_MODEL_DIR`: Thư mục chứa weights `g-group-ai-lab/g-omnivoice` (nếu dùng chung giữa nhiều dự án).
  - `OMNIVOICE_MODEL_EN_DIR`: Thư mục chứa weights `k2-fsa/OmniVoice`.
  - `VOICE_ENHANCE_DIR`: Thư mục cài `voice-enhance`.
  - `OMNIVOICE_SEP_DIR`: Thư mục chứa model RoFormer `sep_models`.
  - `FFMPEG_BIN` / `FFPROBE_BIN`: Đường dẫn binary `ffmpeg` / `ffprobe`.
