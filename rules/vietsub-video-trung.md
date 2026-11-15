# Quy Tắc Bắt Buộc: Pipeline Vietsub Karaoke `\kf` & Lồng Tiếng Video Trung

Áp dụng cho mọi thao tác tải kênh, nhận diện thoại, dịch thuật phân vai, tạo giọng đọc, render phụ đề Karaoke `\kf` và kiểm toán thành phẩm trong dự án `vietsub-video-trung` hoặc dự án khởi tạo từ bộ template này.

## 8 Quy Tắc Kỹ Thuật Bất Biến

1. **Mặt nạ làm mờ hardsub phải là ảnh grayscale `"L"`:**
   - Sinh `mask.png` chế độ `"L"` (`fill=248`, feather `GaussianBlur(12)`), tuyệt đối không dùng ảnh RGBA nền trắng cho `alphamerge`.
   - Graph FFmpeg chuẩn:
     `[bg]gblur=sigma=24,eq=brightness=-0.08,format=yuva420p[blurred];[1:v]format=gray[msk];[blurred][msk]alphamerge[cover]`
2. **RapidOCR phải crop dải đáy ở video 2K/4K rồi cộng bù tọa độ gốc:**
   - Crop vùng `(0.12*W, 0.75*H, 0.88*W, H)` (hoặc `0.60*H` với video dọc `H > W`) trên tối đa 10 câu thoại `0.8s–4.5s`, sau đó cộng bù `+x0_crop`, `+y0_crop`. Không đưa nguyên ảnh 2560×1440 vào RapidOCR.
3. **Whisper `large-v3` CUDA float16 & tách khoảng nghỉ `> 1.05s`:**
   - Nạp sẵn thư mục `torch\lib` (CUDA DLL) vào `PATH` và `os.add_dll_directory` trước khi import `faster_whisper`.
   - Bật `word_timestamps=True, condition_on_previous_text=False, beam_size=3`.
   - Tách segment con khi khoảng nghỉ giữa 2 từ liên tiếp `> 1.05s` để không gộp nhạc dạo đầu vào mốc `start`.
4. **`edge-tts` chuẩn `Hz` & đồng bộ `WordBoundary`:**
   - `pitch` trong `project.json` bắt buộc dùng đơn vị `Hz` (`+0Hz`, `-10Hz`, `+18Hz`); không dùng `%`.
   - Chia `offset` và `duration` của `WordBoundary` cho `10_000_000.0` để ra giây.
   - `warmup_tts()` phải chạy hết tất cả các giọng (dùng `break` trong vòng retry, không `return` sớm).
   - Retry 3 tầng (`WordBoundary` -> `SentenceBoundary` -> `SentenceBoundary` `+0%`/`+0Hz` khi câu ngắn + `pitch != 0Hz` gặp `NoAudioReceived`), dùng weighted character timing khi `not wb_words`; kẹp tốc độ `atempo <= 1.48`; khớp từ hiển thị bằng `difflib.SequenceMatcher`.
5. **FFmpeg filter `ass=` trên Windows:**
   - Luôn chạy `subprocess.run(..., cwd=str(tmp_ep))` và dùng tên tương đối `ass=vi_karaoke.ass` để tránh lỗi phân tích dấu `:` của đường dẫn ổ đĩa Windows.
6. **Ưu tiên metadata gốc từ `_zh.json` ở Bước 4:**
   - Luôn đọc `width`, `height`, `duration_sec`, `hardsub_band`, `hardsub_x_band`, `start`, `end` từ `transcripts/<ep>_zh.json` trước khi fallback sang `_vi.json`.
7. **Smart Ducking O(N) bằng NumPy boxcar:**
   - Giữ âm thanh gốc ở mức `0.85` ngoài thoại; dìm mượt `90ms` (2 lần `boxcar_smooth` cửa sổ `45ms`) về `0.08` trên hợp (union) của `[zh_start - 0.10, zh_end + 0.12]` và `[vi_start - 0.10, vi_end + 0.12]`.
8. **Chạy tuần tự + Cổng kiểm tra Pilot 1 tập + Dọn `_tmp`:**
   - Luôn chạy GPU/TTS/FFmpeg tuần tự từng tập.
   - Chạy Pilot 1 tập (`--ep <ep_key> --pilot-frames`), kiểm tra `ffprobe` và soi trực tiếp 2 ảnh JPEG giữa câu thoại `\kf` bằng `read_file` trước khi chạy `--all`.
   - Xóa `_tmp/<ep_key>` ngay sau khi mỗi tập render xong và verify đạt chuẩn.

## Cấu Hình & Bảo Mật

- Không hardcode đường dẫn cá nhân (`<HOME>/...`), cookie, token hay `sec_uid` cố định trong mã nguồn runtime; dùng `config_loader.py` + `project.json`.
- Sau khi hoàn tất `--all`, bắt buộc chạy `step5_audit_report.py` để xác nhận toàn bộ tập đạt lệch thời lượng `< 0.6s` và xuất `BAO_CAO_SAN_XUAT.md`.
