# -*- coding: utf-8 -*-
"""Clone giọng từ mẫu có sẵn trong voices/ hoặc clip tùy ý rồi đọc văn bản dài.

Cú pháp cũ (tương thích ngược):
  python clone.py <ref.wav> <ref.txt> <văn bản.txt> <ra.wav> [vi|en]

Cú pháp mới tiện lợi:
  python clone.py --list-voices
  python clone.py --voice dinh-soan --text "Xin chào Việt Nam." --out out.wav --enhance
  python clone.py --voice quang-nguyen --text-file examples/van_ban_mau.txt --out out.wav
"""
from __future__ import annotations

import argparse
import gc
import re
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
    list_voices,
    run_enhance,
)
from vn_textnorm import normalize  # noqa: E402

SR = 24000


def _print_voices() -> None:
    voices = list_voices()
    print(f"Tổng cộng {len(voices)} giọng trong {VOICES_DIR}:")
    print(f"{'ID':20s} | {'Tên':22s} | {'GT':4s} | {'Lang':4s} | {'Thể loại'}")
    print("-" * 88)
    for v in voices:
        print(f"{v['id']:20s} | {v['name']:22s} | {v['gender']:4s} | {v['lang']:4s} | {v['categories']}")


def _parse_args():
    argv = sys.argv[1:]
    # Tương thích ngược: clone.py <ref.wav> <ref.txt> <văn_bản.txt> <ra.wav> [vi|en]
    if argv and not argv[0].startswith("-") and len(argv) in (4, 5):
        return argparse.Namespace(
            list_voices=False,
            voice=None,
            ref_audio=argv[0],
            ref_txt=argv[1],
            text=None,
            text_file=argv[2],
            out=argv[3],
            lang=argv[4] if len(argv) > 4 else "vi",
            speed=1.0,
            enhance=False,
        )

    ap = argparse.ArgumentParser(description="Clone giọng và đọc văn bản bằng G-OmniVoice.")
    ap.add_argument("--list-voices", action="store_true", help="Liệt kê toàn bộ giọng có sẵn trong voices/")
    ap.add_argument("--voice", type=str, help="ID giọng trong voices/ (vd: dinh-soan, mai-be-phuong)")
    ap.add_argument("--ref-audio", type=str, help="Đường dẫn file WAV mẫu (nếu không dùng --voice)")
    ap.add_argument("--ref-txt", type=str, help="Đường dẫn file TXT lời thoại của mẫu")
    ap.add_argument("--text", type=str, help="Chuỗi văn bản cần đọc trực tiếp")
    ap.add_argument("--text-file", type=str, help="Đường dẫn file TXT chứa văn bản cần đọc")
    ap.add_argument("--out", type=str, help="Đường dẫn file WAV đầu ra")
    ap.add_argument("--lang", choices=["vi", "en"], default=None, help="Ngôn ngữ model (vi hoặc en)")
    ap.add_argument("--speed", type=float, default=1.0, help="Tốc độ đọc (mặc định 1.0)")
    ap.add_argument("--enhance", action="store_true", help="Làm trong giọng và nâng lên 48kHz qua ClearerVoice")
    return ap.parse_args(argv)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = _parse_args()

    if args.list_voices:
        _print_voices()
        return

    if args.voice:
        vdir = VOICES_DIR / args.voice
        if not vdir.is_dir():
            raise FileNotFoundError(f"Không tìm thấy giọng '{args.voice}' trong {VOICES_DIR}. Chạy --list-voices để xem.")
        ref_audio = str(vdir / "ref.wav")
        ref_txt_path = vdir / "ref.txt"
        lang = args.lang or infer_voice_lang(args.voice)
    else:
        if not (args.ref_audio and args.ref_txt):
            raise SystemExit("Cần truyền --voice <id> hoặc cả --ref-audio và --ref-txt (hoặc chạy --list-voices).")
        ref_audio = args.ref_audio
        ref_txt_path = Path(args.ref_txt)
        lang = args.lang or "vi"

    if args.text is not None:
        text = args.text
    elif args.text_file:
        text = Path(args.text_file).read_text(encoding="utf-8")
    else:
        raise SystemExit("Cần truyền --text \"...\" hoặc --text-file <path>.")

    if not args.out:
        raise SystemExit("Cần truyền --out <ra.wav>.")

    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    ref_text = ref_txt_path.read_text(encoding="utf-8").strip()

    import torch
    from omnivoice import OmniVoice

    model_dir = ensure_omni_model(lang)
    device, dtype = get_device_and_dtype()
    model = OmniVoice.from_pretrained(str(model_dir), device_map=device, dtype=dtype)
    prompt = model.create_voice_clone_prompt(ref_audio=ref_audio, ref_text=ref_text)
    gap_sentence = np.zeros(int(0.35 * SR), dtype=np.float32)
    gap_para = np.zeros(int(0.8 * SR), dtype=np.float32)

    parts, t0 = [], time.time()
    for para in [p for p in text.splitlines() if p.strip()]:
        if lang == "vi":
            para = normalize(para)
        sentences = [s.strip() for s in re.split(r"(?<=[.!?…])\s+", para.strip()) if s.strip()]
        for s in sentences:
            gen_kw = dict(text=s, voice_clone_prompt=prompt, language=lang)
            if abs(float(args.speed) - 1.0) > 1e-3:
                gen_kw["speed"] = float(args.speed)
            audio_chunk = model.generate(**gen_kw)[0]
            parts += [audio_chunk.astype(np.float32), gap_sentence]
        parts.append(gap_para)

    if not parts:
        raise ValueError("Văn bản đầu vào rỗng, không có câu nào để đọc.")

    audio = np.concatenate(parts)
    # Giọng mẫu to có thể vượt 0 dB -> kéo nhẹ về -1 dBFS trước khi ghi file
    audio *= min(1.0, 0.89 / max(1e-6, float(np.abs(audio).max())))

    if args.enhance:
        del model, prompt
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
    print(f"{dur:.1f}s audio ({lang}) trong {time.time() - t0:.1f}s -> {out_path}")


if __name__ == "__main__":
    main()
