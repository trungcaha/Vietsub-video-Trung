# -*- coding: utf-8 -*-
"""Đọc thử G-OmniVoice: clone giọng dẫn truyện Đình Soạn + tạo giọng từ mô tả (Voice Design).

Chạy:  python test_tts.py
Kết quả nằm trong thư mục out/
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf
from omnivoice import OmniVoice

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from omni_env import VOICES_DIR, ensure_omni_model, get_device_and_dtype  # noqa: E402

OUT = HERE / "out"
OUT.mkdir(exist_ok=True)

REF_DIR = VOICES_DIR / "dinh-soan"
REF_AUDIO = str(REF_DIR / "ref.wav")
REF_TEXT = (REF_DIR / "ref.txt").read_text(encoding="utf-8").strip()

LINE = (
    "Đêm ấy gió thổi rít qua kẽ vách. Ngọn đèn dầu chập chờn, "
    "rồi tắt phụt. Trong bóng tối, có tiếng ai đó khe khẽ gọi tên Sen."
)

JOBS = [
    ("clone_dan_truyen", dict(ref_audio=REF_AUDIO, ref_text=REF_TEXT)),
    ("design_ba_lao", dict(instruct="female, elderly, low pitch")),
    ("design_nu_ma_mi", dict(instruct="female, young adult, whisper")),
]


def main() -> None:
    t0 = time.time()
    device, dtype = get_device_and_dtype()
    model = OmniVoice.from_pretrained(str(ensure_omni_model("vi")), device_map=device, dtype=dtype)
    print(f"Nạp model: {time.time() - t0:.1f}s ({device})")

    for name, kw in JOBS:
        t = time.time()
        try:
            audio = model.generate(text=LINE, language="vi", **kw)[0].astype(np.float32)
        except Exception as e:
            print(f"{name}: LỖI {e}")
            continue
        audio *= min(1.0, 0.89 / max(1e-6, float(np.abs(audio).max())))
        path = OUT / f"{name}.wav"
        sf.write(path, audio, 24000)
        print(f"{name}: {len(audio) / 24000:.1f}s audio trong {time.time() - t:.1f}s -> {path}")


if __name__ == "__main__":
    main()
