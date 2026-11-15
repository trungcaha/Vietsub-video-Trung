# -*- coding: utf-8 -*-
r"""Bước 4: Tạo giọng đọc Microsoft TTS phân vai (edge-tts + WordBoundary),
đồng bộ từ Karaoke (\kf), FFmpeg/NumPy Smart Ducking O(N), làm mờ hardsub gốc bằng mặt nạ grayscale
và render MP4 tuần tự từng tập bằng GPU h264_nvenc (fallback libx264).

Chạy tuần tự từng tập (luôn chạy Pilot 1 tập + kiểm tra khung hình trước khi --all):
  python scripts/step4_dub_karaoke_render.py --ep <ep_key> --pilot-frames
  python scripts/step4_dub_karaoke_render.py --all
"""

import argparse
import asyncio
import difflib
import io
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import edge_tts
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from config_loader import (  # noqa: E402
    add_project_dir_arg,
    fmt_srt_ts,
    load_project_config,
    probe_media,
    sanitize_stem,
)

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "buffer"):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


def norm_token(tok: str) -> str:
    return re.sub(
        r"[^\wàáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]",
        "",
        tok.lower(),
    )


def fmt_ass_ts(sec: float) -> str:
    sec = max(0.0, float(sec))
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    cs = int(round((sec - int(sec)) * 100))
    if cs >= 100:
        cs = 99
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def ass_escape(txt: str) -> str:
    return txt.replace("\\", "\\\\").replace("{", r"\{").replace("}", r"\}")


def decode_audio_f32(path: Path, ffmpeg_bin: str, sr: int, channels: int = 1) -> np.ndarray:
    res = subprocess.run(
        [
            ffmpeg_bin,
            "-v",
            "error",
            "-i",
            str(path),
            "-ac",
            str(channels),
            "-ar",
            str(sr),
            "-f",
            "f32le",
            "-",
        ],
        capture_output=True,
        check=True,
    )
    arr = np.frombuffer(res.stdout, dtype=np.float32).copy()
    if channels > 1:
        arr = arr.reshape(-1, channels)
    return arr


def encode_wav_pcm16(path: Path, samples: np.ndarray, ffmpeg_bin: str, sr: int, channels: int = 1) -> None:
    """Ghi mảng float32 [-1, 1] ra WAV PCM16 bằng ffmpeg stdin."""
    clipped = np.clip(samples, -1.0, 1.0)
    pcm = (clipped * 32767.0).astype(np.int16)
    subprocess.run(
        [
            ffmpeg_bin,
            "-y",
            "-v",
            "error",
            "-f",
            "s16le",
            "-ar",
            str(sr),
            "-ac",
            str(channels),
            "-i",
            "-",
            str(path),
        ],
        input=pcm.tobytes(),
        check=True,
    )


def validate_roles_pitch(roles_cfg: Dict[str, Any]) -> None:
    """Kiểm tra bắt buộc pitch edge-tts dùng đơn vị Hz (không dùng %)."""
    for rkey, rinfo in roles_cfg.items():
        pitch = str(rinfo.get("pitch", "+0Hz")).strip()
        if "%" in pitch or not pitch.endswith("Hz"):
            raise ValueError(
                f"Role '{rkey}' có pitch='{pitch}' không hợp lệ cho edge-tts. "
                "Bắt buộc dùng đơn vị Hz (vd: '+0Hz', '-10Hz', '+18Hz')."
            )


async def warmup_tts(roles_cfg: Dict[str, Any]) -> None:
    """Khởi động kết nối edge-tts cho toàn bộ các giọng duy nhất (dùng break, không return sớm)."""
    voices = sorted({str(v.get("voice") or "vi-VN-HoaiMyNeural") for v in roles_cfg.values()})
    for voice in voices:
        for k in range(4):
            try:
                c = edge_tts.Communicate("xin chào", voice, boundary="WordBoundary")
                async for ch in c.stream():
                    if ch["type"] == "audio":
                        break
                break
            except Exception:
                await asyncio.sleep(0.5 + k * 0.5)


async def tts_segment_with_retry(
    text: str,
    role_cfg: Dict[str, Any],
    mp3_path: Path,
    words_json_path: Path,
    max_retries: int = 8,
) -> List[Dict[str, Any]]:
    """Synthesize Vietnamese TTS via edge-tts with SentenceBoundary fallback.

    Short or punctuated utterances with non-zero pitch occasionally return
    NoAudioReceived under WordBoundary; fall back to SentenceBoundary and
    neutral prosody before failing.
    """
    if mp3_path.exists() and mp3_path.stat().st_size > 200 and words_json_path.exists():
        return json.loads(words_json_path.read_text(encoding="utf-8"))

    clean_tts = re.sub(r'[""“”\'`\[\]\(\)#*]+', " ", text)
    clean_tts = re.sub(r"\s+", " ", clean_tts).strip()
    if not clean_tts:
        clean_tts = "."

    base_rate = role_cfg.get("rate", "+0%")
    base_pitch = role_cfg.get("pitch", "+0Hz")

    last_err = None
    for attempt in range(max_retries):
        if attempt < 3:
            boundary = "WordBoundary"
            rate = base_rate
            pitch = base_pitch
            tts_input = clean_tts
            if attempt == 2:
                stripped = re.sub(r"[,;:\-—….!?]+$", "", clean_tts).strip()
                if any(ch.isalnum() for ch in stripped):
                    tts_input = stripped
        elif attempt < 6:
            boundary = "SentenceBoundary"
            rate = base_rate
            pitch = base_pitch
            tts_input = clean_tts
        else:
            boundary = "SentenceBoundary"
            rate = "+0%"
            pitch = "+0Hz"
            alpha_only = re.sub(
                r"\s+", " ", re.sub(r"[^\w\s]", " ", clean_tts, flags=re.UNICODE)
            ).strip()
            tts_input = alpha_only if any(ch.isalnum() for ch in alpha_only) else "ừ"

        try:
            words: List[Dict[str, Any]] = []
            audio_chunks = bytearray()
            c = edge_tts.Communicate(
                tts_input,
                voice=role_cfg["voice"],
                rate=rate,
                pitch=pitch,
                boundary=boundary,
            )
            async for ch in c.stream():
                if ch["type"] == "audio":
                    audio_chunks.extend(ch["data"])
                elif ch["type"] == "WordBoundary":
                    words.append(
                        {
                            "text": str(ch.get("text", "")).strip(),
                            "start": float(ch.get("offset", 0)) / 10_000_000.0,
                            "dur": float(ch.get("duration", 0)) / 10_000_000.0,
                        }
                    )
            if len(audio_chunks) > 200:
                mp3_path.write_bytes(bytes(audio_chunks))
                words_json_path.write_text(
                    json.dumps(words, ensure_ascii=False), encoding="utf-8"
                )
                return words
        except Exception as e:
            last_err = e
        await asyncio.sleep(0.25 + min(attempt, 4) * 0.35)

    raise RuntimeError(
        f"edge-tts thất bại sau {max_retries} lần cho câu '{clean_tts[:40]}': {last_err}"
    )


def align_display_words(
    vi_text: str, wb_words: List[Dict[str, Any]], seg_dur: float
) -> List[Dict[str, Any]]:
    """Khớp từ hiển thị (giữ dấu câu đẹp) với mốc WordBoundary từ TTS qua SequenceMatcher."""
    display_tokens = [t for t in re.sub(r"\s+", " ", vi_text.strip()).split(" ") if t]
    if not display_tokens:
        return []

    if not wb_words:
        weights = [
            max(2.0, float(len(norm_token(tok)) or len(tok)))
            + (1.2 if tok[-1] in ",.!?;:" else 0.0)
            for tok in display_tokens
        ]
        total_w = sum(weights) or float(len(display_tokens))
        cur = 0.0
        out: List[Dict[str, Any]] = []
        for tok, w in zip(display_tokens, weights):
            d = max(0.03, seg_dur * (w / total_w))
            end = min(seg_dur, cur + d)
            out.append(
                {
                    "text": tok,
                    "start": min(cur, max(0.0, seg_dur - 0.02)),
                    "end": end,
                    "has_break": tok[-1] in ",.!?;:",
                }
            )
            cur = end
        out[-1]["end"] = seg_dur
        return out

    for w in wb_words:
        w["start"] = max(0.0, float(w["start"]))
        d = max(0.04, float(w["dur"]))
        w["end"] = min(seg_dur, w["start"] + d)

    d_norm = [norm_token(t) for t in display_tokens]
    w_norm = [norm_token(w["text"]) for w in wb_words]

    if len(display_tokens) == len(wb_words):
        return [
            {
                "text": tok,
                "start": w["start"],
                "end": max(w["start"] + 0.04, w["end"]),
                "has_break": tok[-1] in ",.!?;:",
            }
            for tok, w in zip(display_tokens, wb_words)
        ]

    starts: List[Optional[float]] = [None] * len(display_tokens)
    ends: List[Optional[float]] = [None] * len(display_tokens)
    sm = difflib.SequenceMatcher(a=d_norm, b=w_norm, autojunk=False)
    for blk in sm.get_matching_blocks():
        for j in range(blk.size):
            starts[blk.a + j] = wb_words[blk.b + j]["start"]
            ends[blk.a + j] = wb_words[blk.b + j]["end"]

    t0 = wb_words[0]["start"]
    t1 = max(wb_words[-1]["end"], min(seg_dur, t0 + 0.12))
    if starts[0] is None:
        starts[0] = t0
    if ends[-1] is None:
        ends[-1] = t1

    known = [i for i, v in enumerate(starts) if v is not None]
    for i in range(len(display_tokens)):
        if starts[i] is None:
            prev_i = max(k for k in known if k < i)
            nxt = [k for k in known if k > i]
            nxt_i = nxt[0] if nxt else len(display_tokens)
            nxt_t = starts[nxt_i] if nxt else t1
            starts[i] = starts[prev_i] + (nxt_t - starts[prev_i]) * (i - prev_i) / (nxt_i - prev_i)

    out = []
    for i, tok in enumerate(display_tokens):
        s_t = float(starts[i])
        if ends[i] is not None:
            e_t = float(ends[i])
        else:
            e_t = float(starts[i + 1]) if i + 1 < len(display_tokens) else t1
        e_t = max(s_t + 0.04, min(seg_dur, e_t))
        out.append({"text": tok, "start": s_t, "end": e_t, "has_break": tok[-1] in ",.!?;:"})
    return out


def trim_and_speed_fit(
    mp3_path: Path,
    wb_words: List[Dict[str, Any]],
    vi_text: str,
    avail: float,
    tmp_dir: Path,
    seg_id: int,
    ffmpeg_bin: str,
    sr: int,
    atempo_max: float,
) -> Tuple[np.ndarray, List[Dict[str, Any]]]:
    """Giải mã MP3, cắt lặng đầu/đuôi, chuẩn hóa RMS và kẹp tốc độ <= atempo_max nếu tràn slot."""
    y = decode_audio_f32(mp3_path, ffmpeg_bin=ffmpeg_bin, sr=sr, channels=1)
    if len(y) == 0:
        return np.zeros(int(0.1 * sr), dtype=np.float32), []

    hop = int(0.010 * sr)
    n_frames = len(y) // hop
    trim_head = 0.0
    if n_frames >= 3:
        frames = y[: n_frames * hop].reshape(n_frames, hop)
        rms = np.sqrt(np.mean(frames * frames, axis=1) + 1e-12)
        peak_rms = float(np.max(rms))
        thresh = max(1e-4, peak_rms * (10.0 ** (-40.0 / 20.0)))
        active = np.where(rms > thresh)[0]
        if len(active) > 0:
            s_idx = max(0, (int(active[0]) - 2) * hop)
            e_idx = min(len(y), (int(active[-1]) + 3) * hop)
            trim_head = s_idx / float(sr)
            y = y[s_idx:e_idx]

    raw_dur = len(y) / float(sr)
    shifted_wb = []
    for w in wb_words:
        ns = max(0.0, w["start"] - trim_head)
        if ns < raw_dur:
            shifted_wb.append({"text": w["text"], "start": ns, "dur": w["dur"]})

    words = align_display_words(vi_text, shifted_wb, raw_dur)

    speech_rms = float(np.sqrt(np.mean(y * y) + 1e-12))
    if speech_rms > 1e-4:
        gain = min(0.18 / speech_rms, 0.89 / max(1e-5, float(np.max(np.abs(y)))))
        y = y * gain

    if raw_dur > avail:
        speed = min(atempo_max, max(1.01, raw_dur / avail))
        raw_wav = tmp_dir / f"seg_{seg_id:03d}_pre.wav"
        fast_wav = tmp_dir / f"seg_{seg_id:03d}_fast.wav"
        encode_wav_pcm16(raw_wav, y, ffmpeg_bin=ffmpeg_bin, sr=sr, channels=1)

        s_rem = speed
        atempo_chain = []
        while s_rem > 2.0:
            atempo_chain.append("atempo=2.0")
            s_rem /= 2.0
        atempo_chain.append(f"atempo={max(0.5, s_rem):.4f}")
        subprocess.run(
            [
                ffmpeg_bin,
                "-y",
                "-v",
                "error",
                "-i",
                str(raw_wav),
                "-af",
                ",".join(atempo_chain),
                "-ar",
                str(sr),
                "-ac",
                "1",
                str(fast_wav),
            ],
            check=True,
        )
        y = decode_audio_f32(fast_wav, ffmpeg_bin=ffmpeg_bin, sr=sr, channels=1)
        raw_wav.unlink(missing_ok=True)
        fast_wav.unlink(missing_ok=True)

        new_dur = len(y) / float(sr)
        actual_speed = raw_dur / max(0.05, new_dur)
        for w in words:
            w["start"] = w["start"] / actual_speed
            w["end"] = min(new_dur, w["end"] / actual_speed)

    fade_n = min(int(0.010 * sr), len(y) // 4)
    if fade_n > 1:
        ramp = np.linspace(0.0, 1.0, fade_n, dtype=np.float32)
        y[:fade_n] *= ramp
        y[-fade_n:] *= ramp[::-1]

    return y, words


def chunk_karaoke_words(
    words: List[Dict[str, Any]], min_words: int = 4, max_words: int = 7
) -> List[List[Dict[str, Any]]]:
    """Chia câu dài thành các cụm 4–7 từ để phụ đề Karaoke to rõ, dễ đọc."""
    if len(words) <= max_words:
        return [words] if words else []

    chunks: List[List[Dict[str, Any]]] = []
    cur: List[Dict[str, Any]] = []
    for idx, w in enumerate(words):
        cur.append(w)
        rem = len(words) - 1 - idx
        at_punct = w.get("has_break") and len(cur) >= min_words and rem >= 2
        at_limit = (len(cur) >= max_words and rem >= 2) or (len(cur) >= max_words - 1 and rem == 3)
        if at_punct or at_limit:
            chunks.append(cur)
            cur = []
    if cur:
        if chunks and len(cur) == 1 and len(chunks[-1]) >= min_words:
            moved = chunks[-1].pop()
            cur.insert(0, moved)
        chunks.append(cur)
    return chunks


def build_ass_and_srt(
    chunk_entries: List[Dict[str, Any]],
    width: int,
    height: int,
    hardsub_band: List[int],
    video_dur: float,
    ass_path: Path,
    srt_path: Path,
    cfg: Dict[str, Any],
) -> None:
    y_top, y_bot = int(hardsub_band[0]), int(hardsub_band[1])
    band_h = max(40, y_bot - y_top)
    fontsize = round(height * 0.036) if height > width else round(height * 0.052)
    fontsize = max(28, fontsize)
    margin_v = max(14, int(height - y_bot + max(0.0, (band_h - fontsize) * 0.45)))
    margin_lr = max(24, int(width * 0.06))
    outline = round(max(3.5, fontsize * 0.068), 1)

    k_cfg = cfg["karaoke"]
    font_name = k_cfg.get("font_name", "Arial")
    sec_color = k_cfg.get("secondary_bgr", "&H00FFFFFF")
    out_color = k_cfg.get("outline_bgr", "&H00000000")
    back_color = k_cfg.get("back_bgr", "&H96000000")

    roles_cfg = cfg["roles"]
    default_role = cfg.get("default_role") or next(iter(roles_cfg))

    styles = []
    seen_styles = set()
    for role_cfg in roles_cfg.values():
        st_name = role_cfg.get("style") or "Default"
        if st_name in seen_styles:
            continue
        seen_styles.add(st_name)
        prim_color = role_cfg.get("color_bgr", "&H0078F0FF")
        styles.append(
            f"Style: {st_name},{font_name},{fontsize},{prim_color},{sec_color},{out_color},{back_color},"
            f"-1,0,0,0,100,100,0.5,0,1,{outline},2.0,2,{margin_lr},{margin_lr},{margin_v},1"
        )

    title_str = cfg.get("channel_name") or cfg.get("project_slug") or "Vietnamese Karaoke"
    ass_lines = [
        "[Script Info]",
        f"Title: {title_str} Vietnamese Karaoke",
        "ScriptType: v4.00+",
        f"PlayResX: {width}",
        f"PlayResY: {height}",
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        *styles,
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    srt_blocks = []
    for idx, ce in enumerate(chunk_entries, 1):
        words = ce["words"]
        if not words:
            continue
        t_start = max(0.0, float(words[0]["g_start"]))
        raw_end = float(words[-1]["g_end"]) + 0.08
        if idx < len(chunk_entries):
            next_start = float(chunk_entries[idx]["words"][0]["g_start"])
            t_end = min(raw_end, max(t_start + 0.15, next_start - 0.02))
        else:
            t_end = min(raw_end, video_dur - 0.02)
        t_end = max(t_start + 0.15, t_end)

        plain_text = " ".join(w["text"] for w in words)
        srt_blocks.append(
            f"{idx}\n{fmt_srt_ts(t_start)} --> {fmt_srt_ts(t_end)}\n{plain_text}\n"
        )

        cur_cs = int(round(t_start * 100.0))
        k_parts = []
        for wi, w in enumerate(words):
            w_s_cs = int(round(w["g_start"] * 100.0))
            if w_s_cs > cur_cs:
                gap_cs = w_s_cs - cur_cs
                k_parts.append(f"{{\\k{gap_cs}}}")
                cur_cs += gap_cs

            if wi + 1 < len(words):
                target_e_cs = int(round(w["g_end"] * 100.0))
                next_s_cs = int(round(words[wi + 1]["g_start"] * 100.0))
                if 0 < next_s_cs - target_e_cs <= 6:
                    target_e_cs = next_s_cs
            else:
                target_e_cs = max(cur_cs + 1, int(round(w["g_end"] * 100.0)))

            dur_cs = max(1, target_e_cs - cur_cs)
            cur_cs += dur_cs
            space = " " if wi + 1 < len(words) else ""
            k_parts.append(f"{{\\kf{dur_cs}}}{ass_escape(w['text'])}{space}")

        r_cfg = roles_cfg.get(ce["role"], roles_cfg[default_role])
        style_name = r_cfg.get("style", "Default")
        ass_lines.append(
            f"Dialogue: 0,{fmt_ass_ts(t_start)},{fmt_ass_ts(t_end)},{style_name},,0,0,0,,{''.join(k_parts)}"
        )

    ass_path.write_text("\n".join(ass_lines), encoding="utf-8-sig")
    srt_path.write_text("\n".join(srt_blocks), encoding="utf-8")


def boxcar_smooth(arr: np.ndarray, win: int) -> np.ndarray:
    """Làm mượt 1D O(N) bằng cửa sổ trung bình trượt qua tổng tích lũy."""
    if win <= 1 or len(arr) < win:
        return arr
    pad_l = win // 2
    pad_r = win - 1 - pad_l
    padded = np.pad(arr, (pad_l, pad_r), mode="edge")
    cs = np.empty(len(padded) + 1, dtype=np.float64)
    cs[0] = 0.0
    np.cumsum(padded, dtype=np.float64, out=cs[1:])
    return ((cs[win:] - cs[:-win]) / float(win)).astype(np.float32)


def create_pill_blur_mask(
    width: int,
    height: int,
    hardsub_band: List[int],
    dst_png: Path,
    x_band: Optional[List[int]] = None,
    fill_val: int = 248,
    feather_radius: int = 12,
) -> None:
    """Tạo mặt nạ grayscale ('L') pill bo tròn viền mờ cho ffmpeg alphamerge."""
    y_top, y_bot = int(hardsub_band[0]), int(hardsub_band[1])
    if x_band and len(x_band) == 2:
        x0, x1 = int(x_band[0]), int(x_band[1])
    else:
        x0 = int(round(width * 0.14))
        x1 = int(round(width * 0.86))
    radius = max(16, int((y_bot - y_top) * 0.30))

    alpha = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(alpha)
    draw.rounded_rectangle([x0, y_top, x1, y_bot], radius=radius, fill=int(fill_val))
    alpha = alpha.filter(ImageFilter.GaussianBlur(radius=int(feather_radius)))
    alpha.save(str(dst_png))


def extract_pilot_frames(
    out_mp4: Path,
    chunk_entries: List[Dict[str, Any]],
    pilot_dir: Path,
    ep_key: str,
    ffmpeg_bin: str,
) -> List[Path]:
    """Trích 2 frame giữa câu thoại đang quét màu \\kf để kiểm tra trực quan bằng read_file."""
    if not chunk_entries:
        return []
    pilot_dir.mkdir(parents=True, exist_ok=True)
    # Ưu tiên chọn 2 chunk thuộc 2 vai khác nhau ở phần đầu/giữa video
    picked: List[Dict[str, Any]] = []
    seen_roles = set()
    for ce in chunk_entries:
        if len(ce.get("words") or []) >= 3 and ce["role"] not in seen_roles:
            picked.append(ce)
            seen_roles.add(ce["role"])
            if len(picked) == 2:
                break
    if len(picked) < 2:
        for ce in chunk_entries:
            if ce not in picked and len(ce.get("words") or []) >= 2:
                picked.append(ce)
                if len(picked) == 2:
                    break

    saved: List[Path] = []
    for idx, ce in enumerate(picked, 1):
        ws = ce["words"]
        t_mid = 0.5 * (float(ws[0]["g_start"]) + float(ws[-1]["g_end"]))
        dst_jpg = pilot_dir / f"pilot_{ep_key}_{idx}.jpg"
        subprocess.run(
            [
                ffmpeg_bin,
                "-v",
                "error",
                "-y",
                "-ss",
                f"{t_mid:.2f}",
                "-i",
                str(out_mp4),
                "-frames:v",
                "1",
                str(dst_jpg),
            ],
            check=False,
        )
        if dst_jpg.exists():
            saved.append(dst_jpg)
    return saved


async def process_one_episode(
    ep_key: str, cfg: Dict[str, Any], force: bool = False, pilot_frames: bool = False
) -> Optional[Dict[str, Any]]:
    raw_dir = Path(cfg["dirs"]["raw"])
    trans_dir = Path(cfg["dirs"]["transcripts"])
    vi_dir = Path(cfg["dirs"]["translations"])
    out_dir = Path(cfg["dirs"]["output"])
    tmp_root = Path(cfg["dirs"]["tmp"])
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp_root.mkdir(parents=True, exist_ok=True)

    ffmpeg_bin = cfg["tools"]["ffmpeg"]
    ffprobe_bin = cfg["tools"]["ffprobe"]
    r_cfg = cfg["render"]
    d_cfg = cfg["ducking"]
    k_cfg = cfg["karaoke"]
    roles_cfg = cfg["roles"]
    default_role = cfg.get("default_role") or next(iter(roles_cfg))
    sr = int(r_cfg.get("sample_rate", 48000))

    vi_json_path = vi_dir / f"{ep_key}_vi.json"
    zh_json_path = trans_dir / f"{ep_key}_zh.json"
    if not vi_json_path.exists():
        print(f"[SKIP] Chưa có bản dịch {vi_json_path}", flush=True)
        return None

    vi_data = json.loads(vi_json_path.read_text(encoding="utf-8"))
    zh_data = json.loads(zh_json_path.read_text(encoding="utf-8")) if zh_json_path.exists() else {}

    stem = sanitize_stem(vi_data.get("vi_file_stem") or ep_key, ep_key)
    out_mp4 = out_dir / f"{stem}.mp4"
    out_srt = out_dir / f"{stem}.vi.srt"
    out_ass = out_dir / f"{stem}.vi.ass"

    if out_mp4.exists() and out_mp4.stat().st_size > 100_000 and not force:
        print(f"[SKIP] Đã tồn tại thành phẩm {out_mp4.name}", flush=True)
        return {"ep_key": ep_key, "out_mp4": str(out_mp4), "status": "cached"}

    raw_mp4 = raw_dir / f"{ep_key}.mp4"
    if not raw_mp4.exists():
        raise FileNotFoundError(f"Thiếu file video gốc: {raw_mp4}")

    # Ưu tiên metadata gốc từ _zh.json trước _vi.json
    width = int(zh_data.get("width") or vi_data.get("width") or 2560)
    height = int(zh_data.get("height") or vi_data.get("height") or 1440)
    video_dur = float(zh_data.get("duration_sec") or vi_data.get("duration_sec") or 0.0)
    if video_dur <= 0.1:
        info = probe_media(raw_mp4, ffprobe_bin=ffprobe_bin)
        video_dur = float((info.get("format") or {}).get("duration", 0) or 0)
    default_band = (
        [int(height * 0.78), int(height * 0.88)]
        if height > width
        else [int(height * 0.895), int(height * 0.978)]
    )
    hardsub_band = zh_data.get("hardsub_band") or vi_data.get("hardsub_band") or default_band
    x_band = zh_data.get("hardsub_x_band") or [int(width * 0.14), int(width * 0.86)]
    ocr_meta = zh_data.get("ocr_meta") or {}
    use_blur_mask = bool(zh_data.get("has_hardsub", True)) and int(ocr_meta.get("boxes_found", 1)) > 0

    tmp_ep = tmp_root / ep_key
    tmp_ep.mkdir(parents=True, exist_ok=True)

    segments = vi_data.get("segments") or []
    zh_segments = zh_data.get("segments") or []
    zh_by_id = {int(zs["id"]): zs for zs in zh_segments if "id" in zs}
    print(f"\n>>> Xử lý {ep_key} ({len(segments)} câu, {video_dur:.1f}s) -> {out_mp4.name}", flush=True)

    orig_audio = decode_audio_f32(raw_mp4, ffmpeg_bin=ffmpeg_bin, sr=sr, channels=2)
    n_samples = max(len(orig_audio), int(round(video_dur * sr)))
    if len(orig_audio) < n_samples:
        orig_audio = np.pad(orig_audio, ((0, n_samples - len(orig_audio)), (0, 0)))
    elif len(orig_audio) > n_samples:
        orig_audio = orig_audio[:n_samples]

    voice_track = np.zeros(n_samples, dtype=np.float32)
    duck_events: List[Dict[str, float]] = []
    chunk_entries: List[Dict[str, Any]] = []
    prev_actual_end = -0.10

    atempo_max = float(k_cfg.get("atempo_max", 1.48))
    chunk_min_w = int(k_cfg.get("chunk_min_words", 4))
    chunk_max_w = int(k_cfg.get("chunk_max_words", 7))

    for i, seg in enumerate(segments):
        sid = int(seg["id"])
        zseg = zh_by_id.get(sid) or (zh_segments[i] if i < len(zh_segments) else seg)
        zh_start = float(zseg["start"])
        zh_end = float(zseg["end"])

        role = seg.get("role", default_role)
        if role not in roles_cfg:
            role = default_role
        vi_text = (seg.get("vi_text") or "").strip()
        if not vi_text:
            continue

        mp3_p = tmp_ep / f"seg_{sid:03d}.mp3"
        wb_p = tmp_ep / f"seg_{sid:03d}.words.json"
        wb_words = await tts_segment_with_retry(vi_text, roles_cfg[role], mp3_p, wb_p)
        await asyncio.sleep(0.18)

        slot_start = max(zh_start, prev_actual_end + 0.03)
        if i + 1 < len(segments):
            nxt_seg = segments[i + 1]
            nxt_sid = int(nxt_seg["id"])
            nxt_zseg = zh_by_id.get(nxt_sid) or (zh_segments[i + 1] if i + 1 < len(zh_segments) else nxt_seg)
            next_start = float(nxt_zseg["start"])
        else:
            next_start = video_dur
        hard_max_end = min(next_start - 0.04, zh_end + 0.55, video_dur - 0.04)
        avail = max(0.30, hard_max_end - slot_start)

        y_seg, words = trim_and_speed_fit(
            mp3_p,
            wb_words,
            vi_text,
            avail,
            tmp_ep,
            sid,
            ffmpeg_bin=ffmpeg_bin,
            sr=sr,
            atempo_max=atempo_max,
        )
        if len(y_seg) == 0:
            continue

        start_idx = int(round(slot_start * sr))
        if start_idx >= n_samples:
            continue
        end_idx = min(n_samples, start_idx + len(y_seg))
        copy_len = end_idx - start_idx
        voice_track[start_idx:end_idx] += y_seg[:copy_len]
        actual_end = end_idx / float(sr)
        prev_actual_end = actual_end

        duck_events.append(
            {
                "zh_start": zh_start,
                "zh_end": zh_end,
                "vi_start": slot_start,
                "vi_end": actual_end,
            }
        )

        for w in words:
            w["g_start"] = slot_start + w["start"]
            w["g_end"] = min(actual_end, slot_start + w["end"])

        for ch_words in chunk_karaoke_words(words, min_words=chunk_min_w, max_words=chunk_max_w):
            chunk_entries.append({"role": role, "words": ch_words})

    # Smart Ducking O(N)
    bg_normal = float(d_cfg.get("bg_normal", 0.85))
    bg_duck = float(d_cfg.get("bg_duck", 0.08))
    pad_before = float(d_cfg.get("pad_before", 0.10))
    pad_after = float(d_cfg.get("pad_after", 0.12))
    ramp_ms = float(d_cfg.get("ramp_ms", 90))

    gain = np.full(n_samples, bg_normal, dtype=np.float32)
    for ev in duck_events:
        d0 = max(0, int((min(ev["zh_start"], ev["vi_start"]) - pad_before) * sr))
        d1 = min(n_samples, int((max(ev["zh_end"], ev["vi_end"]) + pad_after) * sr))
        gain[d0:d1] = bg_duck

    win = max(1, int((ramp_ms / 2000.0) * sr))
    gain = boxcar_smooth(boxcar_smooth(gain, win), win)

    mixed = orig_audio * gain[:, None] + voice_track[:, None] * 1.05
    peak = float(np.max(np.abs(mixed)))
    if peak > 0.90:
        mixed = np.tanh(mixed * (0.90 / peak) * 1.15) * 0.89

    mixed_wav = tmp_ep / "mixed.wav"
    encode_wav_pcm16(mixed_wav, mixed, ffmpeg_bin=ffmpeg_bin, sr=sr, channels=2)

    local_ass = tmp_ep / "vi_karaoke.ass"
    local_srt = tmp_ep / "vi_subs.srt"
    build_ass_and_srt(
        chunk_entries, width, height, hardsub_band, video_dur, local_ass, local_srt, cfg
    )

    sigma = float(k_cfg.get("gblur_sigma", 24))
    bright = float(k_cfg.get("mask_brightness", -0.08))
    mask_fill = int(k_cfg.get("mask_fill", 248))
    mask_feather = int(k_cfg.get("mask_feather", 12))

    if use_blur_mask:
        mask_png = tmp_ep / "mask.png"
        create_pill_blur_mask(
            width,
            height,
            hardsub_band,
            mask_png,
            x_band=x_band,
            fill_val=mask_fill,
            feather_radius=mask_feather,
        )
        fc = (
            "[0:v]split[base][bg];"
            f"[bg]gblur=sigma={sigma:g},eq=brightness={bright:g},format=yuva420p[blurred];"
            "[1:v]format=gray[msk];"
            "[blurred][msk]alphamerge[cover];"
            "[base][cover]overlay=0:0:shortest=1,ass=vi_karaoke.ass[v]"
        )
        in_args = [
            "-i", str(raw_mp4),
            "-loop", "1", "-t", f"{video_dur + 0.5:.3f}", "-i", "mask.png",
            "-i", "mixed.wav",
        ]
        audio_map = "2:a"
    else:
        fc = "[0:v]ass=vi_karaoke.ass[v]"
        in_args = ["-i", str(raw_mp4), "-i", "mixed.wav"]
        audio_map = "1:a"

    v_codec = r_cfg.get("video_codec", "h264_nvenc")
    nvenc_preset = r_cfg.get("nvenc_preset", "p4")
    nvenc_cq = str(r_cfg.get("nvenc_cq", 21))
    a_bitrate = r_cfg.get("audio_bitrate", "192k")

    nvenc_cmd = [
        ffmpeg_bin,
        "-y",
        "-v",
        "error",
        *in_args,
        "-filter_complex",
        fc,
        "-map",
        "[v]",
        "-map",
        audio_map,
        "-c:v",
        v_codec,
        "-preset",
        nvenc_preset,
        "-cq",
        nvenc_cq,
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        a_bitrate,
        "-ar",
        str(sr),
        "-shortest",
        "-movflags",
        "+faststart",
        str(out_mp4),
    ]
    res = subprocess.run(nvenc_cmd, cwd=str(tmp_ep), capture_output=True, text=True)
    if res.returncode != 0:
        print(f"  [Warn] {v_codec} lỗi ({res.stderr[:140]}), fallback CPU...", flush=True)
        cpu_cmd = [
            ffmpeg_bin,
            "-y",
            "-v",
            "error",
            *in_args,
            "-filter_complex",
            fc,
            "-map",
            "[v]",
            "-map",
            audio_map,
            "-c:v",
            r_cfg.get("cpu_fallback_codec", "libx264"),
            "-preset",
            r_cfg.get("cpu_preset", "veryfast"),
            "-crf",
            str(r_cfg.get("cpu_crf", 20)),
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            a_bitrate,
            "-ar",
            str(sr),
            "-shortest",
            "-movflags",
            "+faststart",
            str(out_mp4),
        ]
        subprocess.run(cpu_cmd, cwd=str(tmp_ep), check=True)

    out_info = probe_media(out_mp4, ffprobe_bin=ffprobe_bin)
    codecs = {s.get("codec_type"): s.get("codec_name") for s in out_info.get("streams") or []}
    out_dur = float((out_info.get("format") or {}).get("duration", 0) or 0)
    if "video" not in codecs or "audio" not in codecs or out_dur <= 0.1:
        raise RuntimeError(f"Output {out_mp4} hỏng metadata: codecs={codecs}, dur={out_dur}")

    shutil.copy2(local_srt, out_srt)
    shutil.copy2(local_ass, out_ass)

    saved_pilots: List[str] = []
    if pilot_frames:
        pilot_dir = Path(cfg["project_dir"]) / "_pilot"
        saved_pilots = [
            str(p)
            for p in extract_pilot_frames(out_mp4, chunk_entries, pilot_dir, ep_key, ffmpeg_bin=ffmpeg_bin)
        ]

    # Xóa _tmp/<ep_key> ngay sau khi xong tập
    shutil.rmtree(tmp_ep, ignore_errors=True)

    print(
        f"  [OK] {out_mp4.name} | {out_dur:.1f}s (gốc {video_dur:.1f}s) | {out_mp4.stat().st_size // 1024} KB",
        flush=True,
    )
    if saved_pilots:
        print(f"  [PILOT] Ảnh kiểm tra Karaoke: {saved_pilots}", flush=True)
    return {
        "ep_key": ep_key,
        "title_vi": vi_data.get("vi_title_display"),
        "out_mp4": str(out_mp4),
        "out_srt": str(out_srt),
        "out_ass": str(out_ass),
        "pilot_frames": saved_pilots,
        "duration_out": round(out_dur, 2),
        "duration_raw": round(video_dur, 2),
        "status": "rendered",
    }


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Bước 4: Lồng tiếng edge-tts + Karaoke \\kf + Smart Ducking + Render MP4"
    )
    add_project_dir_arg(parser)
    parser.add_argument("--ep", type=str, default="", help="Chạy đúng 1 tập theo ep_key (Pilot gate)")
    parser.add_argument("--all", action="store_true", help="Chạy tuần tự toàn bộ các tập lẻ")
    parser.add_argument("--force", action="store_true", help="Render lại cả tập đã có file output")
    parser.add_argument(
        "--pilot-frames",
        action="store_true",
        help="Trích 2 ảnh JPEG giữa câu thoại \\kf vào _pilot/ để kiểm tra trực quan bằng read_file",
    )
    args = parser.parse_args()

    if not args.ep and not args.all:
        parser.error("Cần truyền --ep <ep_key> hoặc --all")

    cfg = load_project_config(args.project_dir or None)
    roles_cfg = cfg.get("roles") or {}
    validate_roles_pitch(roles_cfg)

    manifest_path = Path(cfg["dirs"]["raw"]) / "posts_manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Chưa có {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    single_eps = [e["ep_key"] for e in manifest.get("episodes", []) if not e.get("is_compilation")]

    targets = [args.ep] if args.ep else single_eps
    print("=== WARMUP EDGE-TTS MICROSOFT VOICES ===", flush=True)
    await warmup_tts(roles_cfg)

    results = []
    for ep_key in targets:
        r = await process_one_episode(
            ep_key, cfg, force=args.force, pilot_frames=args.pilot_frames
        )
        if r:
            results.append(r)

    print(f"\n=== HOÀN TẤT BƯỚC 4: {len(results)}/{len(targets)} TẬP ===", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
