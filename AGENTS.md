# AGENTS.md — Hướng dẫn cho AI Agent trong repository `Vietsub-video-Trung`

Repository này đóng gói trọn bộ **Skill, Workflow, Rule và Template** tự động Vietsub Karaoke `\kf`, dịch phân vai AI và lồng tiếng Smart Ducking cho các kênh video Trung / Douyin.

## Cấu trúc mã nguồn

- `skills/vietsub-video-trung/` — Antigravity Skill chuẩn (`SKILL.md`, `scripts/init_project.py`, `references/technical-pitfalls.md`).
- `vendor/MediaCrawler/` — Mã nguồn sạch `MediaCrawler` tích hợp sẵn (không chứa `.venv`, `browser_data`, cookie hay `.db`), dùng cho Bước 1 tải kênh & đăng nhập QR đa nền tảng.
- `setup_machine.py`, `install.ps1`, `install.sh` — Bộ cài đặt đa máy tự động (đồng bộ skill + `vendor/MediaCrawler` + `AGENTS.md`, tạo `.venv` MediaCrawler, cài thư viện pipeline & chạy `--doctor` / `--login`).
- `template/` — Mẫu dự án mới (`project.example.json`, `glossary.example.md`) và bộ 5 script chuẩn hóa trong `template/scripts/`.
- `workflows/` — Workflow `run_workflow` (`workflow_translate_qa.py`) và runbook 5 bước (`vietsub-karaoke-pipeline.md`).
- `rules/vietsub-video-trung.md` — Quy tắc ràng buộc kỹ thuật bắt buộc tuân thủ khi vận hành pipeline.
- `assets/` — Ảnh kiểm chứng thực tế từ tập Pilot (`demo-karaoke-bo-cho.jpg`, `demo-karaoke-anh-bien.jpg`).

## Quy tắc vận hành bắt buộc (8 bài học thực chiến)

1. **Mặt nạ blur grayscale `"L"`:** Tạo `mask.png` chế độ `"L"` (`fill=248`, feather `GaussianBlur(12)`) và dùng `[bg]gblur=sigma=24,eq=brightness=-0.08,format=yuva420p[blurred];[1:v]format=gray[msk];[blurred][msk]alphamerge[cover]` — không dùng RGBA nền trắng cho `alphamerge`.
2. **RapidOCR crop dải đáy:** Trên video 2K/4K phải crop `(0.12*W, 0.75*H, 0.88*W, H)` (hoặc `0.60*H` cho video dọc) ở các câu `0.8s–4.5s`, rồi cộng bù tọa độ gốc.
3. **Whisper `large-v3` CUDA float16:** Nạp `torch/lib` trước khi import `faster_whisper`; bật `word_timestamps=True, condition_on_previous_text=False, beam_size=3`; tách segment con khi khoảng nghỉ giữa 2 từ `> 1.05s`.
4. **`edge-tts` chuẩn hóa:** `pitch` bắt buộc dùng `Hz` (không dùng `%`); `WordBoundary` chia `10_000_000.0` ra giây; `warmup_tts()` phải khởi động đủ mọi giọng (`break`, không `return` sớm); retry 8 lần; kẹp `atempo <= 1.48`; khớp từ hiển thị bằng `SequenceMatcher`.
5. **FFmpeg `ass=` trên Windows:** Luôn chạy `ffmpeg` với `cwd=tmp_ep` và tên tương đối `ass=vi_karaoke.ass`.
6. **Metadata gốc ở Bước 4:** Luôn ưu tiên đọc `width`, `height`, `duration_sec`, `hardsub_band`, `hardsub_x_band`, `start`/`end` từ `_zh.json` trước `_vi.json`.
7. **Smart Ducking `O(N)`:** Giữ nền `0.85` ngoài thoại, dìm mượt `90ms` (2 lần boxcar `45ms`) về `0.08` tại union `[zh_start-0.10, zh_end+0.12]` và `[vi_start-0.10, vi_end+0.12]`.
8. **Chạy tuần tự & Cổng Pilot:** Luôn chạy GPU/TTS/FFmpeg tuần tự từng tập; chạy Pilot 1 tập (`--ep ... --pilot-frames`), kiểm tra `ffprobe` + mở 2 ảnh bằng `read_file` trước khi chạy `--all`; xóa `_tmp/<ep_key>` ngay sau mỗi tập.

## Kiểm tra nhanh khi sửa code

- Không hardcode đường dẫn cá nhân hay secret trong mã nguồn runtime; dùng `config_loader.py` + `project.json` + biến môi trường (`FFMPEG_BIN`, `CUDA_TORCH_LIB`, `MEDIACRAWLER_DIR`, `WORK_ROOT`, `VIETSUB_PROJECT_DIR`).
- Kiểm tra cú pháp Python với `py_compile` cho script thường và `ast.parse` cho workflow top-level `await` (`workflow_translate_qa.py`, `step3_workflow_translate.py`).
