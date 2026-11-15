# Workflow Runbook: Vietsub Karaoke `\kf` & Lồng Tiếng Smart Ducking (5 Bước)

Quy trình chuẩn hóa để chuyển toàn bộ một kênh video Trung/Douyin thành video tiếng Việt phân vai, phụ đề Karaoke quét màu `\kf` và giữ nguyên âm thanh nền tự nhiên.

## Bước 0: Khởi tạo dự án & Cấu hình vai

```bash
python skills/vietsub-video-trung/scripts/init_project.py \
  --slug <ten-du-an> \
  --dest <thu-muc-chua-du-an> \
  --channel-url "https://www.douyin.com/user/<sec_uid>"
```

1. Mở `<du-an>/project.json`: kiểm tra `sec_uid`, `compilation_min_sec` (`600`), `roles` (`voice`, `rate`, `pitch` đơn vị **`Hz`**, `style`, `color_bgr`).
2. Mở `<du-an>/glossary.md`: điền bảng tên nhân vật, xưng hô và quy tắc thoại riêng của series.

---

## Bước 1: Tải video kênh & lập `posts_manifest.json`

Chạy bằng Python của môi trường `MediaCrawler`:

```bash
<mediacrawler-venv-python> scripts/step1_download_channel.py --project-dir "<du-an>"
```

**Cổng kiểm chứng 1:**
- `raw/posts_manifest.json` tồn tại và đếm đúng `single_episodes_count` vs `compilations_count`.
- Mọi tập tải về đều qua `ffprobe` (`width`, `height`, `duration_sec`).

---

## Bước 2: Nhận diện thoại Whisper + đo `f0_hz` + RapidOCR dải đáy

```bash
python scripts/step2_transcribe_ocr.py --project-dir "<du-an>"
```

**Lưu ý kỹ thuật:**
- Script tự nạp `torch/lib` trước khi import `faster_whisper` (`large-v3`, `CUDA float16`, `word_timestamps=True`, `condition_on_previous_text=False`, tách segment khi nghỉ `> 1.05s`).
- `RapidOCR` chỉ crop dải đáy `(0.12*W, 0.75*H, 0.88*W, H)` (hoặc `0.60*H` cho video dọc) ở câu `0.8s–4.5s` rồi cộng bù tọa độ gốc.

**Cổng kiểm chứng 2:**
- Đủ `<ep_key>_zh.json` và `<ep_key>_zh.srt` cho toàn bộ tập lẻ.
- Kiểm tra `hardsub_band` và `ocr_meta.method == "ocr_detected"` (hoặc lý do fallback hợp lệ nếu video không có hardsub).

---

## Bước 3: Dịch phân vai AI song song & QA Gate (`/run-workflow`)

Chạy công cụ `run_workflow` trỏ vào `scripts/step3_workflow_translate.py` (hoặc `workflows/workflow_translate_qa.py`):

- `ScriptPath`: `<du-an>/scripts/step3_workflow_translate.py`
- `Cwd`: `<du-an>`
- `Args`: `{"project_dir": "<du-an>", "batch_size": 4, "model": "flash"}`

Hoặc đặt biến môi trường `VIETSUB_PROJECT_DIR=<du-an>`.

**Cổng kiểm chứng 3:**
- Workflow kết thúc với log: `TOÀN BỘ N TẬP ĐÃ ĐẠT CHUẨN 100%` (0 lỗi ở `Translation QA Gate`).
- Khớp 100% số `segments`, `id`, `role` hợp lệ, `vi_text` không sót chữ Hán, độ dài không vượt ngưỡng `atempo <= 1.48`.

---

## Bước 4: Pilot 1 tập -> Kiểm tra khung hình -> Render hàng loạt tuần tự

### 4A. Cổng kiểm chứng Pilot 1 tập (BẮT BUỘC trước `--all`)

```bash
python scripts/step4_dub_karaoke_render.py --project-dir "<du-an>" --ep <ep_key_dau_tien> --pilot-frames
```

1. Kiểm tra `output/<vi_file_stem>.mp4` bằng `ffprobe` (đủ luồng video + audio, lệch thời lượng `< 0.6s`).
2. Mở 2 ảnh trong `_pilot/` bằng `read_file` để soi trực tiếp:
   - Mặt nạ blur (`mask.png` grayscale) chỉ làm mờ gọn vùng hardsub gốc, **không làm nhòe toàn khung hình**.
   - Chữ Karaoke `\kf` hiển thị rõ nét, căn đáy cân đối, đang quét màu đúng theo từng từ và đúng màu nhân vật.
   - Đã xóa sạch `_tmp/<ep_key>` ngay sau tập Pilot.

### 4B. Render toàn bộ series (chỉ chạy sau khi Pilot đạt)

```bash
python scripts/step4_dub_karaoke_render.py --project-dir "<du-an>" --all
```

*(Chạy tuần tự từng tập để không xung đột GPU NVENC / network edge-tts, tự dọn `_tmp/<ep_key>` sau mỗi tập.)*

---

## Bước 5: Kiểm toán thành phẩm & Xuất `BAO_CAO_SAN_XUAT.md`

```bash
python scripts/step5_audit_report.py --project-dir "<du-an>"
```

**Cổng kiểm chứng 5:**
- Toàn bộ tập lẻ đạt `PASS` (`output/*.mp4`, `.vi.srt`, `.vi.ass` chứa `\kf`, `|duration_out - duration_raw| < 0.6s`).
- Kiểm tra dung lượng trống ổ đĩa và đọc lại `BAO_CAO_SAN_XUAT.md` trước khi bàn giao.
