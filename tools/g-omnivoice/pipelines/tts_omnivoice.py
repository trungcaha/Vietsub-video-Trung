# -*- coding: utf-8 -*-
"""Lồng tiếng toàn bộ <project>/script.json bằng G-OmniVoice + ClearerVoice 48kHz,
xuất audio/NNN.wav, voice.wav (48kHz), timings.json và timings.js.

Chạy từ bất kỳ Python nào (tự re-exec sang tools/g-omnivoice/.venv nếu thiếu omnivoice):
  python tools/g-omnivoice/pipelines/tts_omnivoice.py <thu_muc_du_an>
"""
from __future__ import annotations

import array
import gc
import hashlib
import json
import math
import re
import shutil
import subprocess
import sys
import wave
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

# Tự chuyển sang .venv của G-OmniVoice nếu interpreter hiện tại chưa có omnivoice/torch
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
FPS = 30
LEAD = 0.80
CUE = re.compile(r"\[[^\]]*\]\s*")


def cache_key(voice: str, do_enhance: bool, text: str) -> str:
    return hashlib.md5(
        json.dumps([voice, do_enhance, normalize(text)], ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:16]


def generate(model: OmniVoice, prompt, text: str, raw: Path) -> None:
    parts = []
    for s in [s for s in re.split(r"(?<=[.!?…])\s+", normalize(text.strip())) if s]:
        parts += [
            model.generate(text=s, voice_clone_prompt=prompt, language="vi")[0].astype(np.float32),
            np.zeros(int(0.28 * GEN_SR), dtype=np.float32),
        ]
    if not parts:
        parts = [np.zeros(int(0.2 * GEN_SR), dtype=np.float32), np.zeros(1, dtype=np.float32)]
    audio = np.concatenate(parts[:-1]) if len(parts) > 1 else parts[0]
    audio *= min(1.0, 0.89 / max(1e-6, float(np.abs(audio).max())))
    sf.write(raw, audio, GEN_SR, subtype="FLOAT")


def finish(ffmpeg_bin: str, src: Path, cache: Path) -> None:
    # Chuyển về 48kHz bằng aresample (không dùng asetrate để tránh méo cao độ)
    subprocess.run(
        [
            ffmpeg_bin,
            "-v",
            "error",
            "-y",
            "-i",
            str(src),
            "-af",
            f"aresample={SR},loudnorm=I=-15:TP=-1.5:LRA=9",
            "-ac",
            "1",
            "-ar",
            str(SR),
            "-sample_fmt",
            "s16",
            str(cache),
        ],
        check=True,
    )


def estimate_words(text: str, dur: float):
    toks = re.findall(r"[\wÀ-ỹ]+[^\s]*", text)
    if not toks:
        return []
    weights = [len(re.sub(r"\W", "", t)) + 2 + (5 if re.search(r"[.,?!…]", t) else 0) for t in toks]
    tot = sum(weights)
    t = 0.05
    out = []
    for tok, w in zip(toks, weights):
        span = max(0.02, (dur - 0.1)) * w / tot
        out.append(dict(w=re.sub(r"[^\wÀ-ỹ]", "", tok), s=t, e=t + span * (0.7 if re.search(r"[.,?!…]", tok) else 0.95)))
        t += span
    return out


def _norm_row(r):
    if isinstance(r, dict):
        opts = {k: v for k, v in r.items() if k not in ("speaker", "text", "expr", "scene")}
        return [r.get("speaker", "NGUOI_KE"), r.get("text", ""), r.get("expr", "serious"), r.get("scene", ""), opts]
    return r


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    proj = Path(sys.argv[1]).expanduser().resolve() if len(sys.argv) > 1 else Path.cwd().resolve()
    out = proj / "audio"
    out.mkdir(parents=True, exist_ok=True)
    cache_dir = out / "cache_omni"
    cache_dir.mkdir(parents=True, exist_ok=True)

    cfg = json.loads((proj / "script.json").read_text(encoding="utf-8"))
    base_gap = float(cfg.get("gap", 0.62))
    target_dur = float(cfg.get("target_duration", 0.0))
    voice = str(cfg.get("omni_voice", "dinh-soan"))
    do_enhance = bool(cfg.get("omni_enhance", True))

    vdir = VOICES_DIR / voice
    if not vdir.is_dir():
        raise FileNotFoundError(f"Không tìm thấy giọng '{voice}' trong {VOICES_DIR}")

    raw_rows = [_norm_row(r) for r in cfg["lines"]]
    raw_dir = cache_dir / "_raw"
    enh_dir = cache_dir / "_enh"
    todo = {}
    model = None
    prompt = None

    for i, row in enumerate(raw_rows):
        clean = CUE.sub("", row[1])
        key = cache_key(voice, do_enhance, clean)
        if not (cache_dir / f"{key}.wav").exists() and key not in todo:
            raw_dir.mkdir(parents=True, exist_ok=True)
            raw_f = raw_dir / f"{key}.wav"
            if not raw_f.exists() or raw_f.stat().st_size < 1000:
                if model is None:
                    device, dtype = get_device_and_dtype()
                    model = OmniVoice.from_pretrained(str(ensure_omni_model("vi")), device_map=device, dtype=dtype)
                    prompt = model.create_voice_clone_prompt(
                        ref_audio=str(vdir / "ref.wav"),
                        ref_text=(vdir / "ref.txt").read_text(encoding="utf-8").strip(),
                    )
                generate(model, prompt, clean, raw_f)
                print(f"  [GEN] {i:03d}/{len(raw_rows)} {row[0]:10s}", flush=True)
            else:
                print(f"  [RAW-CACHE] {i:03d}/{len(raw_rows)} {row[0]:10s}", flush=True)
            todo[key] = True

    if todo:
        src_dir = raw_dir
        if model is not None:
            del model, prompt
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        if do_enhance:
            print(f"  [ENHANCE] Làm trong {len(todo)} câu bằng ClearerVoice...", flush=True)
            run_enhance(raw_dir, enh_dir)
            src_dir = enh_dir
        ffmpeg_bin = find_ffmpeg()
        for key in todo:
            finish(ffmpeg_bin, src_dir / f"{key}.wav", cache_dir / f"{key}.wav")
        shutil.rmtree(raw_dir, ignore_errors=True)
        shutil.rmtree(enh_dir, ignore_errors=True)

    for i, row in enumerate(raw_rows):
        key = cache_key(voice, do_enhance, CUE.sub("", row[1]))
        shutil.copy2(cache_dir / f"{key}.wav", out / f"{i:03d}.wav")
        print(f"  [TTS OK] {i:03d}/{len(raw_rows)} {row[0]:10s} ({voice})", flush=True)

    segments = []
    gap_weights = []
    for i, row in enumerate(raw_rows):
        spk, text, expr = row[:3]
        scene = row[3] if len(row) > 3 else spk
        opts = row[4] if len(row) > 4 else {}
        with wave.open(str(out / f"{i:03d}.wav")) as w:
            data = array.array("h", w.readframes(w.getnframes()))
        thr = 300
        a, b = 0, len(data)
        while a < b and abs(data[a]) < thr:
            a += 1
        while b > a and abs(data[b - 1]) < thr:
            b -= 1
        a = max(0, a - int(0.03 * SR))
        b = min(len(data), b + int(0.06 * SR))
        seg = data[a:b]
        segments.append((i, spk, text, expr, scene, opts, seg))
        w_gap = 1.0
        if opts.get("sfx") in ("clock12", "drip"):
            w_gap = 1.9
        elif spk != "NGUOI_KE":
            w_gap = 1.35
        elif i + 1 < len(raw_rows) and len(raw_rows[i + 1]) > 4 and raw_rows[i + 1][4].get("chapter"):
            w_gap = 2.2
        gap_weights.append(w_gap)

    total_speech = sum(len(x[6]) / SR for x in segments)
    tail_pad = 2.5
    if target_dur > total_speech + LEAD + tail_pad:
        rem = target_dur - total_speech - LEAD - tail_pad
        w_sum = sum(gap_weights)
        gaps = [rem * (w / w_sum) for w in gap_weights]
    else:
        gaps = [base_gap * w for w in gap_weights]

    lines = []
    pcm = array.array("h", [0] * int(LEAD * SR))
    t = LEAD
    for idx, (i, spk, text, expr, scene, opts, seg) in enumerate(segments):
        dur = len(seg) / SR
        clean = CUE.sub("", text)
        words = estimate_words(clean, dur)
        g = gaps[idx]
        lines.append(
            dict(
                i=i,
                speaker=spk,
                scene=scene,
                expr=expr,
                text=clean,
                start=round(t, 3),
                end=round(t + dur, 3),
                gap=round(g, 3),
                words=[dict(w=x["w"], s=round(t + x["s"], 3), e=round(t + x["e"], 3)) for x in words],
                **{k: v for k, v in opts.items() if k not in ("gap",)},
            )
        )
        pcm.extend(seg)
        pcm.extend([0] * int(g * SR))
        t += dur + g

    pcm.extend([0] * int(tail_pad * SR))
    total = len(pcm) / SR
    with wave.open(str(proj / "voice.wav"), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())

    hop = SR // FPS
    amp = []
    for f in range(math.ceil(total * FPS)):
        ch = pcm[f * hop : (f + 1) * hop]
        amp.append(math.sqrt(sum(x * x for x in ch) / max(1, len(ch))) if ch else 0)
    mx = sorted(amp)[int(len(amp) * 0.97)] or 1
    amp = [round(min(1, x / mx), 3) for x in amp]
    data = dict(duration=round(total, 3), fps=FPS, lines=lines, amp=amp)
    (proj / "timings.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    (proj / "timings.js").write_text("window.TIMINGS=" + json.dumps(data, ensure_ascii=False) + ";", encoding="utf-8")
    print(f"SPEECH DURATION: {total_speech:.2f}s | TOTAL VIDEO DURATION: {total:.2f}s ({total / 60:.2f} min)")


if __name__ == "__main__":
    main()
