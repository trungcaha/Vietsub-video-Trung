# -*- coding: utf-8 -*-
r"""Bước 5: Kiểm toán toàn diện sản phẩm đầu ra (ffprobe .mp4 + .vi.srt + .vi.ass),
kiểm tra lệch thời lượng < 0.6s, dung lượng đĩa và xuất BAO_CAO_SAN_XUAT.md kèm link file:///.
Chạy: python scripts/step5_audit_report.py [--project-dir <path>] [--max-diff 0.6]
"""

import argparse
import datetime
import io
import json
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from config_loader import (  # noqa: E402
    add_project_dir_arg,
    load_project_config,
    probe_media,
    sanitize_stem,
)

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "buffer"):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


def dir_size_mb(path: Path) -> float:
    if not path.exists():
        return 0.0
    total = sum(p.stat().st_size for p in path.rglob("*") if p.is_file())
    return round(total / (1024 * 1024), 2)


def audit_episode(
    ep: Dict[str, Any],
    cfg: Dict[str, Any],
    max_diff: float,
) -> Dict[str, Any]:
    ep_key = ep["ep_key"]
    trans_dir = Path(cfg["dirs"]["transcripts"])
    vi_dir = Path(cfg["dirs"]["translations"])
    out_dir = Path(cfg["dirs"]["output"])
    ffprobe_bin = cfg["tools"]["ffprobe"]

    zh_path = trans_dir / f"{ep_key}_zh.json"
    vi_path = vi_dir / f"{ep_key}_vi.json"

    zh_data = json.loads(zh_path.read_text(encoding="utf-8")) if zh_path.exists() else {}
    vi_data = json.loads(vi_path.read_text(encoding="utf-8")) if vi_path.exists() else {}

    stem = sanitize_stem(vi_data.get("vi_file_stem") or ep_key, ep_key)
    out_mp4 = out_dir / f"{stem}.mp4"
    out_srt = out_dir / f"{stem}.vi.srt"
    out_ass = out_dir / f"{stem}.vi.ass"

    raw_dur = float(zh_data.get("duration_sec") or ep.get("duration_sec") or 0.0)
    notes: List[str] = []
    status = "PASS"
    out_dur = 0.0
    diff_sec = 0.0
    res_str = "-"
    codecs_str = "-"
    size_mb = 0.0

    if not out_mp4.exists() or out_mp4.stat().st_size < 100_000:
        status = "FAIL"
        notes.append("Thiếu hoặc file MP4 quá nhỏ")
    else:
        size_mb = round(out_mp4.stat().st_size / (1024 * 1024), 2)
        try:
            info = probe_media(out_mp4, ffprobe_bin=ffprobe_bin)
            streams = info.get("streams") or []
            v_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
            a_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)
            out_dur = float((info.get("format") or {}).get("duration", 0) or 0)
            diff_sec = round(abs(out_dur - raw_dur), 3)

            if not v_stream or not a_stream:
                status = "FAIL"
                notes.append("Thiếu luồng video hoặc audio")
            else:
                res_str = f"{v_stream.get('width')}x{v_stream.get('height')}"
                codecs_str = f"{v_stream.get('codec_name')}/{a_stream.get('codec_name')}"

            if raw_dur > 0 and diff_sec >= max_diff:
                status = "FAIL"
                notes.append(f"Lệch thời lượng {diff_sec:.3f}s >= {max_diff:.2f}s")
        except Exception as e:
            status = "FAIL"
            notes.append(f"ffprobe lỗi: {e}")

    if not out_srt.exists() or out_srt.stat().st_size < 10:
        status = "FAIL"
        notes.append("Thiếu .vi.srt")
    if not out_ass.exists() or out_ass.stat().st_size < 100:
        status = "FAIL"
        notes.append("Thiếu .vi.ass")
    else:
        ass_txt = out_ass.read_text(encoding="utf-8-sig", errors="replace")
        if r"\kf" not in ass_txt:
            status = "FAIL"
            notes.append("File .vi.ass thiếu thẻ Karaoke \\kf")

    return {
        "ep_key": ep_key,
        "title_vi": vi_data.get("vi_title_display") or ep_key,
        "status": status,
        "raw_dur": round(raw_dur, 2),
        "out_dur": round(out_dur, 2),
        "diff_sec": diff_sec,
        "resolution": res_str,
        "codecs": codecs_str,
        "size_mb": size_mb,
        "out_mp4": out_mp4,
        "out_srt": out_srt,
        "out_ass": out_ass,
        "notes": notes,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Bước 5: Kiểm toán ffprobe & xuất BAO_CAO_SAN_XUAT.md")
    add_project_dir_arg(parser)
    parser.add_argument(
        "--max-diff",
        type=float,
        default=0.0,
        help="Ngưỡng lệch thời lượng tối đa tính bằng giây (mặc định theo project.json: 0.6s)",
    )
    parser.add_argument(
        "--out-report",
        type=str,
        default="",
        help="Đường dẫn file báo cáo Markdown (mặc định: <project_dir>/BAO_CAO_SAN_XUAT.md)",
    )
    args = parser.parse_args()

    cfg = load_project_config(args.project_dir or None)
    proj_dir = Path(cfg["project_dir"])
    raw_dir = Path(cfg["dirs"]["raw"])
    trans_dir = Path(cfg["dirs"]["transcripts"])
    vi_dir = Path(cfg["dirs"]["translations"])
    out_dir = Path(cfg["dirs"]["output"])
    tmp_root = Path(cfg["dirs"]["tmp"])

    max_diff = float(args.max_diff) if args.max_diff > 0 else float(
        (cfg.get("render") or {}).get("max_duration_diff_sec", 0.6)
    )
    report_path = (
        Path(args.out_report).expanduser().resolve()
        if args.out_report
        else proj_dir / "BAO_CAO_SAN_XUAT.md"
    )

    manifest_path = raw_dir / "posts_manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        all_eps = manifest.get("episodes", [])
        single_eps = [e for e in all_eps if not e.get("is_compilation")]
        comp_eps = [e for e in all_eps if e.get("is_compilation")]
    else:
        single_eps = [{"ep_key": p.stem.replace("_vi", "")} for p in sorted(vi_dir.glob("*_vi.json"))]
        comp_eps = []

    rows = [audit_episode(ep, cfg, max_diff=max_diff) for ep in single_eps]
    passed = sum(1 for r in rows if r["status"] == "PASS")
    failed = len(rows) - passed
    max_observed_diff = max((r["diff_sec"] for r in rows), default=0.0)

    raw_mb = dir_size_mb(raw_dir)
    trans_mb = dir_size_mb(trans_dir)
    vi_mb = dir_size_mb(vi_dir)
    out_mb = dir_size_mb(out_dir)
    tmp_mb = dir_size_mb(tmp_root)
    disk = shutil.disk_usage(proj_dir)
    free_gb = round(disk.free / (1024**3), 2)
    total_gb = round(disk.total / (1024**3), 2)

    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        f"# Báo Cáo Sản Xuất Vietsub Karaoke & Lồng Tiếng — {cfg.get('channel_name')}",
        "",
        f"- **Thời điểm kiểm toán:** `{now_str}`",
        f"- **Dự án (`project_slug`):** `{cfg.get('project_slug')}`",
        f"- **Thư mục dự án:** [{proj_dir.name}]({proj_dir.as_uri()})",
        f"- **Kênh nguồn:** {cfg.get('channel_url') or cfg.get('sec_uid')}",
        "",
        "## 1. Tổng quan đạt chuẩn",
        "",
        f"| Chỉ số | Giá trị |",
        f"|---|---|",
        f"| Tập lẻ kiểm toán | **{len(rows)}** |",
        f"| Tập hợp tập bỏ qua (`is_compilation`) | {len(comp_eps)} |",
        f"| Đạt chuẩn (`PASS`) | **{passed}/{len(rows)}** |",
        f"| Lỗi / thiếu (`FAIL`) | **{failed}** |",
        f"| Lệch thời lượng tối đa (`|out - raw|`) | `{max_observed_diff:.3f}s` (ngưỡng `< {max_diff:.2f}s`) |",
        f"| Dung lượng `output/` | `{out_mb:.2f} MB` (`raw/`: `{raw_mb:.2f} MB`, `_tmp/`: `{tmp_mb:.2f} MB`) |",
        f"| Dung lượng trống ổ đĩa | `{free_gb:.2f} GB / {total_gb:.2f} GB` |",
        "",
        "## 2. Chi tiết từng tập",
        "",
        "| Tập | Tiêu đề Việt | Trạng thái | Gốc (s) | Xuất (s) | Lệch (s) | Độ phân giải / Codec | Dung lượng | Tệp thành phẩm |",
        "|---|---|---|---|---|---|---|---|---|",
    ]

    for r in rows:
        links = []
        if r["out_mp4"].exists():
            links.append(f"[MP4]({r['out_mp4'].as_uri()})")
        if r["out_srt"].exists():
            links.append(f"[SRT]({r['out_srt'].as_uri()})")
        if r["out_ass"].exists():
            links.append(f"[ASS]({r['out_ass'].as_uri()})")
        link_cell = " · ".join(links) if links else "-"
        note_str = f" ({'; '.join(r['notes'])})" if r["notes"] else ""
        lines.append(
            f"| `{r['ep_key']}` | {r['title_vi']} | **{r['status']}**{note_str} | "
            f"{r['raw_dur']} | {r['out_dur']} | {r['diff_sec']} | "
            f"`{r['resolution']}` `{r['codecs']}` | {r['size_mb']} MB | {link_cell} |"
        )

    if tmp_mb > 1.0:
        lines.extend(
            [
                "",
                f"> **Lưu ý dọn rác:** Thư mục `_tmp/` hiện còn `{tmp_mb:.2f} MB`. Nên kiểm tra và xóa nếu không còn tập nào đang chạy.",
            ]
        )

    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"=== BƯỚC 5: KIỂM TOÁN HOÀN TẤT ({passed}/{len(rows)} PASS, {failed} FAIL) ===", flush=True)
    print(f"Báo cáo lưu tại: {report_path}", flush=True)
    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
