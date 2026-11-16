# -*- coding: utf-8 -*-
"""Tạo voiceover 48kHz + word timings (work/phrases.json & web/phrases_data.js)
bằng G-OmniVoice + ClearerVoice, giữ nguyên cao độ khi thay đổi voice_speed.

Chạy từ bất kỳ Python nào:
  python tools/g-omnivoice/pipelines/tts_phrases.py <thu_muc_du_an>
"""
from __future__ import annotations

import gc
import json
import re
import subprocess
import sys
from pathlib import Path

OMNI_TOOL_DIR = Path(__file__).resolve().parent.parent
if str(OMNI_TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(OMNI_TOOL_DIR))

from omni_env import (  # noqa: E402
    VOICES_DIR,
    ensure_omni_model,
    find_ffmpeg,
    get_device_and_dtype,
    get_venv_python,
    run_enhance,
)

try:
    import omnivoice  # noqa: F401
    import torch  # noqa: F401
except ImportError:
    venv_py = get_venv_python(OMNI_TOOL_DIR)
    if venv_py.is_file() and venv_py.resolve() != Path(sys.executable).resolve():
        res = subprocess.run([str(venv_py), str(Path(__file__).resolve()), *sys.argv[1:]])
        sys.exit(res.returncode)
    raise

import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402
from omnivoice import OmniVoice  # noqa: E402
from vn_textnorm import normalize  # noqa: E402

SR = 48000
GEN_SR = 24000


def trim_silence(wav: np.ndarray, sr: int, thresh_db: float = -40.0) -> np.ndarray:
    if len(wav) == 0:
        return wav
    peak = max(1e-6, float(np.abs(wav).max()))
    thr = peak * (10.0 ** (thresh_db / 20.0))
    win = max(1, int(0.015 * sr))
    env = np.convolve(np.abs(wav), np.ones(win) / win, mode="same")
    idx = np.where(env > thr)[0]
    if len(idx) == 0:
        return wav
    pad_l = int(0.03 * sr)
    pad_r = int(0.05 * sr)
    a = max(0, int(idx[0]) - pad_l)
    b = min(len(wav), int(idx[-1]) + pad_r)
    return wav[a:b]


def split_clauses(text: str):
    parts = [p.strip() for p in re.split(r"(?<=[,;:.!?])\s+", text.strip()) if p.strip()]
    return parts if parts else [text.strip()]


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    root = Path(sys.argv[1]).expanduser().resolve() if len(sys.argv) > 1 else Path.cwd().resolve()
    work = root / "work"
    cfg = json.loads((work / "script.json").read_text(encoding="utf-8"))
    fps = int(cfg.get("fps", 30))
    voice = str(cfg.get("omni_voice", "quang-nguyen"))
    do_enhance = bool(cfg.get("omni_enhance", True))
    speed = float(cfg.get("voice_speed", 1.0))

    raw_dir = work / "_tts_raw"
    enh_dir = work / "_tts_enh"
    fin_dir = work / "_tts_fin"
    for d in (raw_dir, enh_dir, fin_dir):
        d.mkdir(parents=True, exist_ok=True)

    vdir = VOICES_DIR / voice
    if not vdir.is_dir():
        raise FileNotFoundError(f"Không tìm thấy giọng '{voice}' trong {VOICES_DIR}")
    ref_wav = str(vdir / "ref.wav")
    ref_txt = (vdir / "ref.txt").read_text(encoding="utf-8").strip()

    sentences = cfg["sentences"]
    need_gen = [s for s in sentences if not (raw_dir / f"{s['id']}.wav").exists() or (raw_dir / f"{s['id']}.wav").stat().st_size < 1000]

    if need_gen:
        device, dtype = get_device_and_dtype()
        print(f"[TTS] Loading G-OmniVoice ({voice}) on {device}...", flush=True)
        model = OmniVoice.from_pretrained(str(ensure_omni_model("vi")), device_map=device, dtype=dtype)
        prompt = model.create_voice_clone_prompt(ref_audio=ref_wav, ref_text=ref_txt)
        for s in need_gen:
            clauses = split_clauses(s["text"])
            chunks = []
            for c in clauses:
                norm_c = normalize(c)
                wav_c = model.generate(text=norm_c, voice_clone_prompt=prompt, language="vi")[0].astype(np.float32)
                wav_c = trim_silence(wav_c, GEN_SR, -38.0)
                chunks.append(wav_c)
                chunks.append(np.zeros(int(0.10 * GEN_SR), dtype=np.float32))
            merged = np.concatenate(chunks[:-1]) if len(chunks) > 1 else chunks[0]
            merged *= min(1.0, 0.89 / max(1e-6, float(np.abs(merged).max())))
            sf.write(raw_dir / f"{s['id']}.wav", merged, GEN_SR, subtype="FLOAT")
            print(f"  [GEN] {s['id']} ({len(merged) / GEN_SR:.2f}s)", flush=True)
        del model, prompt
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    src_dir = raw_dir
    if do_enhance:
        missing_enh = [s for s in sentences if not (enh_dir / f"{s['id']}.wav").exists()]
        if missing_enh:
            print(f"[ENHANCE] Running ClearerVoice 48kHz on {len(sentences)} segments...", flush=True)
            run_enhance(raw_dir, enh_dir)
        src_dir = enh_dir

    ffmpeg_bin = find_ffmpeg()
    full_audio = [np.zeros(int(0.12 * SR), dtype=np.float32)]
    cursor = len(full_audio[0]) / SR
    phrases_out = []

    rb_check = subprocess.run([ffmpeg_bin, "-filters"], capture_output=True, text=True, check=False)
    has_rubberband = "rubberband" in (rb_check.stdout or "")

    for idx, s in enumerate(sentences):
        in_wav = src_dir / f"{s['id']}.wav"
        out_wav = fin_dir / f"{s['id']}.wav"
        af_parts = [f"aresample={SR}"]
        if abs(speed - 1.0) > 1e-3:
            af_parts.append(f"rubberband=tempo={speed:.4f}" if has_rubberband else f"atempo={speed:.4f}")
        af_parts.append("loudnorm=I=-16:TP=-1.5:LRA=9")
        subprocess.run(
            [
                ffmpeg_bin,
                "-v",
                "error",
                "-y",
                "-i",
                str(in_wav),
                "-af",
                ",".join(af_parts),
                "-ac",
                "1",
                "-ar",
                str(SR),
                "-sample_fmt",
                "s16",
                str(out_wav),
            ],
            check=True,
        )
        seg, _ = sf.read(out_wav, dtype="float32")
        seg = trim_silence(seg, SR, -40.0)
        dur = len(seg) / SR
        start_t = cursor
        end_t = start_t + dur

        words_raw = s["text"].split()
        weights = [max(1.0, len(re.sub(r"[^\wÀ-ỹ]", "", w)) * 0.35 + (1.6 if w[-1:] in ",;:.!?" else 0.8)) for w in words_raw]
        w_sum = sum(weights) or 1.0
        w_cursor = start_t
        words_timed = []
        for w, wt in zip(words_raw, weights):
            wd = dur * (wt / w_sum)
            words_timed.append(
                {
                    "word": w,
                    "start": round(w_cursor, 3),
                    "end": round(w_cursor + wd, 3),
                    "frame_start": round(w_cursor * fps),
                    "frame_end": round((w_cursor + wd) * fps),
                }
            )
            w_cursor += wd

        phrases_out.append(
            {
                "index": idx,
                "id": s["id"],
                "text": s["text"],
                "start": round(start_t, 3),
                "end": round(end_t, 3),
                "duration": round(dur, 3),
                "frame_start": round(start_t * fps),
                "frame_end": round(end_t * fps),
                "pause_after": s.get("pause_after", 0.24),
                "words": words_timed,
            }
        )

        full_audio.append(seg)
        pause = float(s.get("pause_after", 0.24))
        full_audio.append(np.zeros(int(pause * SR), dtype=np.float32))
        cursor = end_t + pause

    master = np.concatenate(full_audio)
    total_dur = len(master) / SR
    total_frames = round(total_dur * fps)
    vo_path = work / "voiceover.wav"
    sf.write(vo_path, master, SR, subtype="PCM_16")

    sd = subprocess.run(
        [ffmpeg_bin, "-i", str(vo_path), "-af", "silencedetect=noise=-35dB:d=0.12", "-f", "null", "-"],
        capture_output=True,
        text=True,
        check=False,
    )
    silences = []
    s_start = None
    for line in (sd.stderr or "").splitlines():
        m1 = re.search(r"silence_start:\s*([0-9.]+)", line)
        m2 = re.search(r"silence_end:\s*([0-9.]+)", line)
        if m1:
            s_start = float(m1.group(1))
        elif m2 and s_start is not None:
            silences.append([round(s_start, 3), round(float(m2.group(1)), 3)])
            s_start = None

    meta = {
        "title": cfg["title"],
        "fps": fps,
        "sample_rate": SR,
        "voice": voice,
        "voice_speed": speed,
        "rubberband_used": has_rubberband,
        "duration": round(total_dur, 3),
        "frames": total_frames,
        "detected_silences": silences,
        "phrases": phrases_out,
    }
    (work / "phrases.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    (root / "web").mkdir(parents=True, exist_ok=True)
    (root / "web" / "phrases_data.js").write_text(
        "export const PHRASES_DATA = " + json.dumps(meta, ensure_ascii=False, indent=2) + ";\n",
        encoding="utf-8",
    )
    print(f"[DONE] voiceover.wav = {total_dur:.2f}s ({total_frames} frames @ {fps}fps), rubberband={has_rubberband}")


if __name__ == "__main__":
    main()
