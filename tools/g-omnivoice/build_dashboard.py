# -*- coding: utf-8 -*-
"""Dựng trang giong-clone.html liệt kê mọi giọng đã clone trong voices/ (đọc voices/<id>/meta.json).

Chạy lại sau mỗi lần thêm/sửa giọng:  python build_dashboard.py
Mỗi giọng cần: ref.wav, ref.txt, meta.json; demo.wav là tùy chọn.
Âm thanh được nén MP3 và nhúng thẳng vào trang (data URI), mở ở bất kỳ đâu vẫn nghe được.
"""
from __future__ import annotations

import base64
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import soundfile as sf

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from omni_env import find_ffmpeg  # noqa: E402


def embed_mp3(wav: Path, kbps: int, ffmpeg_bin: str) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        mp3 = Path(tmp) / "a.mp3"
        subprocess.run(
            [ffmpeg_bin, "-v", "error", "-y", "-i", str(wav), "-ac", "1", "-ar", "44100", "-b:a", f"{kbps}k", str(mp3)],
            check=True,
        )
        return "data:audio/mpeg;base64," + base64.b64encode(mp3.read_bytes()).decode("ascii")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    ffmpeg_bin = find_ffmpeg()
    voices = []
    for d in sorted((HERE / "voices").iterdir()):
        if not d.is_dir() or not (d / "meta.json").is_file():
            continue
        m = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        m["id"] = d.name
        m["ref_text"] = (d / "ref.txt").read_text(encoding="utf-8").strip()
        m["ref"] = embed_mp3(d / "ref.wav", 96, ffmpeg_bin)
        m["ref_dur"] = round(sf.info(str(d / "ref.wav")).duration, 1)
        if (d / "demo.wav").is_file():
            m["demo"] = embed_mp3(d / "demo.wav", 64, ffmpeg_bin)
            m["demo_dur"] = round(sf.info(str(d / "demo.wav")).duration)
        voices.append(m)

    html = (HERE / "dashboard_template.html").read_text(encoding="utf-8")
    html = html.replace("/*__DATA__*/[]", json.dumps(voices, ensure_ascii=False))
    html = html.replace("__UPDATED__", time.strftime("%H:%M %d/%m/%Y"))
    out_html = HERE / "giong-clone.html"
    out_html.write_text(html, encoding="utf-8")
    size = out_html.stat().st_size / 1e6
    print(f"{len(voices)} giọng -> {out_html} ({size:.1f} MB, audio đã nhúng)")


if __name__ == "__main__":
    main()
