# -*- coding: utf-8 -*-
"""So sánh 2 model (G-OmniVoice tiếng Việt vs k2-fsa OmniVoice gốc đa ngôn ngữ).

Chạy:
  python compare_models.py <ref.wav> <ref.txt> <văn_bản.txt> <thư_mục_ra> [vi|en]
"""
from __future__ import annotations

import gc
import re
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf
import torch
from omnivoice import OmniVoice

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from omni_env import ensure_omni_model, get_device_and_dtype  # noqa: E402
from vn_textnorm import normalize  # noqa: E402

SR = 24000


def main() -> None:
    if len(sys.argv) < 5:
        raise SystemExit("Cú pháp: python compare_models.py <ref.wav> <ref.txt> <văn bản.txt> <thư mục ra> [vi|en]")

    ref, ref_txt, text_file, out_dir = sys.argv[1:5]
    lang = sys.argv[5] if len(sys.argv) > 5 else "en"
    out = Path(out_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    ref_text = Path(ref_txt).read_text(encoding="utf-8").strip()
    raw_lines = Path(text_file).read_text(encoding="utf-8").splitlines()
    sentences = []
    for l in raw_lines:
        line = normalize(l.strip()) if lang == "vi" else l.strip()
        for s in re.split(r"(?<=[.!?…])\s+", line):
            if s.strip():
                sentences.append(s.strip())

    device, dtype = get_device_and_dtype()
    for label, model_lang in [("g-omnivoice", "vi"), ("omnivoice-goc", "en")]:
        model_dir = ensure_omni_model(model_lang)
        model = OmniVoice.from_pretrained(str(model_dir), device_map=device, dtype=dtype)
        prompt = model.create_voice_clone_prompt(ref_audio=ref, ref_text=ref_text)
        t0, parts = time.time(), []
        for s in sentences:
            parts += [
                model.generate(text=s, voice_clone_prompt=prompt, language=lang)[0].astype(np.float32),
                np.zeros(int(0.35 * SR), dtype=np.float32),
            ]
        audio = np.concatenate(parts)
        audio *= min(1.0, 0.89 / max(1e-6, float(np.abs(audio).max())))
        sf.write(out / f"{label}.wav", audio, SR)
        print(f"{label}: {time.time() - t0:.1f}s -> {out / f'{label}.wav'}", flush=True)
        del model, prompt
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()


if __name__ == "__main__":
    main()
