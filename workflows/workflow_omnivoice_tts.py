# -*- coding: utf-8 -*-
r"""Workflow chuẩn cho công cụ run_workflow:
Điều phối chuẩn hóa kịch bản tiếng Việt (tuỳ chọn) + tạo giọng hàng loạt bằng G-OmniVoice
(chạy tuần tự trên GPU để tránh tràn VRAM) và kiểm định ffprobe (48kHz, duration > 0).

Tham số Args:
  - input_dir: Thư mục chứa các file *.txt hoặc thư mục con chứa script.json (mặc định CWD)
  - output_dir: Thư mục xuất WAV thành phẩm (mặc định <input_dir>/voice_out)
  - voice: ID giọng trong tools/g-omnivoice/voices/ (mặc định "dinh-soan")
  - enhance: True/False làm trong 48kHz bằng ClearerVoice (mặc định True)
  - model: Model tier cho agent chuẩn hóa văn bản (mặc định "flash")
"""
import json
import os
import subprocess
import sys
from pathlib import Path


def _resolve_repo_root() -> Path:
    here = Path(__file__).resolve().parent.parent
    if (here / "tools" / "g-omnivoice" / "clone.py").is_file():
        return here
    ws = globals().get("WORKSPACES") or ()
    for w in ws:
        cand = Path(w).expanduser().resolve()
        if (cand / "tools" / "g-omnivoice" / "clone.py").is_file():
            return cand
    return Path.cwd().resolve()


REPO_ROOT = _resolve_repo_root()
OMNI_DIR = REPO_ROOT / "tools" / "g-omnivoice"
if str(OMNI_DIR) not in sys.path:
    sys.path.insert(0, str(OMNI_DIR))

from omni_env import find_ffprobe, get_venv_python, list_voices  # noqa: E402

g_args = globals().get("args") or {}
INPUT_DIR = Path(str(g_args.get("input_dir") or Path.cwd())).expanduser().resolve()
OUTPUT_DIR = Path(str(g_args.get("output_dir") or (INPUT_DIR / "voice_out"))).expanduser().resolve()
VOICE_ID = str(g_args.get("voice") or "dinh-soan").strip()
DO_ENHANCE = bool(g_args.get("enhance", True))
MODEL_TIER = str(g_args.get("model") or "flash")

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
OMNI_PY = get_venv_python(OMNI_DIR)
FFPROBE_BIN = find_ffprobe()


phase("1. Discover Inputs & Optional Text Normalization")
valid_ids = {v["id"] for v in list_voices()}
if VOICE_ID not in valid_ids:
    raise ValueError(f"Giọng '{VOICE_ID}' không tồn tại trong {OMNI_DIR / 'voices'}. Hợp lệ: {sorted(valid_ids)}")

raw_scripts = sorted(INPUT_DIR.glob("*.raw.txt"))
if raw_scripts:
    log(f"Phát hiện {len(raw_scripts)} file .raw.txt, điều phối chuẩn hóa song song (model={MODEL_TIER})...")
    norm_results = await parallel(
        raw_scripts,
        lambda p: agent(
            f"""Đọc `{p}`, viết lại toàn bộ số đếm, ngày tháng, đơn vị thành chữ tiếng Việt tự nhiên để đọc TTS,
giữ nguyên nội dung và câu từ, lưu kết quả sang `{p.with_suffix('').with_suffix('.txt')}` bằng `write_file` (không truyền ArtifactMetadata),
rồi gọi `finish` trả về đường dẫn file đã ghi.""",
            schema={"type": "string"},
            role=f"Normalize {p.name}",
            model=MODEL_TIER,
        ),
    )
    log("Chuẩn hóa xong:", norm_results)

txt_files = [p for p in sorted(INPUT_DIR.glob("*.txt")) if not p.name.endswith(".raw.txt")]
json_projects = [p.parent for p in sorted(INPUT_DIR.glob("*/script.json"))]
if (INPUT_DIR / "script.json").is_file():
    json_projects.insert(0, INPUT_DIR)

log(f"Tìm thấy {len(txt_files)} file .txt và {len(json_projects)} dự án script.json | voice={VOICE_ID} | enhance={DO_ENHANCE}")


phase("2. Sequential GPU Synthesis")
produced_wavs = []

for tf in txt_files:
    out_wav = OUTPUT_DIR / f"{tf.stem}.wav"
    cmd = [
        str(OMNI_PY),
        str(OMNI_DIR / "clone.py"),
        "--voice",
        VOICE_ID,
        "--text-file",
        str(tf),
        "--out",
        str(out_wav),
    ]
    if DO_ENHANCE:
        cmd.append("--enhance")
    log("Chạy:", " ".join(cmd))
    subprocess.run(cmd, check=True)
    produced_wavs.append(out_wav)

for pdir in json_projects:
    cmd = [str(OMNI_PY), str(OMNI_DIR / "pipelines" / "tts_omnivoice.py"), str(pdir)]
    log("Chạy pipeline:", " ".join(cmd))
    subprocess.run(cmd, check=True)
    if (pdir / "voice.wav").is_file():
        produced_wavs.append(pdir / "voice.wav")


phase("3. FFprobe Audio Verification")
verified = []
for wav in produced_wavs:
    res = subprocess.run(
        [
            FFPROBE_BIN,
            "-v",
            "error",
            "-show_entries",
            "stream=sample_rate,channels:format=duration",
            "-of",
            "json",
            str(wav),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    info = json.loads(res.stdout)
    dur = float((info.get("format") or {}).get("duration") or 0.0)
    stream = (info.get("streams") or [{}])[0]
    sr = int(stream.get("sample_rate") or 0)
    if dur <= 0.0:
        raise RuntimeError(f"File âm thanh rỗng: {wav}")
    verified.append({"file": str(wav), "duration_sec": round(dur, 2), "sample_rate": sr})

log(f"ĐÃ TẠO & KIỂM ĐỊNH THÀNH CÔNG {len(verified)} FILE AUDIO:", json.dumps(verified, ensure_ascii=False))
