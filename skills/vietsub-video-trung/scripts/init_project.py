# -*- coding: utf-8 -*-
r"""Khởi tạo thư mục dự án Vietsub Karaoke & Lồng Tiếng mới từ bộ template.

Ví dụ:
  python init_project.py --slug kenh-moi --dest ./Du_an --channel-url "https://www.douyin.com/user/..."
"""

import argparse
import io
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Optional

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "buffer"):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


def extract_sec_uid(channel_url: str) -> str:
    url = (channel_url or "").strip()
    if not url:
        return ""
    m = re.search(r"/user/([A-Za-z0-9_.-]+)", url)
    if m:
        return m.group(1)
    m = re.search(r"sec_uid=([A-Za-z0-9_.-]+)", url)
    return m.group(1) if m else ""


def find_template_dir() -> Path:
    """Tìm template/ cho cả 2 chế độ: skill cài độc lập hoặc chạy trong repo gốc."""
    script_path = Path(__file__).resolve()
    candidates = [
        script_path.parents[1] / "template",  # skills/vietsub-video-trung/template (bản cài cục bộ)
        script_path.parents[3] / "template",  # <repo>/template (chạy từ source repo)
    ]
    for cand in candidates:
        if (cand / "project.example.json").is_file() and (cand / "scripts").is_dir():
            return cand
    raise FileNotFoundError(
        "Không tìm thấy thư mục template/ chứa project.example.json và scripts/. "
        f"Đã kiểm tra: {[str(c) for c in candidates]}"
    )


def init_project(
    slug: str,
    dest: Path,
    channel_url: str = "",
    sec_uid: str = "",
    channel_name: str = "",
    force: bool = False,
    in_place: bool = False,
) -> Path:
    clean_slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", slug.strip()).strip("-")
    if not clean_slug:
        raise ValueError(f"Slug không hợp lệ: {slug!r}")

    template_dir = find_template_dir()
    dest_resolved = dest.expanduser().resolve()
    if in_place or dest_resolved.name == clean_slug:
        proj_dir = dest_resolved
    else:
        proj_dir = dest_resolved / clean_slug

    proj_dir.mkdir(parents=True, exist_ok=True)
    for sub in ("raw", "transcripts", "translations", "output", "scripts"):
        (proj_dir / sub).mkdir(parents=True, exist_ok=True)

    # Copy toàn bộ template/scripts/*.py vào <proj_dir>/scripts/
    scripts_src = template_dir / "scripts"
    scripts_dst = proj_dir / "scripts"
    for py_file in sorted(scripts_src.glob("*.py")):
        dst_file = scripts_dst / py_file.name
        if force or not dst_file.exists():
            shutil.copy2(py_file, dst_file)

    # Sinh project.json từ mẫu
    proj_json_path = proj_dir / "project.json"
    if force or not proj_json_path.exists():
        cfg = json.loads((template_dir / "project.example.json").read_text(encoding="utf-8"))
        parsed_sec_uid = sec_uid.strip() or extract_sec_uid(channel_url)
        final_url = channel_url.strip() or (
            f"https://www.douyin.com/user/{parsed_sec_uid}" if parsed_sec_uid else ""
        )
        final_name = channel_name.strip() or clean_slug

        cfg["project_slug"] = clean_slug
        cfg["channel_name"] = final_name
        cfg["channel_url"] = final_url
        cfg["sec_uid"] = parsed_sec_uid
        proj_json_path.write_text(
            json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    # Sinh glossary.md từ mẫu
    glossary_dst = proj_dir / "glossary.md"
    if force or not glossary_dst.exists():
        glossary_tpl = (template_dir / "glossary.example.md").read_text(encoding="utf-8")
        lines = glossary_tpl.splitlines()
        if lines and lines[0].startswith("# "):
            display_name = channel_name.strip() or clean_slug
            lines[0] = f"# Từ điển nhân vật & Quy tắc dịch thuật — {display_name} ({clean_slug})"
        glossary_dst.write_text("\n".join(lines) + "\n", encoding="utf-8")

    return proj_dir


def main(argv: Optional[list] = None) -> None:
    parser = argparse.ArgumentParser(
        description="Khởi tạo dự án Vietsub Karaoke & Lồng Tiếng mới từ template"
    )
    parser.add_argument("--slug", required=True, help="Mã slug dự án (vd: wangwang-miaoba)")
    parser.add_argument(
        "--dest",
        type=str,
        default=".",
        help="Thư mục cha chứa dự án (hoặc chính thư mục dự án nếu trùng tên slug)",
    )
    parser.add_argument("--channel-url", type=str, default="", help="URL trang cá nhân kênh Douyin")
    parser.add_argument("--sec-uid", type=str, default="", help="Mã sec_uid Douyin (tùy chọn nếu đã có URL)")
    parser.add_argument("--channel-name", type=str, default="", help="Tên hiển thị của kênh")
    parser.add_argument("--in-place", action="store_true", help="Tạo trực tiếp trong --dest không lồng thêm <slug>")
    parser.add_argument("--force", action="store_true", help="Ghi đè scripts, project.json, glossary.md nếu đã có")
    args = parser.parse_args(argv)

    proj_dir = init_project(
        slug=args.slug,
        dest=Path(args.dest),
        channel_url=args.channel_url,
        sec_uid=args.sec_uid,
        channel_name=args.channel_name,
        force=args.force,
        in_place=args.in_place,
    )
    print(f"[OK] Đã khởi tạo dự án tại: {proj_dir}")
    print("Cấu trúc tạo sẵn: raw/, transcripts/, translations/, output/, scripts/, project.json, glossary.md")
    print("Bước tiếp theo:")
    print("  1. Kiểm tra/cập nhật glossary.md & roles trong project.json")
    print(f"  2. Chạy Bước 1: python \"{proj_dir / 'scripts' / 'step1_download_channel.py'}\" --project-dir \"{proj_dir}\"")


if __name__ == "__main__":
    main()
