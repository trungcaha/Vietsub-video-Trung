# -*- coding: utf-8 -*-
r"""Bước 2: Nhận diện thoại (Whisper large-v3 CUDA float16), đo cao độ f0_hz
và dò tọa độ hardsub tiếng Trung (RapidOCR crop dải đáy) cho toàn bộ tập lẻ.
Chạy: python scripts/step2_transcribe_ocr.py [--project-dir <path>] [--force] [--ep <ep_key>]
"""

import argparse
import io
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from config_loader import (  # noqa: E402
    add_project_dir_arg,
    fmt_srt_ts,
    load_project_config,
    setup_cuda_dll_paths,
)

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "buffer"):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

HALLUCINATION_PATTERNS = [
    "字幕",
    "优优独播剧场",
    "amara.org",
    "请不吝点赞",
    "订阅转发",
    "谢谢观看",
    "感谢观看",
    "打赏支持",
    "明镜与点点",
    "中文字幕",
]


def decode_audio_16k(mp4_path: Path, ffmpeg_bin: str) -> "np.ndarray":
    import numpy as np

    res = subprocess.run(
        [
            ffmpeg_bin,
            "-v",
            "error",
            "-i",
            str(mp4_path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-f",
            "f32le",
            "-",
        ],
        capture_output=True,
        check=True,
    )
    return np.frombuffer(res.stdout, dtype=np.float32).copy()


def is_noise_text(txt: str) -> bool:
    t = txt.strip()
    if not t:
        return True
    tl = t.lower()
    if any(p in tl for p in HALLUCINATION_PATTERNS):
        return True
    stripped = re.sub(r"[\s\.,!?，。！？、~…\-—\"'“”‘’]+", "", t)
    if not stripped:
        return True
    if len(stripped) >= 6 and len(set(stripped)) == 1:
        return True
    return False


def estimate_f0_hz(audio_slice: "np.ndarray", sr: int = 16000) -> float:
    """Ước tính tần số cơ bản trung vị f0_hz trên lát cắt âm thanh bằng autocorrelation."""
    import numpy as np

    if len(audio_slice) < int(0.08 * sr):
        return 0.0
    frame_len = int(0.04 * sr)
    hop = int(0.02 * sr)
    if len(audio_slice) < frame_len:
        return 0.0

    frames = []
    rms_vals = []
    for start in range(0, len(audio_slice) - frame_len + 1, hop):
        fr = audio_slice[start : start + frame_len]
        r = float(np.sqrt(np.mean(fr * fr) + 1e-12))
        frames.append(fr)
        rms_vals.append(r)

    if not rms_vals:
        return 0.0
    med_rms = float(np.median(rms_vals))
    thresh = max(0.008, 0.35 * med_rms)

    lag_min = sr // 450
    lag_max = sr // 75
    f0s: List[float] = []

    for fr, r in zip(frames, rms_vals):
        if r < thresh:
            continue
        fr0 = fr - np.mean(fr)
        denom = float(np.dot(fr0, fr0))
        if denom <= 1e-9:
            continue
        corr = np.correlate(fr0, fr0, mode="full")[len(fr0) - 1 :]
        sub = corr[lag_min : lag_max + 1] / denom
        if len(sub) == 0:
            continue
        best_idx = int(np.argmax(sub))
        if float(sub[best_idx]) >= 0.45:
            lag = lag_min + best_idx
            f0s.append(sr / float(lag))

    if not f0s:
        return 0.0
    return round(float(np.median(f0s)), 1)


def f0_to_hint(f0_hz: float, roles_cfg: Dict[str, Any]) -> str:
    """Sinh gợi ý âm học f0 dựa theo dải f0_range trong project.json."""
    if f0_hz <= 0.0:
        return "unknown"

    matched: List[str] = []
    for role_key, info in (roles_cfg or {}).items():
        rng = info.get("f0_range")
        if isinstance(rng, (list, tuple)) and len(rng) == 2:
            lo, hi = float(rng[0]), float(rng[1])
            if lo <= f0_hz <= hi:
                label = info.get("label") or role_key
                matched.append(f"{role_key} ({label})")

    if f0_hz >= 235.0:
        band_tag = "high_voice"
    elif f0_hz >= 155.0:
        band_tag = "mid_voice"
    else:
        band_tag = "deep_voice"

    if matched:
        return f"{band_tag} -> ứng viên: {', '.join(matched)}"
    return band_tag


def detect_hardsub_band(
    mp4_path: Path,
    segments: List[Dict[str, Any]],
    width: int,
    height: int,
    ocr: Any,
    tmp_jpg: Path,
    ffmpeg_bin: str,
) -> Tuple[List[int], Dict[str, Any]]:
    """Dò [y_top, y_bot] và [x0, x1] của hardsub tiếng Trung bằng crop vùng đáy rồi cộng bù tọa độ gốc."""
    import numpy as np
    from PIL import Image

    if height > width:
        default_top = int(0.78 * height)
        default_bot = int(0.88 * height)
    else:
        default_top = int(0.895 * height)
        default_bot = int(0.978 * height)
    default_x_band = [int(0.14 * width), int(0.86 * width)]

    if not segments:
        return [default_top, default_bot], {
            "method": "default_no_segments",
            "boxes_found": 0,
            "has_hardsub": False,
            "x_band": default_x_band,
        }

    ideal = [s for s in segments if len(s["zh_text"]) >= 4 and 0.8 <= s["duration"] <= 4.5]
    if len(ideal) >= 4:
        step = max(1, len(ideal) // 10)
        picked = ideal[::step][:10]
    else:
        picked = sorted(segments, key=lambda s: len(s["zh_text"]), reverse=True)[:10]
    timestamps = sorted(round(s["start"] + 0.55 * s["duration"], 2) for s in picked)

    x0_crop = int(0.12 * width)
    x1_crop = int(0.88 * width)
    y0_crop = int(0.60 * height) if height > width else int(0.75 * height)

    boxes_y: List[Tuple[float, float, float, float, float, str]] = []
    for ts in timestamps:
        tmp_jpg.unlink(missing_ok=True)
        subprocess.run(
            [
                ffmpeg_bin,
                "-v",
                "error",
                "-y",
                "-ss",
                f"{ts:.2f}",
                "-i",
                str(mp4_path),
                "-frames:v",
                "1",
                str(tmp_jpg),
            ],
            check=False,
        )
        if not tmp_jpg.exists():
            continue
        with Image.open(tmp_jpg) as im:
            crop = np.array(im.crop((x0_crop, y0_crop, x1_crop, height)))
        res, _ = ocr(crop)
        tmp_jpg.unlink(missing_ok=True)
        for box, txt, sc in res or []:
            if float(sc) < 0.60:
                continue
            ys = [p[1] + y0_crop for p in box]
            xs = [p[0] + x0_crop for p in box]
            cx = sum(xs) / 4.0
            cy = sum(ys) / 4.0
            y0, y1 = min(ys), max(ys)
            x0, x1 = min(xs), max(xs)
            bh = y1 - y0
            if (
                y0_crop <= cy <= 0.99 * height
                and abs(cx - width / 2.0) < 0.32 * width
                and 0.015 * height <= bh <= 0.14 * height
                and len(txt.strip()) >= 2
            ):
                boxes_y.append((y0, y1, cy, x0, x1, txt.strip()[:30]))

    if len(boxes_y) < 2:
        return [default_top, default_bot], {
            "method": "default_low_ocr_hits",
            "boxes_found": len(boxes_y),
            "has_hardsub": bool(len(boxes_y) > 0),
            "x_band": default_x_band,
        }

    med_cy = float(np.median([b[2] for b in boxes_y]))
    inliers = [b for b in boxes_y if abs(b[2] - med_cy) <= 0.06 * height]
    if len(inliers) < 2:
        inliers = boxes_y

    raw_top = min(b[0] for b in inliers)
    raw_bot = max(b[1] for b in inliers)
    y_top = max(0, int(raw_top - 0.016 * height))
    y_bot = min(height, int(raw_bot + 0.016 * height))

    min_h = int(0.068 * height)
    max_h = int(0.135 * height)
    band_h = y_bot - y_top
    if band_h < min_h:
        center_y = (y_top + y_bot) // 2
        y_top = center_y - min_h // 2
        y_bot = y_top + min_h
    elif band_h > max_h:
        c_med = int(med_cy)
        y_top = c_med - max_h // 2
        y_bot = y_top + max_h

    y_top = max(0, min(height - min_h, y_top))
    y_bot = min(height, max(y_top + min_h, y_bot))

    min_x = min(b[3] for b in inliers)
    max_x = max(b[4] for b in inliers)
    x_band = [
        max(int(0.08 * width), min(int(0.18 * width), int(min_x - 0.04 * width))),
        min(int(0.92 * width), max(int(0.82 * width), int(max_x + 0.04 * width))),
    ]

    return [y_top, y_bot], {
        "method": "ocr_detected",
        "boxes_found": len(boxes_y),
        "inliers_used": len(inliers),
        "has_hardsub": True,
        "x_band": x_band,
        "sample_texts": [b[5] for b in inliers[:4]],
    }


def split_whisper_segments(
    raw_segs: Any,
    audio_16k: "np.ndarray",
    dur_sec: float,
    pause_split_sec: float,
    roles_cfg: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Tách segment Whisper theo khoảng nghỉ word-level > pause_split_sec và ước tính f0_hz."""
    segments: List[Dict[str, Any]] = []
    seg_id = 0
    for s in raw_segs:
        words_list = list(getattr(s, "words", None) or [])
        chunks_of_words = []
        if words_list:
            cur_w = [words_list[0]]
            for w in words_list[1:]:
                if float(w.start) - float(cur_w[-1].end) > pause_split_sec:
                    chunks_of_words.append(cur_w)
                    cur_w = [w]
                else:
                    cur_w.append(w)
            chunks_of_words.append(cur_w)
        else:
            chunks_of_words.append([])

        for sub_w in chunks_of_words:
            if sub_w:
                txt = "".join(str(w.word) for w in sub_w).strip()
                if is_noise_text(txt):
                    continue
                start_s = round(max(0.0, float(sub_w[0].start) - 0.04), 3)
                end_s = round(min(dur_sec, max(start_s + 0.20, float(sub_w[-1].end) + 0.08)), 3)
            else:
                txt = (s.text or "").strip()
                if is_noise_text(txt):
                    continue
                start_s = max(0.0, float(s.start))
                end_s = min(dur_sec, float(s.end))
                if end_s - start_s > len(txt) * 0.55 + 1.5:
                    start_s = max(start_s, end_s - (len(txt) * 0.45 + 0.8))
                start_s = round(start_s, 3)
                end_s = round(max(start_s + 0.20, end_s), 3)

            if end_s - start_s < 0.12:
                continue
            seg_id += 1
            sl = audio_16k[int(start_s * 16000) : int(end_s * 16000)]
            f0 = estimate_f0_hz(sl, sr=16000)
            segments.append(
                {
                    "id": seg_id,
                    "start": start_s,
                    "end": end_s,
                    "duration": round(end_s - start_s, 3),
                    "f0_hz": f0,
                    "acoustic_hint": f0_to_hint(f0, roles_cfg),
                    "zh_text": txt,
                }
            )
    return segments


def main() -> None:
    parser = argparse.ArgumentParser(description="Bước 2: Whisper large-v3 GPU + F0 + RapidOCR crop dải đáy")
    add_project_dir_arg(parser)
    parser.add_argument("--force", action="store_true", help="Chạy lại cả những tập đã có transcript")
    parser.add_argument("--ep", type=str, default="", help="Chỉ chạy 1 ep_key cụ thể")
    args = parser.parse_args()

    cfg = load_project_config(args.project_dir or None)
    # Bắt buộc nạp CUDA DLL trước khi import faster_whisper
    dll_dirs = setup_cuda_dll_paths(cfg)

    from faster_whisper import WhisperModel
    from rapidocr_onnxruntime import RapidOCR

    raw_dir = Path(cfg["dirs"]["raw"])
    trans_dir = Path(cfg["dirs"]["transcripts"])
    trans_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = raw_dir / "posts_manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Chưa có manifest Bước 1 tại {manifest_path}")

    ffmpeg_bin = cfg["tools"]["ffmpeg"]
    w_cfg = cfg["whisper"]
    roles_cfg = cfg.get("roles") or {}

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    episodes = [e for e in manifest.get("episodes", []) if not e.get("is_compilation")]
    if args.ep:
        episodes = [e for e in episodes if e["ep_key"] == args.ep]

    print(
        f"=== BƯỚC 2: TRANSCRIBE + F0 + OCR CHO {len(episodes)} TẬP (CUDA DLL dirs={len(dll_dirs)}) ===",
        flush=True,
    )

    primary_model = w_cfg.get("model", "large-v3")
    fallback_model = w_cfg.get("fallback_model", "medium")
    device = w_cfg.get("device", "cuda")
    compute_type = w_cfg.get("compute_type", "float16")

    try:
        model = WhisperModel(primary_model, device=device, compute_type=compute_type)
        model_name = primary_model
    except Exception as e:
        print(f"[Warn] Không load được {primary_model} ({e}), chuyển sang {fallback_model}...", flush=True)
        model = WhisperModel(fallback_model, device=device, compute_type=compute_type)
        model_name = fallback_model

    ocr = RapidOCR()
    print(f"Đã nạp Whisper '{model_name}' ({device}/{compute_type}) + RapidOCR.", flush=True)

    tmp_jpg = trans_dir / "_tmp_ocr_frame.jpg"
    done_cnt = 0
    src_lang = cfg.get("source_lang", "zh")
    pause_split_sec = float(w_cfg.get("pause_split_sec", 1.05))
    min_sil_ms = int(w_cfg.get("min_silence_ms", 350))
    speech_pad_ms = int(w_cfg.get("speech_pad_ms", 120))
    beam_size = int(w_cfg.get("beam_size", 3))

    for idx, ep in enumerate(episodes, 1):
        ep_key = ep["ep_key"]
        json_out = trans_dir / f"{ep_key}_zh.json"
        srt_out = trans_dir / f"{ep_key}_zh.srt"

        if json_out.exists() and not args.force:
            print(f"[{idx:02d}/{len(episodes)}] Bỏ qua {ep_key} (đã có transcript).", flush=True)
            done_cnt += 1
            continue

        mp4_path = Path(ep["file_path"])
        if not mp4_path.exists():
            mp4_path = raw_dir / f"{ep_key}.mp4"
        if not mp4_path.exists():
            print(f"[{idx:02d}/{len(episodes)}] THIẾU FILE {mp4_path}", flush=True)
            continue

        dur_sec = float(ep["duration_sec"])
        audio_16k = decode_audio_16k(mp4_path, ffmpeg_bin=ffmpeg_bin)
        raw_segs, _ = model.transcribe(
            audio_16k,
            language=src_lang,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=min_sil_ms, speech_pad_ms=speech_pad_ms),
            condition_on_previous_text=False,
            word_timestamps=True,
            beam_size=beam_size,
        )

        segments = split_whisper_segments(
            raw_segs,
            audio_16k=audio_16k,
            dur_sec=dur_sec,
            pause_split_sec=pause_split_sec,
            roles_cfg=roles_cfg,
        )
        hardsub_band, ocr_meta = detect_hardsub_band(
            mp4_path,
            segments,
            int(ep["width"]),
            int(ep["height"]),
            ocr,
            tmp_jpg,
            ffmpeg_bin=ffmpeg_bin,
        )

        payload = {
            "ep_key": ep_key,
            "index": ep["index"],
            "aweme_id": ep["aweme_id"],
            "aweme_url": ep["aweme_url"],
            "publish_date": ep["publish_date"],
            "title_zh": ep["desc"],
            "width": ep["width"],
            "height": ep["height"],
            "duration_sec": ep["duration_sec"],
            "whisper_model": model_name,
            "hardsub_band": hardsub_band,
            "hardsub_x_band": ocr_meta.get("x_band"),
            "has_hardsub": ocr_meta.get("has_hardsub", True),
            "ocr_meta": ocr_meta,
            "segment_count": len(segments),
            "segments": segments,
        }
        json_out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        srt_lines = [
            f"{s['id']}\n{fmt_srt_ts(s['start'])} --> {fmt_srt_ts(s['end'])}\n{s['zh_text']}\n"
            for s in segments
        ]
        srt_out.write_text("\n".join(srt_lines), encoding="utf-8")
        done_cnt += 1
        print(
            f"[{idx:02d}/{len(episodes)}] OK {ep_key}: {len(segments)} câu | band={hardsub_band} ({ocr_meta['method']})",
            flush=True,
        )

    tmp_jpg.unlink(missing_ok=True)
    print(f"\n=== HOÀN TẤT BƯỚC 2: {done_cnt}/{len(episodes)} TẬP CÓ TRANSCRIPT ===", flush=True)


if __name__ == "__main__":
    main()
