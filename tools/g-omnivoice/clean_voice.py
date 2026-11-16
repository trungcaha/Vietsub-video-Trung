# -*- coding: utf-8 -*-
"""Tách giọng nói khỏi nhạc nền rồi làm trong để tạo mẫu giọng clone 48kHz sạch.

Chạy:
  python clean_voice.py <file_am_thanh_hoac_video> [thu_muc_ra]

Kết quả:
  vocals.wav (tách nhạc) -> vocals_dry.wav (khử nhiễu/vang) -> clean.wav (48kHz mono)
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

from audio_separator.separator import Separator

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from omni_env import get_sep_models_dir, run_enhance  # noqa: E402


def separate(models_dir: Path, out_dir: Path, model: str, inp: Path, stem: str, name: str) -> Path:
    sep = Separator(output_dir=str(out_dir), model_file_dir=str(models_dir), output_single_stem=stem)
    sep.load_model(model)
    produced = Path(sep.separate(str(inp))[0]).name
    dst = out_dir / name
    shutil.move(str(out_dir / produced), str(dst))
    return dst


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("Cú pháp: python clean_voice.py <file âm thanh/video> [thư mục ra]")

    src = Path(sys.argv[1]).expanduser().resolve()
    out = Path(sys.argv[2]).expanduser().resolve() if len(sys.argv) > 2 else src.parent
    out.mkdir(parents=True, exist_ok=True)
    models_dir = get_sep_models_dir()

    # Bước 1: BS-RoFormer tách lời khỏi nhạc nền
    vocals = separate(models_dir, out, "model_bs_roformer_ep_317_sdr_12.9755.ckpt", src, "Vocals", "vocals.wav")
    # Bước 2: Mel-RoFormer Denoise xoá nhạc sót, nhiễu nền, tiếng vang
    dry = separate(models_dir, out, "denoise_mel_band_roformer_aufr33_aggr_sdr_27.9768.ckpt", vocals, "dry", "vocals_dry.wav")
    # Bước 3: ClearerVoice MossFormer2 khử tạp âm + phục hồi dải cao 48kHz
    run_enhance(dry, out / "clean.wav")
    print("->", out / "clean.wav")


if __name__ == "__main__":
    main()
