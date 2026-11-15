---
name: vietsub-video-trung
description: >-
  Pipeline trọn gói Vietsub Karaoke \kf & lồng tiếng Smart Ducking cho toàn bộ video một kênh Douyin/Trung Quốc:
  tải video kênh, nhận diện thoại Whisper GPU + dò hardsub RapidOCR, dịch phân vai AI song song + QA,
  lồng tiếng edge-tts nhiều vai theo cao độ Hz, làm mờ hardsub gốc bằng mặt nạ grayscale, Smart Ducking giữ âm nền
  và kiểm toán ffprobe xuất báo cáo. Dùng khi người dùng nói "vietsub video trung", "vietsub douyin",
  "karaoke sub", "long tieng kenh trung", hoặc "dich kenh douyin".
---

# Vietsub Karaoke `\kf` & Lồng Tiếng Video Trung

Đóng gói quy trình 5 bước sản xuất hàng loạt video Trung/Douyin sang tiếng Việt: phụ đề Karaoke quét màu `\kf` theo từng từ, phân vai giọng đọc `edge-tts`, làm mờ mượt dải hardsub gốc và Smart Ducking giữ âm thanh nền tự nhiên.

## Thành phần đi kèm skill

| Thành phần | Vị trí | Chức năng |
|---|---|---|
| Khởi tạo dự án | [init_project.py](./scripts/init_project.py) | Sinh cây thư mục `raw/`, `transcripts/`, `translations/`, `output/`, `scripts/`, `project.json`, `glossary.md` |
| Trình tải kênh nhúng | [vendor/MediaCrawler/](./vendor/MediaCrawler/) | Mã nguồn sạch `MediaCrawler` đi kèm skill; tự động tạo `.venv` & đăng nhập QR qua `setup_machine.py` |
| Cấu hình mẫu | [project.example.json](./template/project.example.json) & [glossary.example.md](./template/glossary.example.md) | Tham số `ducking`, `karaoke`, `whisper`, `render`, bảng vai `roles` (`Hz`, `color_bgr`) và từ điển mẫu |
| Bộ script 5 bước | [template/scripts/](./template/scripts/) | `config_loader.py`, `step1_download_channel.py` .. `step5_audit_report.py` |
| Workflow dịch QA | [workflow_translate_qa.py](./workflows/workflow_translate_qa.py) & [step3_workflow_translate.py](./template/scripts/step3_workflow_translate.py) | Chạy `/run-workflow` dịch phân vai song song + QA Gate 0 lỗi |
| Runbook & Quy tắc | [vietsub-karaoke-pipeline.md](./workflows/vietsub-karaoke-pipeline.md) & [vietsub-video-trung.md](./rules/vietsub-video-trung.md) | Cổng kiểm chứng từng bước & quy định bắt buộc |
| Chi tiết kỹ thuật | [technical-pitfalls.md](./references/technical-pitfalls.md) | Giải phẫu 8 lỗi thực chiến & cấu hình chi tiết |

## Triển khai sang máy mới chỉ 3 lệnh

```bash
git clone https://github.com/trungcaha/Vietsub-video-Trung.git && cd Vietsub-video-Trung
python setup_machine.py            # Windows: .\install.ps1 | macOS/Linux: ./install.sh
python setup_machine.py --login dy # Quét QR đăng nhập Douyin lưu vào browser_data/
```

Các cờ hữu ích khác của `setup_machine.py`: `--doctor` (kiểm tra sức khỏe môi trường), `--skill-only` (chỉ đồng bộ skill/vendor/template/rules & `AGENTS.md`), `--skip-pip`, `--venv-target skill|repo|both`.

## Quy trình 5 bước

1. **Khởi tạo dự án**:
   `python scripts/init_project.py --slug <slug> --dest <path> --channel-url "<url>"`
   Sau đó chỉnh sửa `glossary.md` (tên nhân vật, xưng hô) và `roles` trong `project.json`.
2. **Bước 1 — Tải video kênh**:
   `python scripts/step1_download_channel.py --project-dir "<proj>"`
   Script tự động re-exec sang `.venv` của `MediaCrawler` nếu Python đang chạy thiếu `playwright`/`execjs`, đồng thời hỗ trợ fallback `yt-dlp`. Tạo `raw/posts_manifest.json`, tách tự động tập lẻ và hợp tập (`duration >= 600s` hoặc từ khóa `合集`/`纯享`).
3. **Bước 2 — Whisper (GPU `float16` / fallback CPU `int8`) + F0 + RapidOCR**:
   `python scripts/step2_transcribe_ocr.py --project-dir "<proj>"`
   Xuất `transcripts/<ep>_zh.json` (có `f0_hz`, `acoustic_hint`, `hardsub_band`, `hardsub_x_band`) và `_zh.srt`. Tự fallback mượt sang CPU `int8` nếu máy không có CUDA GPU.
4. **Bước 3 — Dịch phân vai & QA (`/run-workflow`)**:
   Chạy `run_workflow` với `ScriptPath="<proj>/scripts/step3_workflow_translate.py"`, `Cwd="<proj>"`.
   Cổng kiểm chứng: QA Gate báo **0 lỗi** (khớp 100% số câu, không sót chữ Hán, độ dài không tràn slot).
5. **Bước 4 — Pilot 1 tập -> `--all`**:
   - **Cổng Pilot (bắt buộc trước `--all`):**
     `python scripts/step4_dub_karaoke_render.py --project-dir "<proj>" --ep <ep_1> --pilot-frames`
     Kiểm tra `ffprobe` đạt chuẩn và mở 2 ảnh `_pilot/*.jpg` bằng `read_file` xác nhận mặt nạ blur gọn vùng hardsub + chữ `\kf` quét đúng màu nhân vật.
   - **Chạy hàng loạt tuần tự:**
     `python scripts/step4_dub_karaoke_render.py --project-dir "<proj>" --all`
6. **Bước 5 — Kiểm toán & Báo cáo**:
   `python scripts/step5_audit_report.py --project-dir "<proj>"`
   Kiểm tra `ffprobe` toàn bộ `.mp4` + `.vi.srt` + `.vi.ass`, xác nhận lệch thời lượng `< 0.6s`, dung lượng đĩa và xuất `BAO_CAO_SAN_XUAT.md` kèm link `file:///`.

## Lỗi đã gặp — phải nhớ

| Lỗi thực chiến | Cách đúng (bắt buộc) |
|---|---|
| `alphamerge` đọc luma nền trắng RGBA làm **nhòe cả khung hình** | Tạo `mask.png` grayscale `"L"` (`fill=248`, `GaussianBlur(12)`) + `[bg]gblur=sigma=24,eq=brightness=-0.08,format=yuva420p[blurred];[1:v]format=gray[msk];[blurred][msk]alphamerge[cover]` |
| Đưa nguyên ảnh 2K/4K vào `RapidOCR` bị **trượt box hardsub**, rơi về fallback | Crop dải đáy `(0.12*W, 0.75*H, 0.88*W, H)` (hoặc `0.60*H` cho dọc) ở các câu `0.8s–4.5s` rồi cộng bù tọa độ gốc |
| Whisper thiếu CUDA DLL hoặc **gộp nhạc dạo đầu** vào mốc `start` | Nạp sẵn `torch\lib` trước khi import `faster_whisper` (`large-v3` `float16`); bật `word_timestamps=True, condition_on_previous_text=False, beam_size=3`; tách segment khi khoảng nghỉ `> 1.05s` |
| `edge-tts` lỗi `%` pitch, lỡ warmup giọng 2, hoặc lệch chữ Karaoke | `pitch` bắt buộc dùng `Hz`; `WordBoundary` chia `10_000_000.0`; warmup đủ mọi giọng bằng `break` (không `return` sớm); retry 8 lần; kẹp `atempo <= 1.48`; khớp từ bằng `SequenceMatcher` |
| FFmpeg `ass=` báo lỗi cú pháp vì dấu `:` ổ đĩa Windows | Chạy `ffmpeg` với `cwd=tmp_ep` và tên tương đối `ass=vi_karaoke.ass` |
| Bước 3 chép nhầm kích thước / `hardsub_band` mẫu vào `_vi.json` | Bước 4 luôn ưu tiên đọc `width`, `height`, `duration_sec`, `hardsub_band`, `hardsub_x_band`, `start`/`end` từ `_zh.json` trước `_vi.json` |
| `sidechaincompress` chậm hoặc cắt cụt tiếng động giữa 2 lượt thoại | Dùng NumPy Smart Ducking `O(N)`: nền `0.85`, dìm mượt `90ms` (2 lần boxcar `45ms`) về `0.08` tại union `[zh_start-0.10, zh_end+0.12]` & `[vi_start-0.10, vi_end+0.12]` |
| Render song song treo NVENC / rate-limit TTS / tràn đĩa `_tmp` | Chạy GPU/TTS/FFmpeg **tuần tự từng tập**; qua cổng **Pilot 1 tập** (`read_file` 2 ảnh + `ffprobe`) trước `--all`; xóa `_tmp/<ep_key>` ngay sau mỗi tập |

Chi tiết công thức & lý do từng lỗi xem thêm tại [references/technical-pitfalls.md](./references/technical-pitfalls.md).
