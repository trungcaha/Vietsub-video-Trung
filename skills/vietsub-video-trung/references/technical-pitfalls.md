# Chi Tiết Kỹ Thuật & 8 Bài Học Xương Máu (Technical Pitfalls)

Tài liệu này giải thích nguyên nhân gốc rễ, triệu chứng và cách khắc phục chuẩn cho 8 sự cố thực chiến đã gặp khi sản xuất series video Trung dài tập bằng pipeline Vietsub Karaoke `\kf`.

---

## 1. Grayscale `mask.png` cho FFmpeg `alphamerge`

- **Hiện tượng lỗi:** Dùng ảnh RGBA nền trắng hoặc ảnh RGB khi đưa vào `alphamerge` khiến FFmpeg đọc kênh luma nền trắng thành alpha toàn khung -> toàn bộ video bị làm mờ thay vì chỉ làm mờ dải phụ đề gốc.
- **Cách xử lý chuẩn:**
  1. Tạo ảnh grayscale mode `"L"` nền đen (`0`), vẽ hình chữ nhật bo góc tại `[x0, y_top, x1, y_bot]` với `fill=248`, làm mềm biên bằng `ImageFilter.GaussianBlur(radius=12)`.
  2. Trong FFmpeg `filter_complex`, ép mặt nạ qua `format=gray` trước khi ghép với luồng video đã blur:
     ```text
     [0:v]split[base][bg];
     [bg]gblur=sigma=24,eq=brightness=-0.08,format=yuva420p[blurred];
     [1:v]format=gray[msk];
     [blurred][msk]alphamerge[cover];
     [base][cover]overlay=0:0:shortest=1,ass=vi_karaoke.ass[v]
     ```
- **Tham số trong `project.json`:** `karaoke.gblur_sigma` (`24`), `karaoke.mask_brightness` (`-0.08`), `karaoke.mask_fill` (`248`), `karaoke.mask_feather` (`12`).

---

## 2. RapidOCR trên video 2K/4K phải crop dải đáy

- **Hiện tượng lỗi:** Đưa cả khung hình `2560x1440` hoặc `3840x2160` vào RapidOCR làm chữ nhỏ bị nén/mất nét ở bước resize detector, dẫn đến không bắt được box phụ đề và rơi về `default_low_ocr_hits`.
- **Cách xử lý chuẩn:**
  1. Chọn tối đa 10 câu thoại ổn định có `len(zh_text) >= 4` và `0.8 <= duration <= 4.5` giây; trích frame tại `start + 0.55 * duration`.
  2. Crop đúng dải chứa hardsub:
     - Video ngang (`W >= H`): `(0.12*W, 0.75*H, 0.88*W, H)`
     - Video dọc (`H > W`): `(0.12*W, 0.60*H, 0.88*W, H)`
  3. Đưa ảnh đã crop vào `RapidOCR()`, sau đó cộng bù `x0_crop` và `y0_crop` vào tọa độ từng đỉnh box để trả về đúng hệ tọa độ gốc, lọc ngoại lai theo trung vị `cy`, kẹp bề dày dải mờ trong `[0.068*H, 0.135*H]`.

---

## 3. Whisper `large-v3` CUDA float16 & tách pause `> 1.05s`

- **Hiện tượng lỗi:**
  - `faster_whisper` trên Windows báo thiếu `cublas64_*.dll` / `cudnn*.dll` dù PyTorch đã cài sẵn trong môi trường Python hoặc `.venv`.
  - Whisper gộp đoạn nhạc dạo hoặc im lặng dài đầu clip vào `segment.start`, khiến lồng tiếng phát sớm hoặc ducking cắt nhầm nhạc mở đầu.
- **Cách xử lý chuẩn:**
  1. Gọi `setup_cuda_dll_paths(cfg)` **trước** khi `from faster_whisper import WhisperModel` để tự dò `CUDA_TORCH_LIB`, `torch/lib`, `nvidia/*/bin` và thêm vào `PATH` + `os.add_dll_directory()`.
  2. Chạy `model.transcribe(..., language="zh", vad_filter=True, vad_parameters=dict(min_silence_duration_ms=350, speech_pad_ms=120), condition_on_previous_text=False, word_timestamps=True, beam_size=3)`.
  3. Duyệt mảng `s.words`; hễ `w.start - prev_w.end > 1.05` (tham số `whisper.pause_split_sec`) thì tách ngay thành segment độc lập trước khi tính `f0_hz`.

---

## 4. `edge-tts`: `pitch` dùng `Hz`, `WordBoundary`, fallback `SentenceBoundary`, warmup, retry & `SequenceMatcher`

- **Hiện tượng lỗi:**
  - Truyền `pitch="+10%"` vào `edge_tts.Communicate` gây lỗi WebSocket `NoAudioReceived` (Microsoft TTS chỉ nhận `Hz`, ví dụ `-10Hz`, `+18Hz`).
  - Câu thoại ngắn hoặc có dấu câu cuối kết hợp `pitch != +0Hz` (như `"Được rồi,"`) đôi khi khiến Microsoft TTS trả về rỗng `NoAudioReceived` khi bật `boundary="WordBoundary"`.
  - `warmup_tts()` dùng `return` sớm trong vòng lặp giọng khiến giọng thứ 2 chưa được khởi động kết nối.
  - Câu dịch có dấu câu/số khiến số token `display_tokens` khác số `WordBoundary` từ TTS -> lệch chữ khi quét `\kf`.
  - Tua âm quá `1.5x` làm giọng bị méo robot.
- **Cách xử lý chuẩn:**
  1. Validate toàn bộ `roles.*.pitch` phải kết thúc bằng `Hz`.
  2. `warmup_tts()` duyệt hết danh sách giọng duy nhất, dùng `break` (không `return`) khi nhận chunk audio đầu tiên.
  3. `WordBoundary` quy đổi giây bằng `offset / 10_000_000.0` và `duration / 10_000_000.0`; áp dụng **retry 3 tầng** (8 lần, backoff `0.25 + min(attempt, 4) * 0.35`):
     - `attempt < 3`: `boundary="WordBoundary"` giữ `(rate, pitch)` của vai (`attempt == 2` strip dấu câu cuối `[,;:\-—….!?]+$` nếu còn ký tự chữ/số).
     - `attempt 3..5`: fallback sang `boundary="SentenceBoundary"`, giữ nguyên `(rate, pitch)` của vai (`words_json` lưu `[]`).
     - `attempt >= 6`: `boundary="SentenceBoundary"`, đưa về `rate="+0%"`, `pitch="+0Hz"`, lọc chỉ giữ ký tự chữ/số + khoảng trắng (fallback `"ừ"` nếu rỗng).
  4. Khi `wb_words` có dữ liệu, khớp `display_tokens` qua `difflib.SequenceMatcher(a=d_norm, b=w_norm, autojunk=False)` và nội suy tuyến tính; khi `not wb_words` (fallback `SentenceBoundary`), `align_display_words` phân bổ `seg_dur` theo **weighted character timing** (`max(2.0, float(len(norm_token(tok)) or len(tok))) + (1.2 if tok[-1] in ",.!?;:" else 0.0)`), giữ đơn điệu và ép `out[-1]["end"] = seg_dur`.
  5. Nếu `raw_dur > avail`, tính `speed = min(atempo_max, raw_dur / avail)` với `atempo_max = 1.48`, nhân chia ngược `w["start"]`, `w["end"]` theo `actual_speed` thực tế của WAV sau `atempo`.

---

## 5. FFmpeg filter `ass=` trên Windows

- **Hiện tượng lỗi:** Truyền đường dẫn tuyệt đối có ký tự ổ đĩa `C:\...` vào `ass=C:\...\vi_karaoke.ass` khiến bộ phân tách filter của FFmpeg hiểu nhầm dấu `:` là dấu phân cách option.
- **Cách xử lý chuẩn:** Luôn gọi `subprocess.run(..., cwd=str(tmp_ep))` với file phụ đề nằm trong `tmp_ep` và filter viết tương đối: `ass=vi_karaoke.ass`.

---

## 6. Ưu tiên metadata gốc từ `_zh.json` trước `_vi.json`

- **Hiện tượng lỗi:** Subagent dịch thuật ở Bước 3 đôi khi chép nhầm giá trị ví dụ (như `1080x1920` hay `hardsub_band` mẫu) vào `_vi.json`, khiến Bước 4 vẽ sai cỡ chữ ASS hoặc sai vị trí mặt nạ blur.
- **Cách xử lý chuẩn:** Trong `step4_dub_karaoke_render.py`, luôn đọc `width`, `height`, `duration_sec`, `hardsub_band`, `hardsub_x_band`, và cặp `start`/`end` từng câu từ `transcripts/<ep_key>_zh.json` trước, chỉ fallback sang `_vi.json` nếu thiếu.

---

## 7. Smart Ducking O(N) bằng NumPy boxcar

- **Hiện tượng lỗi:** Dùng FFmpeg `sidechaincompress` hoặc ghép nhiều filter `volume=enable=...` cho hàng chục câu thoại chạy chậm và dễ giật biên âm lượng, hoặc cắt cụt tiếng động tự nhiên ở đoạn giao giữa thoại Trung và thoại Việt.
- **Cách xử lý chuẩn:**
  1. Khởi tạo vector `gain = np.full(n_samples, 0.85, dtype=np.float32)` tại 48 kHz.
  2. Trên từng câu, hạ `gain[d0:d1] = 0.08` tại **hợp (union)** `[min(zh_start, vi_start) - 0.10, max(zh_end, vi_end) + 0.12]`.
  3. Làm mượt đường bao bằng 2 lần `boxcar_smooth` cửa sổ `45ms` (`cumsum` độ phức tạp `O(N)`, tổng ramp `90ms`), sau đó trộn `orig_audio * gain[:, None] + voice_track[:, None] * 1.05` và soft-limiter `tanh` khi peak `> 0.90`. Thời gian xử lý `< 1s/tập`.

---

## 8. Chạy tuần tự + Cổng Pilot 1 tập + Dọn `_tmp/<ep_key>`

- **Hiện tượng lỗi:**
  - Chạy song song nhiều tiến trình `step4` cùng lúc gây tranh chấp encoder `h264_nvenc` (giới hạn session trên GPU tiêu dùng) và bị Microsoft `edge-tts` chặn rate-limit.
  - Để sót file WAV/MP3 tạm trong `_tmp/` làm đầy ổ đĩa nhanh chóng khi chạy hàng loạt 40+ tập.
- **Cách xử lý chuẩn:**
  1. Luôn chạy GPU/TTS/FFmpeg **tuần tự từng tập** trong một tiến trình duy nhất.
  2. Bắt buộc chạy **Pilot 1 tập** với `--ep <ep_key> --pilot-frames`, kiểm tra `ffprobe` và mở trực tiếp 2 ảnh `_pilot/*.jpg` bằng `read_file` để xác nhận blur band + quét màu `\kf` đạt chuẩn trước khi chạy `--all`.
  3. Gọi `shutil.rmtree(tmp_ep, ignore_errors=True)` ngay sau khi mỗi tập xuất xong và qua bước `probe_media`.
