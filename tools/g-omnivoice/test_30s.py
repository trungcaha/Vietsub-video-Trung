# -*- coding: utf-8 -*-
"""Đọc thử ~30 giây mở đầu truyện Gỡ Ngải bằng G-OmniVoice.

Người kể: clone giọng Đình Soạn từ voices/dinh-soan/ref.wav.
Sen: giọng nữ thì thầm tạo từ mô tả (Voice Design).
"""
from __future__ import annotations

import re
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

SR = 24000
REF_DIR = VOICES_DIR / "dinh-soan"
REF_AUDIO = str(REF_DIR / "ref.wav")
REF_TEXT = (REF_DIR / "ref.txt").read_text(encoding="utf-8").strip()

NARRATOR = dict(ref_audio=REF_AUDIO, ref_text=REF_TEXT)
SEN = dict(instruct="female, young adult, whisper")

LINES = [
    (
        NARRATOR,
        "Đêm tân hôn, làng Đoài tắt đèn từ lâu mà buồng cưới của nhà bà Tần vẫn còn một ngọn đèn dầu vặn nhỏ. "
        "Sen nằm nghiêng, tay còn giữ vạt áo, nghe tiếng chồng thở đều bên cạnh.",
    ),
    (
        NARRATOR,
        "Cô mệt rã rời. Cả ngày cúi chào rót nước, đến giờ xương sống mới được duỗi ra. "
        "Ngoài sân, mấy tàu cau đập vào nhau đồp bộp trong gió. "
        "Ở trong nhà, cái đồng hồ quả lắc gõ mười hai tiếng chậm và nặng.",
    ),
    (SEN, "Ai... ai đó?"),
]


def sentences(text: str):
    return [s.strip() for s in re.split(r"(?<=[.!?…])\s+", text.strip()) if s.strip()]


def main() -> None:
    (HERE / "out").mkdir(exist_ok=True)
    device, dtype = get_device_and_dtype()
    model = OmniVoice.from_pretrained(str(ensure_omni_model("vi")), device_map=device, dtype=dtype)
    gap_sentence = np.zeros(int(0.35 * SR), dtype=np.float32)
    gap_line = np.zeros(int(0.8 * SR), dtype=np.float32)

    parts, t0 = [], time.time()
    for voice, text in LINES:
        for s in sentences(text):
            parts += [model.generate(text=s, language="vi", **voice)[0].astype(np.float32), gap_sentence]
        parts.append(gap_line)

    audio = np.concatenate(parts)
    audio *= min(1.0, 0.89 / max(1e-6, float(np.abs(audio).max())))
    out = HERE / "out" / "thu_30s_go_ngai.wav"
    sf.write(out, audio, SR)
    print(f"{len(audio) / SR:.1f}s audio trong {time.time() - t0:.1f}s -> {out}")


if __name__ == "__main__":
    main()
