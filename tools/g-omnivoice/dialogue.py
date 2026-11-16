# -*- coding: utf-8 -*-
"""Đọc thử đoạn hội thoại nhiều giọng (hỗ trợ cả tiếng Việt & tiếng Anh) rồi nối lại.

Chạy:
  python dialogue.py <hội_thoại.txt> <ra.wav> [--enhance]

Mỗi dòng trong <hội_thoại.txt> có dạng:
  <id giọng>|<câu thoại>
hoặc đổi tốc độ theo vai:
  <id giọng>@<tốc độ>|<câu thoại>  (vd: adam-top-top@1.14|Ê ê, đứng sau tui nè!)
"""
from __future__ import annotations

import argparse
import gc
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import soundfile as sf

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from omni_env import (  # noqa: E402
    VOICES_DIR,
    ensure_omni_model,
    get_device_and_dtype,
    infer_voice_lang,
    run_enhance,
)
from vn_textnorm import normalize  # noqa: E402

SR = 24000


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    ap = argparse.ArgumentParser(description="Đọc hội thoại nhiều vai bằng G-OmniVoice.")
    ap.add_argument("src", help="File hội thoại dạng <id_giong>[@speed]|<cau_thoai>")
    ap.add_argument("out", help="File WAV đầu ra")
    ap.add_argument("--enhance", action="store_true", help="Làm trong giọng và nâng lên 48kHz qua ClearerVoice")
    args = ap.parse_args()

    src_path = Path(args.src)
    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    lines = [l.split("|", 1) for l in src_path.read_text(encoding="utf-8").splitlines() if "|" in l and l.strip()]
    if not lines:
        raise ValueError(f"Không có dòng hợp lệ (dạng <id>|<text>) trong {src_path}")

    import torch
    from omnivoice import OmniVoice

    device, dtype = get_device_and_dtype()
    models = {}
    prompts = {}
    parts, t0 = [], time.time()

    for vid_raw, text in lines:
        vid, _, speed = vid_raw.strip().partition("@")
        lang = infer_voice_lang(vid)
        if lang not in models:
            model_dir = ensure_omni_model(lang)
            models[lang] = OmniVoice.from_pretrained(str(model_dir), device_map=device, dtype=dtype)
        key = (lang, vid)
        if key not in prompts:
            vdir = VOICES_DIR / vid
            if not vdir.is_dir():
                raise FileNotFoundError(f"Không tìm thấy giọng '{vid}' trong {VOICES_DIR}")
            prompts[key] = models[lang].create_voice_clone_prompt(
                ref_audio=str(vdir / "ref.wav"),
                ref_text=(vdir / "ref.txt").read_text(encoding="utf-8").strip(),
            )
        spoken = normalize(text.strip()) if lang == "vi" else text.strip()
        audio_chunk = models[lang].generate(
            text=spoken,
            voice_clone_prompt=prompts[key],
            language=lang,
            speed=float(speed or 1.0),
        )[0]
        parts += [audio_chunk.astype(np.float32), np.zeros(int(0.5 * SR), dtype=np.float32)]

    audio = np.concatenate(parts)
    # Giọng mẫu to (vd Adam) có thể vượt 0 dB -> hạ về tối đa 0.89 tránh vỡ tiếng
    audio *= min(1.0, 0.89 / max(1e-6, float(np.abs(audio).max())))

    if args.enhance:
        models.clear()
        prompts.clear()
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        with tempfile.TemporaryDirectory() as tmp_dir:
            raw_wav = Path(tmp_dir) / "raw_24k.wav"
            sf.write(raw_wav, audio, SR, subtype="FLOAT")
            run_enhance(raw_wav, out_path)
    else:
        sf.write(out_path, audio, SR)

    dur = sf.info(str(out_path)).duration if out_path.is_file() else len(audio) / SR
    print(f"{dur:.1f}s audio trong {time.time() - t0:.1f}s -> {out_path}")


if __name__ == "__main__":
    main()
