# -*- coding: utf-8 -*-
r"""Bộ cài đặt & kiểm tra sức khỏe đa máy (Windows / macOS / Linux) cho Vietsub-video-Trung.

Ví dụ:
  python setup_machine.py                 # Cài skill + .venv MediaCrawler + thư viện pipeline + --doctor
  python setup_machine.py --skill-only    # Chỉ đồng bộ skill, vendor/MediaCrawler, template, rules & AGENTS.md
  python setup_machine.py --doctor        # Kiểm tra môi trường (Python, FFmpeg, Node, Chrome/Edge, MediaCrawler, CUDA)
  python setup_machine.py --login dy      # Mở trình duyệt quét QR đăng nhập Douyin
"""

import argparse
import importlib.util
import io
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "buffer"):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

REPO_ROOT = Path(__file__).resolve().parent
GEMINI_CFG_DIR = Path.home() / ".gemini" / "config"
SKILL_NAME = "vietsub-video-trung"
SKILL_DST = GEMINI_CFG_DIR / "skills" / SKILL_NAME
AGENTS_MD_PATH = GEMINI_CFG_DIR / "AGENTS.md"

TRIGGER_LINE = (
    '| vietsub-video-trung | "vietsub video trung", "vietsub douyin", '
    '"karaoke sub", "long tieng kenh trung", "dich kenh douyin" |'
)
PREV_TRIGGER_ANCHOR = "| video-translation-editing |"

PIPELINE_PACKAGES = [
    "faster-whisper",
    "rapidocr-onnxruntime",
    "edge-tts",
    "numpy",
    "Pillow",
    "yt-dlp",
]

VENDOR_SKIP_ROOT_DIRS = {".venv", "browser_data", "data", "logs"}
VENDOR_SKIP_ANY_DIRS = {".venv", "__pycache__", ".pytest_cache", "node_modules"}
VENDOR_SKIP_EXTS = {".db", ".sqlite", ".sqlite3", ".pyc", ".pyo"}


def _import_config_loader():
    for scripts_dir in (
        REPO_ROOT / "template" / "scripts",
        SKILL_DST / "template" / "scripts",
    ):
        if (scripts_dir / "config_loader.py").is_file():
            if str(scripts_dir) not in sys.path:
                sys.path.insert(0, str(scripts_dir))
            import config_loader  # type: ignore

            return config_loader
    raise FileNotFoundError("Không tìm thấy template/scripts/config_loader.py.")


def _copy_tree_clean(
    src: Path,
    dst: Path,
    skip_any_dirs: Optional[set] = None,
    skip_root_dirs: Optional[set] = None,
    skip_exts: Optional[set] = None,
) -> int:
    """Copy đệ quy cây thư mục từ src sang dst, giữ nguyên thư mục runtime (.venv/browser_data) ở dst."""
    skip_any_dirs = skip_any_dirs or {"__pycache__", ".pytest_cache"}
    skip_root_dirs = skip_root_dirs or set()
    skip_exts = skip_exts or {".pyc", ".pyo"}
    dst.mkdir(parents=True, exist_ok=True)
    count = 0
    for root, dirs, files in os.walk(src):
        rel = Path(root).relative_to(src)
        is_root = rel == Path(".")
        dirs[:] = [
            d
            for d in dirs
            if d not in skip_any_dirs and not (is_root and d in skip_root_dirs)
        ]
        target_dir = dst / rel
        target_dir.mkdir(parents=True, exist_ok=True)
        for fname in files:
            sf = Path(root) / fname
            if sf.suffix.lower() in skip_exts:
                continue
            shutil.copy2(sf, target_dir / fname)
            count += 1
    return count


def _clean_pycache(root: Path) -> None:
    if not root.exists():
        return
    for pc in list(root.rglob("__pycache__")):
        shutil.rmtree(pc, ignore_errors=True)


def update_global_agents_md() -> str:
    """Chèn dòng trigger vietsub-video-trung vào ~/.gemini/config/AGENTS.md nếu chưa có."""
    if not GEMINI_CFG_DIR.exists():
        GEMINI_CFG_DIR.mkdir(parents=True, exist_ok=True)

    if not AGENTS_MD_PATH.exists():
        content = (
            "# Global Workflow Rules\n\n"
            "## Skills & Trigger Keywords\n\n"
            "| Skill | Trigger when user says |\n"
            "|-------|------------------------|\n"
            f"{TRIGGER_LINE}\n"
        )
        AGENTS_MD_PATH.write_text(content, encoding="utf-8")
        return f"Đã tạo mới {AGENTS_MD_PATH} kèm dòng trigger."

    text = AGENTS_MD_PATH.read_text(encoding="utf-8")
    if "| vietsub-video-trung |" in text:
        return f"Đã có sẵn trigger trong {AGENTS_MD_PATH} (giữ nguyên)."

    lines = text.splitlines()
    new_lines: List[str] = []
    inserted = False
    for line in lines:
        new_lines.append(line)
        if not inserted and line.strip().startswith(PREV_TRIGGER_ANCHOR):
            new_lines.append(TRIGGER_LINE)
            inserted = True

    if not inserted:
        # Fallback nếu máy mới chưa có dòng video-translation-editing
        table_idx = -1
        for i, line in enumerate(new_lines):
            if line.strip().startswith("| Skill |") and i + 1 < len(new_lines):
                table_idx = i + 1
                break
        if table_idx >= 0:
            j = table_idx + 1
            while j < len(new_lines) and new_lines[j].strip().startswith("|"):
                j += 1
            new_lines.insert(j, TRIGGER_LINE)
            inserted = True
        else:
            if new_lines and new_lines[-1].strip():
                new_lines.append("")
            new_lines.extend(
                [
                    "## Skills & Trigger Keywords",
                    "",
                    "| Skill | Trigger when user says |",
                    "|-------|------------------------|",
                    TRIGGER_LINE,
                ]
            )

    trailing_nl = "\n" if text.endswith("\n") else ""
    AGENTS_MD_PATH.write_text("\n".join(new_lines) + trailing_nl, encoding="utf-8")
    return f"Đã cập nhật trigger vào {AGENTS_MD_PATH}."


def sync_skill_and_vendor() -> Dict[str, int]:
    """Đồng bộ skill, vendor/MediaCrawler, template, workflows, rules sang ~/.gemini/config/skills/vietsub-video-trung."""
    skill_src = REPO_ROOT / "skills" / SKILL_NAME
    if not skill_src.is_dir():
        raise FileNotFoundError(f"Không tìm thấy thư mục skill nguồn: {skill_src}")

    stats: Dict[str, int] = {}
    stats["skill_files"] = _copy_tree_clean(skill_src, SKILL_DST)

    for sub in ("template", "workflows", "rules"):
        sdir = REPO_ROOT / sub
        if sdir.is_dir():
            stats[sub] = _copy_tree_clean(sdir, SKILL_DST / sub)

    vendor_src = REPO_ROOT / "vendor" / "MediaCrawler"
    if vendor_src.is_dir():
        stats["vendor_MediaCrawler"] = _copy_tree_clean(
            vendor_src,
            SKILL_DST / "vendor" / "MediaCrawler",
            skip_any_dirs=VENDOR_SKIP_ANY_DIRS,
            skip_root_dirs=VENDOR_SKIP_ROOT_DIRS,
            skip_exts=VENDOR_SKIP_EXTS,
        )

    _clean_pycache(SKILL_DST)
    return stats


def _venv_python_for(mc_dir: Path) -> Path:
    if os.name == "nt":
        return mc_dir / ".venv" / "Scripts" / "python.exe"
    return mc_dir / ".venv" / "bin" / "python"


def setup_mediacrawler_venv(mc_dir: Path) -> None:
    """Tạo .venv cho MediaCrawler (ưu tiên uv sync -> fallback venv + pip) và cài playwright chromium."""
    if not (mc_dir / "media_platform").is_dir():
        raise FileNotFoundError(f"Thư mục MediaCrawler không hợp lệ: {mc_dir}")

    print(f"\n>>> Cài đặt môi trường MediaCrawler tại: {mc_dir}", flush=True)
    uv_bin = shutil.which("uv")
    if uv_bin:
        print("  [uv] Đang chạy uv sync...", flush=True)
        subprocess.run([uv_bin, "sync"], cwd=str(mc_dir), check=True)
        mc_py = _venv_python_for(mc_dir)
    else:
        mc_py = _venv_python_for(mc_dir)
        if not mc_py.exists():
            print("  [venv] Đang tạo .venv...", flush=True)
            subprocess.run([sys.executable, "-m", "venv", str(mc_dir / ".venv")], check=True)
        req_file = mc_dir / "requirements.txt"
        print("  [pip] Đang cài requirements.txt + playwright...", flush=True)
        subprocess.run([str(mc_py), "-m", "pip", "install", "--upgrade", "pip"], check=True)
        if req_file.is_file():
            subprocess.run([str(mc_py), "-m", "pip", "install", "-r", str(req_file), "playwright"], check=True)
        else:
            subprocess.run([str(mc_py), "-m", "pip", "install", "playwright", "pyexecjs", "httpx"], check=True)

    print("  [playwright] Đang cài trình duyệt Chromium...", flush=True)
    subprocess.run([str(mc_py), "-m", "playwright", "install", "chromium"], cwd=str(mc_dir), check=True)


def install_pipeline_packages() -> None:
    """Cài các thư viện Python của pipeline vào Python hiện tại."""
    print(f"\n>>> Cài đặt thư viện pipeline vào {sys.executable}: {', '.join(PIPELINE_PACKAGES)}", flush=True)
    subprocess.run([sys.executable, "-m", "pip", "install", *PIPELINE_PACKAGES], check=True)


def detect_browsers() -> List[str]:
    """Dò Chrome/Edge cục bộ trên Windows / macOS / Linux."""
    sys_name = platform.system()
    candidates: List[str] = []
    if sys_name == "Windows":
        candidates = [
            os.path.expandvars(r"%PROGRAMFILES%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%PROGRAMFILES%\Microsoft\Edge\Application\msedge.exe"),
            os.path.expandvars(r"%PROGRAMFILES(X86)%\Microsoft\Edge\Application\msedge.exe"),
        ]
    elif sys_name == "Darwin":
        candidates = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        ]
    else:
        for b in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge"):
            w = shutil.which(b)
            if w:
                candidates.append(w)
        candidates.extend(
            [
                "/usr/bin/google-chrome",
                "/usr/bin/chromium",
                "/usr/bin/chromium-browser",
                "/usr/bin/microsoft-edge",
            ]
        )

    found: List[str] = []
    seen = set()
    for p in candidates:
        if p and os.path.isfile(p) and p.lower() not in seen:
            seen.add(p.lower())
            found.append(p)
    return found


def run_doctor(project_dir: Optional[str] = None) -> int:
    """Kiểm tra sức khỏe hệ thống ở chế độ chỉ đọc (không cài gói, không sửa file)."""
    cl = _import_config_loader()
    pdir = Path(project_dir).expanduser().resolve() if project_dir else REPO_ROOT

    print("=== KIỂM TRA SỨC KHỎE MÔI TRƯỜNG (DOCTOR) ===")
    issues = 0

    # 1. Python
    py_ver = sys.version_info
    py_ok = py_ver >= (3, 10)
    print(f"[{'OK' if py_ok else 'FAIL'}] Python: {py_ver.major}.{py_ver.minor}.{py_ver.micro} ({sys.executable})")
    if not py_ok:
        issues += 1

    # 2. FFmpeg & FFprobe (libass + h264_nvenc / libx264)
    ffmpeg_bin = cl.find_binary("ffmpeg", "FFMPEG_BIN", "", pdir)
    ffprobe_bin = cl.find_binary("ffprobe", "FFPROBE_BIN", "", pdir)
    ff_resolved = shutil.which(ffmpeg_bin) or (ffmpeg_bin if Path(ffmpeg_bin).is_file() else "")
    fp_resolved = shutil.which(ffprobe_bin) or (ffprobe_bin if Path(ffprobe_bin).is_file() else "")

    has_ass = False
    has_nvenc = False
    has_x264 = False
    if ff_resolved:
        f_res = subprocess.run([ff_resolved, "-hide_banner", "-filters"], capture_output=True, text=True, check=False)
        has_ass = bool(re.search(r"(?m)^\s*\S+\s+ass\b", f_res.stdout or ""))
        e_res = subprocess.run([ff_resolved, "-hide_banner", "-encoders"], capture_output=True, text=True, check=False)
        enc_txt = e_res.stdout or ""
        has_nvenc = "h264_nvenc" in enc_txt
        has_x264 = "libx264" in enc_txt
        print(
            f"[{'OK' if has_ass else 'WARN'}] ffmpeg: {ff_resolved} | filter ass={'YES' if has_ass else 'NO'} | "
            f"h264_nvenc={'YES' if has_nvenc else 'NO'}, libx264={'YES' if has_x264 else 'NO'}"
        )
        if not has_ass:
            issues += 1
    else:
        print("[FAIL] ffmpeg: Không tìm thấy (hãy cài FFmpeg có libass hoặc đặt FFMPEG_BIN)")
        issues += 1

    print(f"[{'OK' if fp_resolved else 'FAIL'}] ffprobe: {fp_resolved or 'Không tìm thấy'}")
    if not fp_resolved:
        issues += 1

    # 3. Node.js
    node_bin = shutil.which("node")
    if node_bin:
        n_ver = subprocess.run([node_bin, "--version"], capture_output=True, text=True, check=False).stdout.strip()
        print(f"[OK] node: {n_ver} ({node_bin})")
    else:
        print("[WARN] node: Chưa cài Node.js (cần cho pyexecjs chạy libs/douyin.js trong MediaCrawler)")

    # 4. Chrome / Edge
    browsers = detect_browsers()
    if browsers:
        print(f"[OK] Browser (Chrome/Edge): {browsers[0]} (+{max(0, len(browsers) - 1)} khác)")
    else:
        print("[WARN] Browser: Không tìm thấy Chrome/Edge ở đường dẫn chuẩn")

    # 5. MediaCrawler & .venv
    mc_dir = cl.find_mediacrawler_dir("", pdir)
    if mc_dir:
        mc_py = cl.find_mediacrawler_python(mc_dir)
        dy_profile = mc_dir / "browser_data" / "cdp_dy_user_data_dir"
        if mc_py:
            chk = subprocess.run(
                [str(mc_py), "-c", "import playwright, execjs; print('ok')"],
                capture_output=True,
                text=True,
                check=False,
            )
            deps_ok = chk.returncode == 0 and "ok" in (chk.stdout or "")
            print(
                f"[{'OK' if deps_ok else 'WARN'}] MediaCrawler: {mc_dir} | .venv={mc_py} | "
                f"playwright+execjs={'OK' if deps_ok else 'MISSING'} | "
                f"Douyin profile={'YES' if dy_profile.is_dir() else 'NO (--login dy)'}"
            )
        else:
            print(
                f"[WARN] MediaCrawler: {mc_dir} (chưa có .venv — chạy 'python setup_machine.py' để cài)"
            )
    else:
        print("[FAIL] MediaCrawler: Không tìm thấy bản nào")
        issues += 1

    # 6. CUDA torch/lib vs CPU fallback
    torch_dirs = cl.find_torch_lib_dirs("", pdir)
    if torch_dirs:
        dll_cnt = sum(len(list(d.glob("*.dll"))) + len(list(d.glob("*.so*"))) for d in torch_dirs)
        print(f"[OK] CUDA torch/lib: {torch_dirs[0]} ({dll_cnt} lib files, GPU float16 sẵn sàng)")
    else:
        print("[WARN] CUDA torch/lib: Không thấy — Bước 2 sẽ tự fallback mượt sang Whisper CPU (int8)")

    # 7. Pipeline Python packages (trong interpreter hiện tại)
    mod_map = [
        ("faster_whisper", "faster-whisper"),
        ("rapidocr_onnxruntime", "rapidocr-onnxruntime"),
        ("edge_tts", "edge-tts"),
        ("numpy", "numpy"),
        ("PIL", "Pillow"),
        ("yt_dlp", "yt-dlp"),
    ]
    missing_pkgs = [pkg for mod, pkg in mod_map if importlib.util.find_spec(mod) is None]
    if not missing_pkgs:
        print("[OK] Gói Python pipeline: Đủ faster-whisper, rapidocr-onnxruntime, edge-tts, numpy, Pillow, yt-dlp")
    else:
        print(f"[WARN] Gói Python pipeline còn thiếu trong {Path(sys.executable).name}: {', '.join(missing_pkgs)}")

    # 8. Installed skill & AGENTS.md trigger
    skill_ok = (SKILL_DST / "SKILL.md").is_file() and (SKILL_DST / "vendor" / "MediaCrawler" / "main.py").is_file()
    agents_ok = AGENTS_MD_PATH.is_file() and "| vietsub-video-trung |" in AGENTS_MD_PATH.read_text(encoding="utf-8")
    print(f"[{'OK' if skill_ok else 'WARN'}] Skill cục bộ: {SKILL_DST} ({'đầy đủ' if skill_ok else 'chưa cài'})")
    print(f"[{'OK' if agents_ok else 'WARN'}] Trigger AGENTS.md: {AGENTS_MD_PATH} ({'đã bật' if agents_ok else 'chưa có'})")

    print(f"=== KẾT QUẢ DOCTOR: {issues} lỗi nghiêm trọng ===")
    return 1 if issues > 0 else 0


def run_login(platform_code: str, project_dir: Optional[str] = None) -> int:
    """Mở MediaCrawler/login_helper.py cho nền tảng được chọn (vd: dy)."""
    cl = _import_config_loader()
    pdir = Path(project_dir).expanduser().resolve() if project_dir else REPO_ROOT
    mc_dir = cl.find_mediacrawler_dir("", pdir)
    if not mc_dir:
        for cand in (SKILL_DST / "vendor" / "MediaCrawler", REPO_ROOT / "vendor" / "MediaCrawler"):
            if (cand / "login_helper.py").is_file():
                mc_dir = cand
                break
    if not mc_dir or not (mc_dir / "login_helper.py").is_file():
        raise FileNotFoundError("Không tìm thấy vendor/MediaCrawler/login_helper.py.")

    mc_py = cl.find_mediacrawler_python(mc_dir) or Path(sys.executable)
    print(f">>> Mở đăng nhập [{platform_code}] tại {mc_dir} bằng {mc_py}", flush=True)
    res = subprocess.run([str(mc_py), str(mc_dir / "login_helper.py"), platform_code], cwd=str(mc_dir))
    return res.returncode


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Cài đặt đa máy & kiểm tra sức khỏe cho Vietsub-video-Trung"
    )
    parser.add_argument("--doctor", action="store_true", help="Chỉ kiểm tra sức khỏe hệ thống (không cài/sửa)")
    parser.add_argument(
        "--skill-only",
        action="store_true",
        help="Chỉ đồng bộ skill + vendor/MediaCrawler + template + rules + AGENTS.md (không chạy uv/pip)",
    )
    parser.add_argument(
        "--skip-pip",
        action="store_true",
        help="Bỏ qua bước cài đặt gói Python & uv/pip, chỉ đồng bộ skill và chạy --doctor",
    )
    parser.add_argument(
        "--venv-target",
        choices=["skill", "repo", "both"],
        default="skill",
        help="Vị trí tạo .venv cho MediaCrawler (mặc định: skill)",
    )
    parser.add_argument(
        "--login",
        type=str,
        default="",
        help="Mở login_helper.py để quét QR đăng nhập nền tảng (vd: dy, xhs, bili, all)",
    )
    parser.add_argument(
        "--project-dir",
        type=str,
        default="",
        help="Thư mục dự án tùy chọn khi chạy --doctor hoặc --login",
    )
    args = parser.parse_args()

    if args.doctor and not args.skill_only and not args.login:
        sys.exit(run_doctor(args.project_dir or None))

    if args.login:
        sys.exit(run_login(args.login.strip(), args.project_dir or None))

    print(">>> Bước 1: Đồng bộ Skill + vendor/MediaCrawler + Template + Rules...", flush=True)
    stats = sync_skill_and_vendor()
    agent_msg = update_global_agents_md()
    print(f"  [OK] Đã đồng bộ sang {SKILL_DST}: {stats}")
    print(f"  [OK] {agent_msg}")

    if args.skill_only:
        print("=== HOÀN TẤT (--skill-only) ===")
        return

    if not args.skip_pip:
        targets: List[Path] = []
        if args.venv_target in ("skill", "both"):
            targets.append(SKILL_DST / "vendor" / "MediaCrawler")
        if args.venv_target in ("repo", "both"):
            repo_mc = REPO_ROOT / "vendor" / "MediaCrawler"
            if repo_mc.is_dir():
                targets.append(repo_mc)
        for mc_dir in targets:
            setup_mediacrawler_venv(mc_dir)

        install_pipeline_packages()

    print()
    rc = run_doctor(args.project_dir or None)
    print("\nTiếp theo: chạy 'python setup_machine.py --login dy' để đăng nhập Douyin nếu chưa có profile.")
    sys.exit(rc)


if __name__ == "__main__":
    main()
