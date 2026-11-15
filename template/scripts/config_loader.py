# -*- coding: utf-8 -*-
"""Tiện ích nạp cấu hình project.json và tự động dò tìm công cụ hệ thống (không hardcode đường dẫn cá nhân)."""

import argparse
import importlib.util
import json
import os
import re
import shutil
import site
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

DEFAULT_CONFIG: Dict[str, Any] = {
    "project_slug": "vietsub-project",
    "channel_name": "Douyin Channel",
    "channel_url": "",
    "sec_uid": "",
    "platform": "douyin",
    "source_lang": "zh",
    "target_lang": "vi",
    "compilation_min_sec": 600,
    "compilation_keywords": ["合集", "纯享"],
    "whisper": {
        "model": "large-v3",
        "fallback_model": "medium",
        "device": "cuda",
        "compute_type": "float16",
        "beam_size": 3,
        "min_silence_ms": 350,
        "speech_pad_ms": 120,
        "pause_split_sec": 1.05,
    },
    "ducking": {
        "bg_normal": 0.85,
        "bg_duck": 0.08,
        "ramp_ms": 90,
        "pad_before": 0.10,
        "pad_after": 0.12,
    },
    "karaoke": {
        "atempo_max": 1.48,
        "gblur_sigma": 24,
        "mask_brightness": -0.08,
        "mask_fill": 248,
        "mask_feather": 12,
        "font_name": "Arial",
        "secondary_bgr": "&H00FFFFFF",
        "outline_bgr": "&H00000000",
        "back_bgr": "&H96000000",
        "chunk_min_words": 4,
        "chunk_max_words": 7,
    },
    "render": {
        "sample_rate": 48000,
        "video_codec": "h264_nvenc",
        "nvenc_preset": "p4",
        "nvenc_cq": 21,
        "cpu_fallback_codec": "libx264",
        "cpu_preset": "veryfast",
        "cpu_crf": 20,
        "audio_bitrate": "192k",
        "max_duration_diff_sec": 0.6,
    },
    "default_role": "dan_chuyen",
    "roles": {
        "dan_chuyen": {
            "label": "Dẫn Chuyện",
            "description": "Lời dẫn chuyện mặc định",
            "f0_range": [150, 999],
            "voice": "vi-VN-HoaiMyNeural",
            "rate": "+2%",
            "pitch": "+0Hz",
            "style": "DanChuyen",
            "color_bgr": "&H0078F0FF",
        }
    },
    "paths": {
        "ffmpeg": "",
        "ffprobe": "",
        "cuda_torch_lib": "",
        "mediacrawler_dir": "",
        "fallback_dl_py": "",
        "fallback_dl_script": "",
    },
}


def deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Gộp đệ quy dict cấu hình, giữ nguyên giá trị mặc định cho khóa bị thiếu."""
    out = deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = deepcopy(v)
    return out


def extract_sec_uid(channel_url: str) -> str:
    """Tách sec_uid từ URL trang cá nhân Douyin nếu có."""
    url = (channel_url or "").strip()
    if not url:
        return ""
    m = re.search(r"/user/([A-Za-z0-9_.-]+)", url)
    if m:
        return m.group(1)
    m = re.search(r"sec_uid=([A-Za-z0-9_.-]+)", url)
    return m.group(1) if m else ""


def resolve_project_dir(project_dir: Optional[str | Path] = None) -> Path:
    """Xác định thư mục dự án theo thứ tự ưu tiên: CLI -> ENV -> CWD -> cha của scripts/ -> WORK_ROOT."""
    if project_dir:
        p = Path(project_dir).expanduser().resolve()
        if p.exists():
            return p
        raise FileNotFoundError(f"Thư mục dự án không tồn tại: {p}")

    env_dir = os.environ.get("VIETSUB_PROJECT_DIR", "").strip()
    if env_dir:
        p = Path(env_dir).expanduser().resolve()
        if (p / "project.json").exists() or p.exists():
            return p

    cwd = Path.cwd().resolve()
    if (cwd / "project.json").exists():
        return cwd

    script_parent = Path(__file__).resolve().parent.parent
    if (script_parent / "project.json").exists():
        return script_parent

    work_root = os.environ.get("WORK_ROOT", "").strip()
    if work_root:
        wr = Path(work_root).expanduser().resolve()
        if (wr / "project.json").exists():
            return wr

    return cwd


def _ancestor_dirs(start: Path, max_depth: int = 4) -> List[Path]:
    dirs: List[Path] = []
    cur = start.resolve()
    for _ in range(max_depth + 1):
        dirs.append(cur)
        if cur.parent == cur:
            break
        cur = cur.parent
    return dirs


def _search_roots(project_dir: Path) -> List[Path]:
    roots: List[Path] = []
    seen = set()
    candidates: List[Path] = list(_ancestor_dirs(project_dir, max_depth=4))
    work_root = os.environ.get("WORK_ROOT", "").strip()
    if work_root:
        candidates.append(Path(work_root).expanduser())
    home = Path.home()
    candidates.extend([home / "Downloads" / "MUSE", home])
    for r in candidates:
        try:
            rp = r.resolve()
        except Exception:
            rp = r
        key = str(rp).lower()
        if key not in seen and rp.exists():
            seen.add(key)
            roots.append(rp)
    return roots


def find_binary(
    name: str,
    env_var: str,
    config_path: str = "",
    project_dir: Optional[Path] = None,
) -> str:
    """Tìm binary theo thứ tự: ENV -> project.json -> shutil.which -> thư mục công cụ tương đối/hệ thống."""
    env_val = os.environ.get(env_var, "").strip()
    if env_val:
        ep = Path(env_val).expanduser()
        if ep.is_file():
            return str(ep)
        which_env = shutil.which(env_val)
        if which_env:
            return which_env

    if config_path:
        cp = Path(config_path).expanduser()
        if cp.is_file():
            return str(cp)

    found = shutil.which(name)
    if found:
        return found

    exe_name = f"{name}.exe" if os.name == "nt" and not name.endswith(".exe") else name
    candidate_subpaths = [
        Path("MUSE_tool") / exe_name,
        Path("tools") / "ffmpeg" / "bin" / exe_name,
        Path("bin") / exe_name,
    ]
    base_dir = project_dir or Path.cwd()
    for root in _search_roots(base_dir):
        for sub in candidate_subpaths:
            cand = root / sub
            if cand.is_file():
                return str(cand)

    sys_cand = Path(sys.prefix) / "Library" / "bin" / exe_name
    if sys_cand.is_file():
        return str(sys_cand)

    return name


def find_torch_lib_dirs(config_path: str = "", project_dir: Optional[Path] = None) -> List[Path]:
    """Dò thư mục chứa CUDA DLL (torch/lib hoặc nvidia/*/bin) cho faster_whisper."""
    candidates: List[Path] = []
    for env_key in ("CUDA_TORCH_LIB", "TORCH_LIB"):
        val = os.environ.get(env_key, "").strip()
        if val:
            candidates.append(Path(val).expanduser())

    if config_path:
        candidates.append(Path(config_path).expanduser())

    spec = importlib.util.find_spec("torch")
    if spec and spec.origin:
        candidates.append(Path(spec.origin).resolve().parent / "lib")

    sp_dirs: List[Path] = []
    try:
        sp_dirs.extend(Path(p) for p in site.getsitepackages())
    except Exception:
        pass
    try:
        usp = site.getusersitepackages()
        if usp:
            sp_dirs.append(Path(usp))
    except Exception:
        pass
    sp_dirs.append(Path(sys.prefix) / "Lib" / "site-packages")

    for sp in sp_dirs:
        candidates.append(sp / "torch" / "lib")
        nv_dir = sp / "nvidia"
        if nv_dir.is_dir():
            candidates.extend(nv_dir.glob("*/bin"))

    base_dir = project_dir or Path.cwd()
    for root in _search_roots(base_dir):
        for venv_name in (".venv", "venv"):
            candidates.append(root / venv_name / "Lib" / "site-packages" / "torch" / "lib")
            candidates.append(root / "tools" / "g-omnivoice" / venv_name / "Lib" / "site-packages" / "torch" / "lib")

    valid: List[Path] = []
    seen = set()
    for d in candidates:
        try:
            rd = d.resolve()
        except Exception:
            continue
        key = str(rd).lower()
        if key not in seen and rd.is_dir():
            seen.add(key)
            valid.append(rd)
    return valid


def setup_cuda_dll_paths(cfg: Dict[str, Any]) -> List[Path]:
    """Nạp CUDA DLL paths vào PATH và os.add_dll_directory trước khi import faster_whisper."""
    proj_dir = Path(cfg["project_dir"])
    cfg_torch = (cfg.get("paths") or {}).get("cuda_torch_lib", "")
    dirs = find_torch_lib_dirs(cfg_torch, project_dir=proj_dir)
    for d in dirs:
        ds = str(d)
        cur_path = os.environ.get("PATH", "")
        if ds not in cur_path.split(os.pathsep):
            os.environ["PATH"] = ds + os.pathsep + cur_path
        if hasattr(os, "add_dll_directory"):
            try:
                os.add_dll_directory(ds)
            except OSError:
                pass
    return dirs


def find_mediacrawler_python(mc_dir: Optional[Path]) -> Optional[Path]:
    """Trả về đường dẫn Python trong .venv của MediaCrawler nếu đã được cài đặt."""
    if not mc_dir or not mc_dir.is_dir():
        return None
    candidates = [
        mc_dir / ".venv" / "Scripts" / "python.exe",
        mc_dir / ".venv" / "bin" / "python",
        mc_dir / ".venv" / "bin" / "python3",
    ]
    for cand in candidates:
        if cand.is_file():
            return cand.resolve()
    return None


def find_mediacrawler_dir(config_path: str = "", project_dir: Optional[Path] = None) -> Optional[Path]:
    """Tìm MediaCrawler theo ưu tiên: ENV -> project.json -> skill vendor -> <root>/vendor/MediaCrawler -> <root>/MediaCrawler.
    Nếu có nhiều bản cùng tồn tại, ưu tiên bản đã có sẵn .venv.
    """
    for explicit in (os.environ.get("MEDIACRAWLER_DIR", "").strip(), (config_path or "").strip()):
        if explicit:
            ep = Path(explicit).expanduser()
            if ep.is_dir() and (ep / "media_platform").is_dir():
                return ep.resolve()

    candidates: List[Path] = [
        Path.home() / ".gemini" / "config" / "skills" / "vietsub-video-trung" / "vendor" / "MediaCrawler",
    ]
    base_dir = project_dir or Path.cwd()
    roots = _search_roots(base_dir)
    for anc in _ancestor_dirs(Path(__file__).resolve().parent, max_depth=4):
        if anc not in roots:
            roots.append(anc)

    for root in roots:
        candidates.append(root / "vendor" / "MediaCrawler")
    for root in roots:
        candidates.append(root / "MediaCrawler")

    valid_dirs: List[Path] = []
    seen = set()
    for c in candidates:
        if c.is_dir() and (c / "media_platform").is_dir():
            rc = c.resolve()
            key = str(rc).lower()
            if key not in seen:
                seen.add(key)
                valid_dirs.append(rc)

    for vd in valid_dirs:
        if find_mediacrawler_python(vd) is not None:
            return vd

    return valid_dirs[0] if valid_dirs else None


def load_project_config(project_dir: Optional[str | Path] = None) -> Dict[str, Any]:
    """Đọc project.json từ thư mục dự án, hợp nhất với DEFAULT_CONFIG và giải quyết đường dẫn."""
    pdir = resolve_project_dir(project_dir)
    cfg_file = pdir / "project.json"
    if not cfg_file.exists():
        raise FileNotFoundError(
            f"Không tìm thấy project.json tại {pdir}. "
            "Hãy chạy init_project.py trước hoặc truyền --project-dir."
        )

    raw_cfg = json.loads(cfg_file.read_text(encoding="utf-8"))
    cfg = deep_merge(DEFAULT_CONFIG, raw_cfg)
    if not cfg.get("sec_uid") and cfg.get("channel_url"):
        cfg["sec_uid"] = extract_sec_uid(cfg["channel_url"])
    if not cfg.get("channel_url") and cfg.get("sec_uid"):
        cfg["channel_url"] = f"https://www.douyin.com/user/{cfg['sec_uid']}"

    cfg["project_dir"] = str(pdir)
    cfg["dirs"] = {
        "raw": str(pdir / "raw"),
        "transcripts": str(pdir / "transcripts"),
        "translations": str(pdir / "translations"),
        "output": str(pdir / "output"),
        "tmp": str(pdir / "_tmp"),
        "scripts": str(pdir / "scripts"),
    }

    paths_cfg = cfg.get("paths") or {}
    mc_dir = find_mediacrawler_dir(paths_cfg.get("mediacrawler_dir", ""), pdir)
    mc_py = find_mediacrawler_python(mc_dir)
    cfg["tools"] = {
        "ffmpeg": find_binary("ffmpeg", "FFMPEG_BIN", paths_cfg.get("ffmpeg", ""), pdir),
        "ffprobe": find_binary("ffprobe", "FFPROBE_BIN", paths_cfg.get("ffprobe", ""), pdir),
        "mediacrawler_dir": str(mc_dir or ""),
        "mediacrawler_python": str(mc_py or ""),
        "fallback_dl_py": os.environ.get("DOUYIN_FALLBACK_PY", "").strip()
        or paths_cfg.get("fallback_dl_py", "").strip(),
        "fallback_dl_script": os.environ.get("DOUYIN_FALLBACK_SCRIPT", "").strip()
        or paths_cfg.get("fallback_dl_script", "").strip(),
    }
    return cfg


def add_project_dir_arg(parser: argparse.ArgumentParser) -> None:
    """Thêm tham số --project-dir dùng chung cho mọi script CLI."""
    parser.add_argument(
        "--project-dir",
        type=str,
        default="",
        help="Đường dẫn thư mục dự án chứa project.json (mặc định: VIETSUB_PROJECT_DIR hoặc thư mục hiện tại)",
    )


def sanitize_stem(stem: str, ep_key: str, max_len: int = 70) -> str:
    """Làm sạch tên file xuất để hợp lệ trên Windows/Linux và không quá dài."""
    clean = re.sub(r'[<>:"/\\|?*\r\n\t]+', "_", (stem or "").strip())
    clean = re.sub(r"[\s_]+", "_", clean).strip("._")
    if not clean:
        clean = ep_key
    if len(clean) > max_len:
        clean = clean[:max_len].rstrip("_")
    return clean


def fmt_srt_ts(sec: float) -> str:
    """Định dạng timestamp HH:MM:SS,mmm cho SRT."""
    sec = max(0.0, float(sec))
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    ms = int(round((sec - int(sec)) * 1000))
    if ms >= 1000:
        ms = 999
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def probe_media(path: Path, ffprobe_bin: str = "ffprobe") -> Dict[str, Any]:
    """Chạy ffprobe lấy streams + format JSON."""
    res = subprocess.run(
        [
            ffprobe_bin,
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        timeout=60,
    )
    return json.loads(res.stdout or "{}")


def probe_video_basic(
    path: Path, ffprobe_bin: str = "ffprobe", min_bytes: int = 50_000
) -> Optional[Tuple[int, int, float]]:
    """Đọc nhanh (width, height, duration_sec) từ video, trả None nếu file lỗi/thiếu."""
    if not path.exists() or path.stat().st_size < min_bytes:
        return None
    try:
        info = probe_media(path, ffprobe_bin=ffprobe_bin)
        streams = [s for s in (info.get("streams") or []) if s.get("codec_type") == "video"]
        fmt = info.get("format") or {}
        if not streams:
            return None
        w = int(streams[0].get("width", 0) or 0)
        h = int(streams[0].get("height", 0) or 0)
        dur = float(fmt.get("duration", 0) or 0.0)
        if w <= 0 or h <= 0 or dur <= 0.1:
            return None
        return w, h, round(dur, 3)
    except Exception:
        return None
