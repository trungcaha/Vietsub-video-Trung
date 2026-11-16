# -*- coding: utf-8 -*-
"""Làm trong giọng nói: khử nhiễu/tạp âm (MossFormer2_SE_48K) rồi phục hồi dải cao (MossFormer2_SR_48K).

Chạy:  python enhance.py <vào.wav | thư mục> <ra.wav | thư mục> [--no-se] [--no-sr]
Ra 48kHz mono PCM_16. Model tự tải về checkpoints/ lần đầu.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

HERE = Path(__file__).resolve().parent


def main() -> None:
    ap = argparse.ArgumentParser(description="Khử nhiễu & phục hồi dải cao 48kHz bằng ClearerVoice.")
    ap.add_argument("src", help="File WAV vào hoặc thư mục chứa các file *.wav")
    ap.add_argument("dst", help="File WAV ra hoặc thư mục đầu ra")
    ap.add_argument("--no-se", action="store_true", help="Bỏ bước khử nhiễu (MossFormer2_SE_48K)")
    ap.add_argument("--no-sr", action="store_true", help="Bỏ bước phục hồi dải cao (MossFormer2_SR_48K)")
    a = ap.parse_args()

    # Resolve trước khi chdir vì ClearVoice đọc/tải checkpoints/ theo đường dẫn tương đối
    src = Path(a.src).expanduser().resolve()
    dst = Path(a.dst).expanduser().resolve()
    ffmpeg_bin = os.environ.get("FFMPEG_BIN", "").strip() or shutil.which("ffmpeg") or "ffmpeg"

    os.chdir(HERE)
    from clearvoice import ClearVoice  # noqa: E402

    steps = []
    if not a.no_se:
        steps.append(ClearVoice(task="speech_enhancement", model_names=["MossFormer2_SE_48K"]))
    if not a.no_sr:
        steps.append(ClearVoice(task="speech_super_resolution", model_names=["MossFormer2_SR_48K"]))

    if src.is_dir():
        pairs = [(f, dst / f.name) for f in sorted(src.glob("*.wav"))]
        dst.mkdir(parents=True, exist_ok=True)
    else:
        pairs = [(src, dst)]
        dst.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        for idx, (f, out) in enumerate(pairs):
            if out.exists() and out.stat().st_size > 1000:
                print("-> [cached]", out, flush=True)
                continue
            cur = tmp / f"in_{idx}.wav"
            subprocess.run(
                [ffmpeg_bin, "-v", "error", "-y", "-i", str(f), "-ac", "1", "-ar", "48000", str(cur)],
                check=True,
            )
            for i, cv in enumerate(steps):
                audio = np.asarray(cv(input_path=str(cur), online_write=False)).squeeze()
                cur = tmp / f"s_{idx}_{i}.wav"
                sf.write(cur, audio, 48000)
            sf.write(out, sf.read(cur)[0], 48000, subtype="PCM_16")
            print("->", out, flush=True)


if __name__ == "__main__":
    main()
