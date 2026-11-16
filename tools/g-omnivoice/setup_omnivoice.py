# -*- coding: utf-8 -*-
r"""Bộ cài đặt & kiểm tra sức khỏe đa máy (Windows / macOS / Linux) cho G-OmniVoice Studio.

Ví dụ:
  python setup_omnivoice.py               # Cài đủ 2 .venv (3.12), tải toàn bộ model, đồng bộ skill & --doctor
  python setup_omnivoice.py --minimal     # Chỉ tải model tiếng Việt (g-omnivoice) + ClearerVoice 48kHz
  python setup_omnivoice.py --skip-models # Chỉ cài 2 .venv + skill (model sẽ tự tải khi chạy lần đầu)
  python setup_omnivoice.py --doctor      # Kiểm tra sức khỏe toàn hệ thống (chỉ đọc)
  python setup_omnivoice.py --smoke-test  # Chạy thử tạo 1 câu WAV ngắn để xác nhận máy sẵn sàng
"""
from __future__ import annotations

import argparse
import io
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

if hasattr(sys.stdout, "buffer") and getattr(sys.stdout, "encoding", "").lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "buffer") and getattr(sys.stderr, "encoding", "").lower() != "utf-8":
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
ENHANCE_DIR = HERE.parent / "voice-enhance"
VOICES_DIR = HERE / "voices"

GEMINI_CFG_DIR = Path.home() / ".gemini" / "config"
SKILL_SRC = REPO_ROOT / "skills" / "g-omnivoice"
SKILL_DST = GEMINI_CFG_DIR / "skills" / "g-omnivoice"
AGENTS_MD_PATH = GEMINI_CFG_DIR / "AGENTS.md"

OMNI_TRIGGER_LINE = (
    '| g-omnivoice | "g-omnivoice", "omnivoice", "clone giong", "tao voice", "thu vien giong" |'
)

TORCH_CUDA_INDEX = "https://download.pytorch.org/whl/cu128"


def _venv_python(tool_dir: Path) -> Path:
    if os.name == "nt":
        return tool_dir / ".venv" / "Scripts" / "python.exe"
    return tool_dir / ".venv" / "bin" / "python"


def _detect_nvidia_gpu() -> Tuple[bool, str]:
    smi = shutil.which("nvidia-smi")
    if not smi:
        return False, "Không phát hiện nvidia-smi"
    try:
        res = subprocess.run(
            [smi, "--query-gpu=name,memory.total", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if res.returncode == 0 and (res.stdout or "").strip():
            return True, "; ".join(l.strip() for l in res.stdout.strip().splitlines())
    except Exception:
        pass
    return False, "nvidia-smi không trả về GPU"


def _find_uv() -> Optional[str]:
    uv_bin = shutil.which("uv")
    if uv_bin:
        return uv_bin
    for cand in (
        Path.home() / ".local" / "bin" / ("uv.exe" if os.name == "nt" else "uv"),
        Path.home() / ".cargo" / "bin" / ("uv.exe" if os.name == "nt" else "uv"),
    ):
        if cand.is_file():
            return str(cand)
    return None


def _ensure_uv() -> Optional[str]:
    uv_bin = _find_uv()
    if uv_bin:
        return uv_bin
    print(">>> Chưa thấy `uv`, thử cài `uv` qua pip để tự quản lý Python 3.12...", flush=True)
    for extra in ([], ["--user"]):
        res = subprocess.run(
            [sys.executable, "-m", "pip", "install", *extra, "uv"],
            check=False,
        )
        if res.returncode == 0:
            uv_bin = _find_uv()
            if uv_bin:
                return uv_bin
    return None


def _find_python312_fallback() -> List[str]:
    if os.name == "nt" and shutil.which("py"):
        chk = subprocess.run(["py", "-3.12", "--version"], capture_output=True, text=True, check=False)
        if chk.returncode == 0:
            return ["py", "-3.12"]
    for cand in ("python3.12", "python3", "python"):
        w = shutil.which(cand)
        if w:
            return [w]
    return [sys.executable]


def _create_venv_and_install(
    tool_dir: Path,
    pypi_pkgs: List[str],
    has_gpu: bool,
    uv_bin: Optional[str],
    label: str,
) -> Path:
    venv_dir = tool_dir / ".venv"
    venv_py = _venv_python(tool_dir)
    print(f"\n>>> [{label}] Cài môi trường Python 3.12 tại: {venv_dir}", flush=True)

    if uv_bin:
        if not venv_py.is_file():
            subprocess.run([uv_bin, "venv", str(venv_dir), "--python", "3.12"], check=True)
        torch_cmd = [uv_bin, "pip", "install", "--python", str(venv_py), "torch", "torchaudio"]
        if has_gpu and platform.system() != "Darwin":
            torch_cmd += ["--index-url", TORCH_CUDA_INDEX]
        print(f"  [1/2] Cài PyTorch ({'CUDA cu128' if has_gpu and platform.system() != 'Darwin' else 'standard'})...", flush=True)
        subprocess.run(torch_cmd, check=True)

        pkg_cmd = [uv_bin, "pip", "install", "--python", str(venv_py), *pypi_pkgs]
        print(f"  [2/2] Cài gói PyPI: {', '.join(pypi_pkgs)}", flush=True)
        subprocess.run(pkg_cmd, check=True)
        return venv_py

    # Fallback venv + pip nếu không có uv
    if not venv_py.is_file():
        py_cmd = _find_python312_fallback()
        subprocess.run([*py_cmd, "-m", "venv", str(venv_dir)], check=True)
    subprocess.run([str(venv_py), "-m", "pip", "install", "--upgrade", "pip"], check=True)
    torch_cmd = [str(venv_py), "-m", "pip", "install", "torch", "torchaudio"]
    if has_gpu and platform.system() != "Darwin":
        torch_cmd += ["--index-url", TORCH_CUDA_INDEX]
    print(f"  [1/2] Cài PyTorch ({'CUDA cu128' if has_gpu and platform.system() != 'Darwin' else 'standard'})...", flush=True)
    subprocess.run(torch_cmd, check=True)
    print(f"  [2/2] Cài gói PyPI: {', '.join(pypi_pkgs)}", flush=True)
    subprocess.run([str(venv_py), "-m", "pip", "install", *pypi_pkgs], check=True)
    return venv_py


def install_venvs() -> Tuple[Path, Path]:
    has_gpu, gpu_desc = _detect_nvidia_gpu()
    print(f">>> Phần cứng GPU: {gpu_desc}", flush=True)
    uv_bin = _ensure_uv()

    ort_pkg = "onnxruntime-gpu" if (has_gpu and platform.system() != "Darwin") else "onnxruntime"
    omni_pkgs = [
        "omnivoice==0.2.1",
        "soundfile>=0.12.1",
        "numpy>=2.0.0",
        "huggingface_hub>=0.25.0",
        "accelerate>=1.0.0",
        "audio-separator>=0.30.0",
        ort_pkg,
    ]
    enhance_pkgs = [
        "clearvoice==0.1.2",
        "numpy==1.26.4",
        "soundfile==0.12.1",
        "scipy>=1.11.0,<1.18.0",
        "huggingface_hub>=0.25.0",
    ]

    omni_py = _create_venv_and_install(HERE, omni_pkgs, has_gpu, uv_bin, "g-omnivoice")
    enh_py = _create_venv_and_install(ENHANCE_DIR, enhance_pkgs, has_gpu, uv_bin, "voice-enhance")
    return omni_py, enh_py


def _hf_download_via_python(py_bin: Path, repo_id: str, local_dir: Path) -> None:
    local_dir.mkdir(parents=True, exist_ok=True)
    code = (
        "from huggingface_hub import snapshot_download; "
        f"snapshot_download(repo_id={repo_id!r}, local_dir={str(local_dir)!r})"
    )
    subprocess.run([str(py_bin), "-c", code], check=True)


def _model_vi_ready(model_dir: Path) -> bool:
    return (model_dir / "model.safetensors").is_file() and (model_dir / "audio_tokenizer" / "model.safetensors").is_file()


def _se_ready(ckpt_dir: Path) -> bool:
    return (ckpt_dir / "last_best_checkpoint.pt").is_file()


def _sr_ready(ckpt_dir: Path) -> bool:
    return (ckpt_dir / "last_best_checkpoint_g.pt").is_file() and (ckpt_dir / "do_03925000").is_file()


def _sep_ready(sep_dir: Path) -> bool:
    return (
        (sep_dir / "model_bs_roformer_ep_317_sdr_12.9755.ckpt").is_file()
        and (sep_dir / "denoise_mel_band_roformer_aufr33_aggr_sdr_27.9768.ckpt").is_file()
    )


def download_models(minimal: bool = False) -> None:
    omni_py = _venv_python(HERE) if _venv_python(HERE).is_file() else Path(sys.executable)

    # 1. G-OmniVoice tiếng Việt (~3.1 GB)
    env_vi = os.environ.get("OMNIVOICE_MODEL_DIR", "").strip()
    vi_dir = Path(env_vi).expanduser().resolve() if env_vi else (HERE / "model")
    if _model_vi_ready(vi_dir):
        print(f"[OK] Model G-OmniVoice (vi) đã có sẵn: {vi_dir}", flush=True)
    else:
        print(f">>> Tải model G-OmniVoice (g-group-ai-lab/g-omnivoice) -> {vi_dir}", flush=True)
        _hf_download_via_python(omni_py, "g-group-ai-lab/g-omnivoice", vi_dir)

    # 2. ClearerVoice SE & SR 48kHz (~2.3 GB)
    env_enh = os.environ.get("VOICE_ENHANCE_DIR", "").strip()
    enh_root = Path(env_enh).expanduser().resolve() if env_enh else ENHANCE_DIR
    se_dir = enh_root / "checkpoints" / "MossFormer2_SE_48K"
    sr_dir = enh_root / "checkpoints" / "MossFormer2_SR_48K"
    if _se_ready(se_dir):
        print(f"[OK] ClearerVoice MossFormer2_SE_48K đã có: {se_dir}", flush=True)
    else:
        print(f">>> Tải ClearerVoice MossFormer2_SE_48K -> {se_dir}", flush=True)
        _hf_download_via_python(omni_py, "alibabasglab/MossFormer2_SE_48K", se_dir)

    if _sr_ready(sr_dir):
        print(f"[OK] ClearerVoice MossFormer2_SR_48K đã có: {sr_dir}", flush=True)
    else:
        print(f">>> Tải ClearerVoice MossFormer2_SR_48K -> {sr_dir}", flush=True)
        _hf_download_via_python(omni_py, "alibabasglab/MossFormer2_SR_48K", sr_dir)

    if minimal:
        print("[INFO] Đã bỏ qua model-goc (EN) và sep_models (tách nhạc) do bật --minimal.", flush=True)
        return

    # 3. OmniVoice gốc đa ngôn ngữ / tiếng Anh (~3.1 GB)
    env_en = os.environ.get("OMNIVOICE_MODEL_EN_DIR", "").strip()
    en_dir = Path(env_en).expanduser().resolve() if env_en else (HERE / "model-goc")
    if _model_vi_ready(en_dir):
        print(f"[OK] Model OmniVoice gốc (en) đã có sẵn: {en_dir}", flush=True)
    else:
        print(f">>> Tải model k2-fsa/OmniVoice -> {en_dir}", flush=True)
        _hf_download_via_python(omni_py, "k2-fsa/OmniVoice", en_dir)

    # 4. Audio-Separator RoFormer weights (~1.5 GB)
    env_sep = os.environ.get("OMNIVOICE_SEP_DIR", "").strip()
    sep_dir = Path(env_sep).expanduser().resolve() if env_sep else (HERE / "sep_models")
    sep_dir.mkdir(parents=True, exist_ok=True)
    if _sep_ready(sep_dir):
        print(f"[OK] sep_models (BS-RoFormer & Mel-RoFormer Denoise) đã có: {sep_dir}", flush=True)
    else:
        print(f">>> Tải model tách nhạc RoFormer -> {sep_dir}", flush=True)
        sep_code = (
            "from audio_separator.separator import Separator; "
            f"s = Separator(model_file_dir={str(sep_dir)!r}); "
            "s.load_model('model_bs_roformer_ep_317_sdr_12.9755.ckpt'); "
            "s.load_model('denoise_mel_band_roformer_aufr33_aggr_sdr_27.9768.ckpt')"
        )
        subprocess.run([str(omni_py), "-c", sep_code], check=True)


def sync_omnivoice_skill() -> str:
    """Đồng bộ skills/g-omnivoice sang ~/.gemini/config/skills/g-omnivoice và cập nhật AGENTS.md."""
    if not SKILL_SRC.is_dir():
        return f"Không thấy {SKILL_SRC} (bỏ qua đồng bộ skill)."

    SKILL_DST.mkdir(parents=True, exist_ok=True)
    copied = 0
    for root, dirs, files in os.walk(SKILL_SRC):
        rel = Path(root).relative_to(SKILL_SRC)
        dirs[:] = [d for d in dirs if d not in {"__pycache__", ".pytest_cache"}]
        tdir = SKILL_DST / rel
        tdir.mkdir(parents=True, exist_ok=True)
        for fn in files:
            if fn.endswith((".pyc", ".pyo")):
                continue
            shutil.copy2(Path(root) / fn, tdir / fn)
            copied += 1

    GEMINI_CFG_DIR.mkdir(parents=True, exist_ok=True)
    if not AGENTS_MD_PATH.exists():
        AGENTS_MD_PATH.write_text(
            "# Global Workflow Rules\n\n## Skills & Trigger Keywords\n\n"
            "| Skill | Trigger when user says |\n|-------|------------------------|\n"
            f"{OMNI_TRIGGER_LINE}\n",
            encoding="utf-8",
        )
        return f"Đã chép {copied} file skill -> {SKILL_DST} và tạo {AGENTS_MD_PATH}."

    text = AGENTS_MD_PATH.read_text(encoding="utf-8")
    if "| g-omnivoice |" in text:
        return f"Đã chép {copied} file skill -> {SKILL_DST} (AGENTS.md đã có trigger g-omnivoice)."

    lines = text.splitlines()
    inserted = False
    new_lines: List[str] = []
    for i, line in enumerate(lines):
        new_lines.append(line)
        if not inserted and line.strip().startswith("| vietsub-video-trung |"):
            new_lines.append(OMNI_TRIGGER_LINE)
            inserted = True
    if not inserted:
        table_idx = next((i for i, l in enumerate(new_lines) if l.strip().startswith("| Skill |")), -1)
        if table_idx >= 0:
            j = table_idx + 2
            while j < len(new_lines) and new_lines[j].strip().startswith("|"):
                j += 1
            new_lines.insert(j, OMNI_TRIGGER_LINE)
        else:
            new_lines.extend(["", "## Skills & Trigger Keywords", "", "| Skill | Trigger when user says |", "|-------|------------------------|", OMNI_TRIGGER_LINE])
    trailing = "\n" if text.endswith("\n") else ""
    AGENTS_MD_PATH.write_text("\n".join(new_lines) + trailing, encoding="utf-8")
    return f"Đã chép {copied} file skill -> {SKILL_DST} và thêm trigger vào {AGENTS_MD_PATH}."


def _count_valid_voices() -> Tuple[int, List[str]]:
    if not VOICES_DIR.is_dir():
        return 0, []
    valid, bad = 0, []
    for d in sorted(VOICES_DIR.iterdir()):
        if not d.is_dir():
            continue
        if (d / "ref.wav").is_file() and (d / "ref.txt").is_file() and (d / "meta.json").is_file():
            valid += 1
        else:
            bad.append(d.name)
    return valid, bad


def _check_venv_import(py_bin: Path, stmt: str) -> Tuple[bool, str]:
    if not py_bin.is_file():
        return False, "Chưa có .venv"
    res = subprocess.run([str(py_bin), "-c", stmt], capture_output=True, text=True, check=False)
    if res.returncode == 0:
        return True, (res.stdout or "OK").strip()
    return False, (res.stderr or res.stdout or "Lỗi import").strip().splitlines()[-1]


def run_doctor() -> int:
    print("=== KIỂM TRA SỨC KHỎE G-OMNIVOICE (DOCTOR) ===")
    issues = 0

    py_ok = sys.version_info >= (3, 10)
    print(f"[{'OK' if py_ok else 'FAIL'}] Python hệ thống: {sys.version.split()[0]} ({sys.executable})")
    if not py_ok:
        issues += 1

    uv_bin = _find_uv()
    print(f"[{'OK' if uv_bin else 'INFO'}] uv: {uv_bin or 'Chưa cài (sẽ tự cài hoặc dùng venv+pip)'}")

    ff = os.environ.get("FFMPEG_BIN", "").strip() or shutil.which("ffmpeg")
    fp = os.environ.get("FFPROBE_BIN", "").strip() or shutil.which("ffprobe")
    print(f"[{'OK' if ff else 'FAIL'}] ffmpeg: {ff or 'Không tìm thấy'}")
    print(f"[{'OK' if fp else 'WARN'}] ffprobe: {fp or 'Không tìm thấy'}")
    if not ff:
        issues += 1

    has_gpu, gpu_desc = _detect_nvidia_gpu()
    print(f"[{'OK' if has_gpu else 'WARN'}] GPU NVIDIA: {gpu_desc}")

    omni_py = _venv_python(HERE)
    ok_omni, msg_omni = _check_venv_import(
        omni_py,
        "import torch, omnivoice, soundfile; print(f'torch={torch.__version__}, cuda={torch.cuda.is_available()}')",
    )
    print(f"[{'OK' if ok_omni else 'WARN'}] g-omnivoice .venv: {omni_py} ({msg_omni})")

    enh_py = _venv_python(ENHANCE_DIR)
    ok_enh, msg_enh = _check_venv_import(
        enh_py,
        "import numpy, clearvoice; print(f'numpy={numpy.__version__}, clearvoice=OK')",
    )
    print(f"[{'OK' if ok_enh else 'WARN'}] voice-enhance .venv: {enh_py} ({msg_enh})")

    valid_v, bad_v = _count_valid_voices()
    print(f"[{'OK' if valid_v >= 20 and not bad_v else 'WARN'}] Bộ giọng clone trong voices/: {valid_v} hợp lệ" + (f" (thiếu file ở: {bad_v})" if bad_v else ""))
    if valid_v == 0:
        issues += 1

    env_vi = os.environ.get("OMNIVOICE_MODEL_DIR", "").strip()
    vi_dir = Path(env_vi).expanduser().resolve() if env_vi else (HERE / "model")
    env_en = os.environ.get("OMNIVOICE_MODEL_EN_DIR", "").strip()
    en_dir = Path(env_en).expanduser().resolve() if env_en else (HERE / "model-goc")
    env_enh = os.environ.get("VOICE_ENHANCE_DIR", "").strip()
    enh_root = Path(env_enh).expanduser().resolve() if env_enh else ENHANCE_DIR
    env_sep = os.environ.get("OMNIVOICE_SEP_DIR", "").strip()
    sep_dir = Path(env_sep).expanduser().resolve() if env_sep else (HERE / "sep_models")

    print(f"[{'OK' if _model_vi_ready(vi_dir) else 'WARN'}] Model G-OmniVoice (vi): {vi_dir}")
    print(f"[{'OK' if _model_vi_ready(en_dir) else 'INFO'}] Model OmniVoice gốc (en): {en_dir}")
    print(f"[{'OK' if _se_ready(enh_root / 'checkpoints' / 'MossFormer2_SE_48K') else 'WARN'}] ClearerVoice SE_48K: {enh_root / 'checkpoints' / 'MossFormer2_SE_48K'}")
    print(f"[{'OK' if _sr_ready(enh_root / 'checkpoints' / 'MossFormer2_SR_48K') else 'WARN'}] ClearerVoice SR_48K: {enh_root / 'checkpoints' / 'MossFormer2_SR_48K'}")
    print(f"[{'OK' if _sep_ready(sep_dir) else 'INFO'}] RoFormer sep_models: {sep_dir}")

    skill_ok = (SKILL_DST / "SKILL.md").is_file()
    print(f"[{'OK' if skill_ok else 'INFO'}] Skill cục bộ: {SKILL_DST} ({'đã đồng bộ' if skill_ok else 'chưa đồng bộ'})")
    print(f"=== KẾT QUẢ DOCTOR: {issues} lỗi nghiêm trọng ===")
    return 1 if issues > 0 else 0


def run_smoke_test() -> int:
    omni_py = _venv_python(HERE)
    if not omni_py.is_file():
        omni_py = Path(sys.executable)

    enh_root = Path(os.environ.get("VOICE_ENHANCE_DIR") or ENHANCE_DIR).expanduser().resolve()
    can_enhance = _venv_python(enh_root).is_file() and _se_ready(enh_root / "checkpoints" / "MossFormer2_SE_48K")

    with tempfile.TemporaryDirectory() as tmp_dir:
        out_wav = Path(tmp_dir) / "smoke_test.wav"
        cmd = [
            str(omni_py),
            str(HERE / "clone.py"),
            "--voice",
            "dinh-soan",
            "--text",
            "Xin chào, hệ thống G Omni Voice trên máy mới đã sẵn sàng tạo giọng nói.",
            "--out",
            str(out_wav),
        ]
        if can_enhance:
            cmd.append("--enhance")
        print(f">>> Chạy smoke-test: {' '.join(cmd)}", flush=True)
        subprocess.run(cmd, check=True)
        dur = float(
            subprocess.check_output(
                [str(omni_py), "-c", f"import soundfile as sf; info=sf.info({str(out_wav)!r}); print(f'{{info.duration:.3f}}|{{info.samplerate}}')"],
                text=True,
            )
            .strip()
            .split("|")[0]
        )
        print(f"[OK] Smoke-test PASS: duration={dur:.2f}s (enhance={can_enhance})", flush=True)
        if dur <= 1.0:
            raise RuntimeError(f"Smoke-test WAV quá ngắn ({dur:.2f}s <= 1.0s)")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Cài đặt đa máy cho G-OmniVoice Studio + ClearerVoice 48kHz.")
    parser.add_argument("--minimal", action="store_true", help="Chỉ tải model tiếng Việt (g-omnivoice) + ClearerVoice 48kHz")
    parser.add_argument("--skip-models", action="store_true", help="Không tải model weights (tải tự động khi dùng)")
    parser.add_argument("--skip-pip", action="store_true", help="Bỏ qua cài đặt 2 .venv Python 3.12")
    parser.add_argument("--skill-only", action="store_true", help="Chỉ đồng bộ skill g-omnivoice & trigger AGENTS.md")
    parser.add_argument("--doctor", action="store_true", help="Kiểm tra sức khỏe môi trường (chỉ đọc)")
    parser.add_argument("--smoke-test", action="store_true", help="Chạy thử tạo 1 câu WAV ngắn xác nhận hoạt động")
    args = parser.parse_args()

    if args.doctor and not (args.skill_only or args.smoke_test):
        sys.exit(run_doctor())

    if args.skill_only:
        print(sync_omnivoice_skill(), flush=True)
        return

    if args.smoke_test:
        sys.exit(run_smoke_test())

    print(">>> Bước 1: Đồng bộ Antigravity Skill g-omnivoice...", flush=True)
    print(" ", sync_omnivoice_skill(), flush=True)

    if not args.skip_pip:
        print("\n>>> Bước 2: Tạo 2 .venv tách rời (g-omnivoice & voice-enhance)...", flush=True)
        install_venvs()

    if not args.skip_models:
        print("\n>>> Bước 3: Kiểm tra / tải model weights từ HuggingFace...", flush=True)
        download_models(minimal=args.minimal)

    print()
    rc = run_doctor()
    sys.exit(rc)


if __name__ == "__main__":
    main()
