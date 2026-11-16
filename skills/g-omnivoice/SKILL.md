---
name: g-omnivoice
description: >-
  Tổng hợp giọng nói tiếng Việt & tiếng Anh chất lượng cao bằng G-OmniVoice (zero-shot voice cloning,
  voice design, làm trong 48kHz ClearerVoice), kèm sẵn thư viện 20 giọng đã clone và bộ cài đặt đa máy.
  Dùng khi người dùng nhắc "g-omnivoice", "omnivoice", "clone giong", "tao voice", hoặc "thu vien giong".
---

# G-OmniVoice Studio — Tạo Giọng Clone & Làm Trong 48kHz

Bộ công cụ chạy local (ưu tiên GPU NVIDIA CUDA, fallback CPU / Apple MPS) để tạo giọng đọc từ **20 giọng đã clone sẵn** hoặc nhân bản giọng mới từ clip 5–10 giây, tự động chuẩn hóa số/ngày/tiền tiếng Việt và khử nhiễu phục hồi dải cao 48kHz qua **ClearerVoice**.

## 1. Cài đặt trên máy mới (1 lệnh)

```bash
# Cài đủ 2 .venv Python 3.12 + tải đủ model weights (~10 GB) + đồng bộ skill
python tools/g-omnivoice/setup_omnivoice.py

# Bản gọn nhẹ (chỉ tải model tiếng Việt ~3.1 GB + ClearerVoice ~2.3 GB)
python tools/g-omnivoice/setup_omnivoice.py --minimal

# Kiểm tra trạng thái môi trường & test nhanh 1 câu WAV
python tools/g-omnivoice/setup_omnivoice.py --doctor
python tools/g-omnivoice/setup_omnivoice.py --smoke-test
```

## 2. Danh sách 20 giọng đã clone sẵn (`tools/g-omnivoice/voices/`)

Mở trực tiếp `tools/g-omnivoice/giong-clone.html` trong trình duyệt để nghe thử toàn bộ giọng mẫu và bản demo.

| ID giọng | Tên | Giới tính / Vùng | Thể loại khuyên dùng |
|---|---|---|---|
| `dinh-soan` | **Đình Soạn** *(Mặc định)* | Nam · Miền Nam | Truyện ma dân gian, kể chuyện đêm khuya |
| `ngoc-ly` | **Ngọc Ly** *(Dự phòng)* | Nữ | Tâm sự, truyện ma |
| `adam-top-top` | **Adam Tốp Tốp** | Nam · Miền Nam | Hoạt hình y khoa hài, nhiều vai qua `@speed` (`0.85..1.14`) |
| `duyen-ha-my` | **Duyên Hà My** | Nữ · Miền Nam | Drama công sở (sếp/nhân vật nữ đanh) |
| `mai-be-phuong` | **Mai Bé Phương** | Nữ · Miền Nam | Drama công sở (nhân viên/giọng trẻ) |
| `en-playful-story` | **Playful Story (EN)** | Nữ · Tiếng Anh Mỹ | Học tiếng Anh, stories (`lang="en"`, dùng `model-goc`) |
| `anh` | **Anh** | Nam | Thuyết minh tài liệu, tin tức / phát thanh |
| `dung` | **Dũng** | Nam | Thơ, ca dao, tâm sự |
| `giang` | **Giang** | Nữ · Miền Bắc | Kể chuyện dài, truyền cảm hứng |
| `hien` | **Hiền** | Nữ | Tin tức / phát thanh, kể chuyện dài |
| `hoang-dang` | **Hoàng Đặng** | Nam | Truyện ma, review / quảng cáo |
| `huyen` | **Huyền** | Nữ | Truyền cảm hứng, tin tức / phát thanh |
| `mai` | **Mai** | Nữ | Review / quảng cáo, drama công sở |
| `ngan-bubbly` | **Ngân (trong trẻo)** | Nữ | Thiếu nhi / vui nhộn, review / quảng cáo |
| `ngan-nguyen` | **Ngân Nguyễn** | Nữ | Truyền cảm hứng, tâm sự |
| `nhat-phong` | **Nhật Phong** | Nam | Kể chuyện dài, truyện ma |
| `nhu` | **Như** | Nữ · Miền Bắc | Tin tức / phát thanh, review / quảng cáo |
| `quang-nguyen` | **Quang Nguyên** | Nam | Review sản phẩm / affiliate, Shorts |
| `thao` | **Thảo** | Nữ | Tản văn, tâm sự chữa lành |
| `trung` | **Trung** | Nam | Truyện ma, kể chuyện đêm khuya |

## 3. Các lệnh tạo voice thông dụng

- **Đọc 1 câu hoặc file văn bản từ giọng có sẵn (kèm làm trong 48kHz):**
  ```bash
  tools/g-omnivoice/.venv/Scripts/python.exe tools/g-omnivoice/clone.py \
    --voice dinh-soan --text "Đêm nay trời mưa rất to." --out out.wav --enhance
  ```
- **Hội thoại nhiều giọng / đổi tốc độ theo vai:**
  ```bash
  tools/g-omnivoice/.venv/Scripts/python.exe tools/g-omnivoice/dialogue.py \
    tools/g-omnivoice/examples/hoi_thoai_stickman.txt out_dlg.wav --enhance
  ```
- **Lồng tiếng kịch bản video hàng loạt (`script.json` -> `voice.wav` + `timings.json`):**
  ```bash
  python tools/g-omnivoice/pipelines/tts_omnivoice.py path/to/project
  ```
- **Lồng tiếng kèm word-level `phrases.json` & `silencedetect`:**
  ```bash
  python tools/g-omnivoice/pipelines/tts_phrases.py path/to/project
  ```
- **Workflow `/run-workflow` tạo voice hàng loạt & kiểm định `ffprobe`:**
  Chạy `run_workflow` với `workflows/workflow_omnivoice_tts.py`.

## 4. Quy trình thêm giọng clone mới

1. Tách nhạc nền & khử nhiễu từ MP3/MP4 nguồn:
   ```bash
   tools/g-omnivoice/.venv/Scripts/python.exe tools/g-omnivoice/clean_voice.py input.mp4 out_clean/
   ```
2. Cắt 1 đoạn nói sạch dài **5–10 giây** vào `tools/g-omnivoice/voices/<id-moi>/ref.wav`, chép chính xác từng chữ vào `ref.txt`, thêm `meta.json`.
3. Cập nhật trang thư viện offline:
   ```bash
   tools/g-omnivoice/.venv/Scripts/python.exe tools/g-omnivoice/build_dashboard.py
   ```

## 5. Quy tắc kỹ thuật bắt buộc

- **Giữ 2 `.venv` riêng biệt**: `g-omnivoice` dùng `numpy>=2` (`omnivoice==0.2.1`), còn `voice-enhance` dùng `clearvoice==0.1.2` (`numpy==1.26.4` & `soundfile==0.12.1`).
- **Chuẩn hóa số/ngày/ký hiệu tiếng Việt** bằng `vn_textnorm.normalize()` trước khi đưa vào model (phụ đề vẫn giữ nguyên văn bản gốc).
- **Chống vỡ tiếng (clipping)**: Kéo đỉnh về tối đa `0.89` (`-1 dBFS`) hoặc ghi trung gian `subtype="FLOAT"` trước khi chuẩn hóa `loudnorm` ở 48kHz.
- **Tuyệt đối không dùng `asetrate`** để đổi tốc độ/sample rate vì làm méo cao độ giọng; luôn dùng `aresample=48000` và `atempo` / `rubberband`.
- **Giọng tiếng Anh (`en-playful-story`)**: Tự động dùng `model-goc/` (`k2-fsa/OmniVoice`) với `language="en"` và bỏ qua `vn_textnorm`.
