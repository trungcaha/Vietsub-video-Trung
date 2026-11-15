# -*- coding: utf-8 -*-
r"""Bước 1: Tải toàn bộ video của kênh từ project.json về raw/ và tạo raw/posts_manifest.json.
Chạy bằng Python môi trường MediaCrawler:
  <mediacrawler_python> scripts/step1_download_channel.py [--project-dir <path>]
"""

import argparse
import asyncio
import datetime
import io
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from config_loader import add_project_dir_arg, load_project_config, probe_video_basic  # noqa: E402

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "buffer"):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


def pick_best_video_urls(aweme: Dict[str, Any]) -> List[str]:
    """Chọn danh sách URL video chất lượng cao nhất (ưu tiên height/bitrate cao -> fallback play_addr)."""
    video = aweme.get("video") or {}
    bit_rates = list(video.get("bit_rate") or [])
    bit_rates.sort(
        key=lambda b: (
            int((b.get("play_addr") or {}).get("height", 0) or 0),
            int(b.get("bit_rate", 0) or 0),
        ),
        reverse=True,
    )
    urls: List[str] = []
    seen = set()
    for br in bit_rates:
        pa = br.get("play_addr") or {}
        for u in pa.get("url_list") or []:
            if u and u not in seen:
                seen.add(u)
                urls.append(u)
    pa_def = video.get("play_addr") or {}
    for u in pa_def.get("url_list") or []:
        if u and u not in seen:
            seen.add(u)
            urls.append(u)
    return urls


def download_with_curl(urls: List[str], dst: Path, user_agent: str, ffprobe_bin: str) -> bool:
    """Tải video qua curl về file .mp4.part rồi xác thực bằng ffprobe trước khi đổi tên."""
    curl_bin = shutil.which("curl.exe") or shutil.which("curl") or "curl"
    for url in urls:
        tmp_dst = dst.with_suffix(".mp4.part")
        tmp_dst.unlink(missing_ok=True)
        subprocess.run(
            [
                curl_bin,
                "-sSL",
                "--retry",
                "3",
                "--max-time",
                "300",
                "-A",
                user_agent,
                "-e",
                "https://www.douyin.com/",
                "-o",
                str(tmp_dst),
                url,
            ],
            check=False,
        )
        if probe_video_basic(tmp_dst, ffprobe_bin=ffprobe_bin) is not None:
            if dst.exists():
                dst.unlink()
            tmp_dst.replace(dst)
            return True
        tmp_dst.unlink(missing_ok=True)
    return False


async def fetch_posts_via_mediacrawler(
    mediacrawler_dir: Path, sec_uid: str
) -> Tuple[List[Dict[str, Any]], str]:
    """Dùng MediaCrawler + Playwright CDP lấy toàn bộ bài đăng của sec_uid."""
    if str(mediacrawler_dir) not in sys.path:
        sys.path.insert(0, str(mediacrawler_dir))

    prev_cwd = Path.cwd()
    os.chdir(str(mediacrawler_dir))
    try:
        import config  # type: ignore
        from media_platform.douyin.client import DouYinClient  # type: ignore
        from playwright.async_api import async_playwright  # type: ignore
        from tools import utils  # type: ignore
        from tools.cdp_browser import CDPBrowserManager  # type: ignore

        config.PLATFORM = "dy"
        config.ENABLE_CDP_MODE = True
        config.CDP_CONNECT_EXISTING = False

        cdp_manager = CDPBrowserManager()
        raw_posts: List[Dict[str, Any]] = []
        ua = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
        )
        page_num = 0
        try:
            async with async_playwright() as playwright:
                browser_context = await cdp_manager.launch_and_connect(
                    playwright=playwright,
                    playwright_proxy=None,
                    user_agent=None,
                    headless=False,
                )
                page = await browser_context.new_page()
                await page.goto(
                    f"https://www.douyin.com/user/{sec_uid}",
                    wait_until="domcontentloaded",
                    timeout=60000,
                )
                await asyncio.sleep(3.0)

                cookie_str, cookie_dict = await utils.convert_browser_context_cookies(
                    browser_context,
                    urls=[
                        "https://douyin.com",
                        "https://www.douyin.com",
                        "https://creator.douyin.com",
                    ],
                )
                ua = await page.evaluate("() => navigator.userAgent")
                dy_client = DouYinClient(
                    timeout=30,
                    headers={
                        "User-Agent": ua,
                        "Cookie": cookie_str,
                        "Host": "www.douyin.com",
                        "Origin": "https://www.douyin.com/",
                        "Referer": f"https://www.douyin.com/user/{sec_uid}",
                        "Content-Type": "application/json;charset=UTF-8",
                    },
                    playwright_page=page,
                    cookie_dict=cookie_dict,
                    proxy=None,
                )

                async def on_page(batch: List[Dict[str, Any]]):
                    nonlocal page_num
                    page_num += 1
                    print(
                        f"  [MediaCrawler] Trang {page_num}: +{len(batch)} bài",
                        flush=True,
                    )
                    await asyncio.sleep(0.8)

                raw_posts = await dy_client.get_all_user_aweme_posts(
                    sec_uid, callback=on_page
                )
        finally:
            await cdp_manager.cleanup()
        return raw_posts, ua
    finally:
        os.chdir(str(prev_cwd))


def run_fallback_downloader(
    fallback_py: Path, fallback_script: Path, sec_uid: str, fallback_dir: Path
) -> List[Dict[str, Any]]:
    """Chạy trình tải dự phòng (nếu được cấu hình qua ENV hoặc project.json)."""
    print(
        f"[Fallback] Đang chạy {fallback_script.name} để bổ sung danh sách video...",
        flush=True,
    )
    fallback_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            str(fallback_py),
            str(fallback_script),
            sec_uid,
            str(fallback_dir),
        ],
        cwd=str(fallback_script.parent),
        check=True,
    )
    posts_json = fallback_dir / "posts.json"
    if not posts_json.exists():
        return []
    return json.loads(posts_json.read_text(encoding="utf-8"))


async def main() -> None:
    parser = argparse.ArgumentParser(description="Bước 1: Tải toàn bộ video kênh Douyin về raw/")
    add_project_dir_arg(parser)
    parser.add_argument(
        "--min-expected",
        type=int,
        default=0,
        help="Nếu số bài lấy được từ MediaCrawler nhỏ hơn ngưỡng này và có cấu hình fallback, kích hoạt fallback",
    )
    args = parser.parse_args()

    cfg = load_project_config(args.project_dir or None)
    sec_uid = (cfg.get("sec_uid") or "").strip()
    if not sec_uid:
        raise ValueError(
            "Thiếu sec_uid trong project.json. Hãy điền sec_uid hoặc channel_url hợp lệ."
        )

    channel_name = cfg.get("channel_name") or cfg.get("project_slug")
    channel_url = cfg.get("channel_url") or f"https://www.douyin.com/user/{sec_uid}"
    raw_dir = Path(cfg["dirs"]["raw"])
    raw_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = raw_dir / "posts_manifest.json"
    ffprobe_bin = cfg["tools"]["ffprobe"]

    mc_dir_str = cfg["tools"].get("mediacrawler_dir") or ""
    if not mc_dir_str:
        raise RuntimeError(
            "Không tìm thấy thư mục MediaCrawler. Hãy đặt biến môi trường MEDIACRAWLER_DIR "
            "hoặc điền paths.mediacrawler_dir trong project.json."
        )
    mediacrawler_dir = Path(mc_dir_str)

    comp_min_sec = float(cfg.get("compilation_min_sec", 600))
    comp_keywords = [str(k) for k in (cfg.get("compilation_keywords") or ["合集", "纯享"])]

    print(f"=== BƯỚC 1: TẢI VIDEO KÊNH {channel_name} ({sec_uid}) ===", flush=True)
    raw_posts, ua = await fetch_posts_via_mediacrawler(mediacrawler_dir, sec_uid)

    dedup: Dict[str, Dict[str, Any]] = {}
    for item in raw_posts:
        aid = str(item.get("aweme_id") or "").strip()
        if aid:
            dedup[aid] = item

    print(f"[MediaCrawler] Lấy được {len(dedup)} bài duy nhất từ kênh.", flush=True)

    fallback_used = False
    fallback_dir = raw_dir / "_fallback_dl"
    fallback_items_by_id: Dict[str, Dict[str, Any]] = {}

    fb_py = Path(cfg["tools"]["fallback_dl_py"]) if cfg["tools"].get("fallback_dl_py") else None
    fb_script = Path(cfg["tools"]["fallback_dl_script"]) if cfg["tools"].get("fallback_dl_script") else None

    if (
        (not dedup or (args.min_expected > 0 and len(dedup) < args.min_expected))
        and fb_py is not None
        and fb_script is not None
        and fb_py.exists()
        and fb_script.exists()
    ):
        fallback_used = True
        fb_list = run_fallback_downloader(fb_py, fb_script, sec_uid, fallback_dir)
        for fi in fb_list:
            aid = str(fi.get("id") or fi.get("aweme_id") or "").strip()
            if aid:
                fallback_items_by_id[aid] = fi
                if aid not in dedup:
                    dedup[aid] = {
                        "aweme_id": aid,
                        "create_time": int(fi.get("t", fi.get("create_time", 0)) or 0),
                        "desc": fi.get("desc") or "",
                        "video": {
                            "duration": int(fi.get("dur", 0) or 0),
                            "play_addr": {"url_list": [fi.get("url")] if fi.get("url") else []},
                        },
                        "statistics": {},
                        "mix_info": {},
                        "_fallback_file": str(fallback_dir / f"{aid}.mp4"),
                    }
        print(f"[Fallback] Tổng bài sau gộp: {len(dedup)}", flush=True)

    if not dedup:
        raise RuntimeError("Không lấy được danh sách bài đăng nào từ Douyin!")

    sorted_items = sorted(
        dedup.values(),
        key=lambda x: (int(x.get("create_time", 0) or 0), str(x.get("aweme_id", ""))),
    )

    manifest_items: List[Dict[str, Any]] = []
    ok_count = 0
    comp_count = 0
    single_count = 0
    failed_ids: List[str] = []

    for idx, aweme in enumerate(sorted_items, 1):
        aid = str(aweme.get("aweme_id") or "").strip()
        ctime = int(aweme.get("create_time", 0) or 0)
        pub_dt = (
            datetime.datetime.fromtimestamp(ctime).strftime("%Y-%m-%d %H:%M")
            if ctime > 0
            else ""
        )
        desc = (aweme.get("desc") or "").strip().replace("\n", " ")
        mix_info = aweme.get("mix_info") or {}
        mix_name = (mix_info.get("mix_name") or "").strip()
        stats = aweme.get("statistics") or {}
        ep_key = f"{idx:02d}_{aid}"
        dst_mp4 = raw_dir / f"{ep_key}.mp4"

        fb_file = aweme.get("_fallback_file")
        if fb_file and Path(fb_file).exists() and not dst_mp4.exists():
            if probe_video_basic(Path(fb_file), ffprobe_bin=ffprobe_bin) is not None:
                Path(fb_file).replace(dst_mp4)

        urls = pick_best_video_urls(aweme)
        if not urls and aid in fallback_items_by_id and fallback_items_by_id[aid].get("url"):
            urls = [fallback_items_by_id[aid]["url"]]

        meta = probe_video_basic(dst_mp4, ffprobe_bin=ffprobe_bin)
        if meta is None:
            if not urls:
                print(f"  [{ep_key}] BỎ QUA (không có URL video): {desc[:55]}", flush=True)
                failed_ids.append(aid)
                continue
            print(f"  [{idx:02d}/{len(sorted_items)}] Đang tải {ep_key} ...", flush=True)
            if download_with_curl(urls, dst_mp4, ua, ffprobe_bin=ffprobe_bin):
                meta = probe_video_basic(dst_mp4, ffprobe_bin=ffprobe_bin)
            else:
                print(f"  [{ep_key}] LỖI TẢI VIDEO!", flush=True)
                failed_ids.append(aid)
                continue
        else:
            print(f"  [{idx:02d}/{len(sorted_items)}] Đã có sẵn {ep_key}.mp4", flush=True)

        w, h, dur_sec = meta
        is_compilation = bool(
            dur_sec >= comp_min_sec or any(kw and kw in desc for kw in comp_keywords)
        )
        ok_count += 1
        if is_compilation:
            comp_count += 1
        else:
            single_count += 1

        manifest_items.append(
            {
                "index": idx,
                "ep_key": ep_key,
                "aweme_id": aid,
                "aweme_url": f"https://www.douyin.com/video/{aid}",
                "create_time": ctime,
                "publish_date": pub_dt,
                "desc": desc,
                "mix_name": mix_name,
                "width": w,
                "height": h,
                "duration_sec": dur_sec,
                "is_compilation": is_compilation,
                "liked_count": int(stats.get("digg_count", 0) or 0),
                "share_count": int(stats.get("share_count", 0) or 0),
                "collected_count": int(stats.get("collect_count", 0) or 0),
                "comment_count": int(stats.get("comment_count", 0) or 0),
                "file_path": str(dst_mp4),
                "file_size_mb": round(dst_mp4.stat().st_size / (1024 * 1024), 2),
            }
        )

    if fallback_dir.exists():
        shutil.rmtree(fallback_dir, ignore_errors=True)

    manifest = {
        "project_slug": cfg.get("project_slug"),
        "channel_name": channel_name,
        "sec_uid": sec_uid,
        "channel_url": channel_url,
        "downloaded_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "fallback_used": fallback_used,
        "total_posts_fetched": len(sorted_items),
        "total_downloaded_mp4": ok_count,
        "single_episodes_count": single_count,
        "compilations_count": comp_count,
        "failed_ids": failed_ids,
        "episodes": manifest_items,
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("\n=== TỔNG KẾT BƯỚC 1 ===", flush=True)
    print(f"Tổng bài kênh trả về : {len(sorted_items)}")
    print(f"Tải thành công MP4   : {ok_count} (Thất bại: {len(failed_ids)})")
    print(f"Tập lẻ xử lý tiếp    : {single_count}")
    print(f"Hợp tập (>= {int(comp_min_sec)}s) : {comp_count}")
    print(f"Manifest lưu tại     : {manifest_path}")


if __name__ == "__main__":
    asyncio.run(main())
