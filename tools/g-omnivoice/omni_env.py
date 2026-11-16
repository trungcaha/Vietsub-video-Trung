# -*- coding: utf-8 -*-
"""Tiện ích dò môi trường đa nền tảng (Windows / macOS / Linux) cho G-OmniVoice & ClearerVoice.

Lưu ý: Không import torch, omnivoice hay huggingface_hub ở top-level để các script
pipeline có thể import omni_env từ Python hệ thống trước khi tự re-exec sang .venv.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

OMNIVOICE_ROOT = Path(__file__).resolve().parent
VOICES_DIR = OMNIVOICE_ROOT / "voices"

HF_REPOS: Dict[str, Tuple[str, str]] = {
    "vi": ("model", "g-group-ai-lab/g-omnivoice"),
    "en": ("model-goc", "k2-fsa/OmniVoice"),
}


def get_device_and_dtype():
    """Chọn thiết bị (CUDA -> Apple MPS -> CPU) và dtype phù hợp."""
    import torch

    if torch.cuda.is_available():
        return "cuda:0", torch.float16
    mps = getattr(torch.backends, "mps", None)
    if mps is not None and mps.is_available():
        return "mps", torch.float32
    return "cpu", torch.float32


def _has_model_weights(model_dir: Path) -> bool:
    return (
        (model_dir / "model.safetensors").is_file()
        and (model_dir / "config.json").is_file()
        and (model_dir / "audio_tokenizer" / "model.safetensors").is_file()
    )


def ensure_omni_model(lang: str = "vi") -> Path:
    """Tìm thư mục model cục bộ (hoặc qua biến môi trường), thiếu thì tự tải từ HuggingFace."""
    code = (lang or "vi").strip().lower()
    if code not in HF_REPOS:
        raise ValueError(f"Ngôn ngữ model không hợp lệ: {lang!r} (chỉ hỗ trợ 'vi' hoặc 'en').")

    env_key = "OMNIVOICE_MODEL_DIR" if code == "vi" else "OMNIVOICE_MODEL_EN_DIR"
    env_val = os.environ.get(env_key, "").strip()
    if env_val:
        env_dir = Path(env_val).expanduser().resolve()
        if _has_model_weights(env_dir):
            return env_dir

    subdir, repo_id = HF_REPOS[code]
    target_dir = OMNIVOICE_ROOT / subdir
    if not _has_model_weights(target_dir):
        target_dir.mkdir(parents=True, exist_ok=True)
        print(f"[G-OmniVoice] Chưa thấy model '{subdir}', đang tải từ HuggingFace ({repo_id})...", flush=True)
        from huggingface_hub import snapshot_download

        snapshot_download(repo_id=repo_id, local_dir=str(target_dir))
    return target_dir


def infer_voice_lang(voice_id: str) -> str:
    """Suy ra ngôn ngữ model ('en' hay 'vi') từ metadata giọng."""
    vid = (voice_id or "").strip()
    if vid.startswith("en-"):
        return "en"
    meta_path = VOICES_DIR / vid / "meta.json"
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            cats = meta.get("categories") or []
            if any("tiếng anh" in str(c).lower() for c in cats):
                return "en"
        except Exception:
            pass
    return "vi"


def list_voices() -> List[Dict[str, str]]:
    """Đọc danh sách toàn bộ giọng hợp lệ trong thư mục voices/."""
    items: List[Dict[str, str]] = []
    if not VOICES_DIR.is_dir():
        return items
    for d in sorted(VOICES_DIR.iterdir()):
        if not d.is_dir():
            continue
        if not ((d / "ref.wav").is_file() and (d / "ref.txt").is_file() and (d / "meta.json").is_file()):
            continue
        try:
            meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        except Exception:
            meta = {}
        items.append(
            {
                "id": d.name,
                "name": str(meta.get("name") or d.name),
                "gender": str(meta.get("gender") or ""),
                "region": str(meta.get("region") or ""),
                "status": str(meta.get("status") or ""),
                "categories": ", ".join(str(c) for c in (meta.get("categories") or [])),
                "lang": infer_voice_lang(d.name),
            }
        )
    return items


def get_voice_enhance_dir() -> Path:
    """Tìm thư mục ClearerVoice voice-enhance (ưu tiên VOICE_ENHANCE_DIR)."""
    env_val = os.environ.get("VOICE_ENHANCE_DIR", "").strip()
    if env_val:
        p = Path(env_val).expanduser().resolve()
        if (p / "enhance.py").is_file():
            return p
    return OMNIVOICE_ROOT.parent / "voice-enhance"


def get_sep_models_dir() -> Path:
    """Tìm thư mục chứa model tách nhạc UVR/RoFormer (ưu tiên OMNIVOICE_SEP_DIR)."""
    env_val = os.environ.get("OMNIVOICE_SEP_DIR", "").strip()
    if env_val:
        p = Path(env_val).expanduser().resolve()
        p.mkdir(parents=True, exist_ok=True)
        return p
    d = OMNIVOICE_ROOT / "sep_models"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_venv_python(tool_dir: Path) -> Path:
    """Trả về Python trong .venv của tool_dir (Windows/macOS/Linux), fallback sys.executable."""
    cand = tool_dir / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if cand.is_file():
        return cand
    return Path(sys.executable)


def find_ffmpeg() -> str:
    """Tìm binary ffmpeg qua FFMPEG_BIN hoặc PATH."""
    env_val = os.environ.get("FFMPEG_BIN", "").strip()
    if env_val:
        return env_val
    return shutil.which("ffmpeg") or "ffmpeg"


def find_ffprobe() -> str:
    """Tìm binary ffprobe qua FFPROBE_BIN hoặc PATH."""
    env_val = os.environ.get("FFPROBE_BIN", "").strip()
    if env_val:
        return env_val
    return shutil.which("ffprobe") or "ffprobe"


def run_enhance(src_path: Path, dst_path: Path, extra_args: Optional[Sequence[str]] = None) -> None:
    """Gọi ClearerVoice enhance.py trong .venv riêng để khử tạp âm & nâng 48kHz."""
    enh_dir = get_voice_enhance_dir()
    enhance_script = enh_dir / "enhance.py"
    if not enhance_script.is_file():
        raise FileNotFoundError(f"Không tìm thấy ClearerVoice enhance.py tại: {enhance_script}")
    py = get_venv_python(enh_dir)
    cmd = [str(py), str(enhance_script), str(src_path), str(dst_path), *(list(extra_args) if extra_args else [])]
    subprocess.run(cmd, check=True)
