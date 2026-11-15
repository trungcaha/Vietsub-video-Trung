# -*- coding: utf-8 -*-
"""
Công cụ hỗ trợ đăng nhập lần lượt từng nền tảng cho MediaCrawler.
Lưu trực tiếp trạng thái đăng nhập vào browser_data/cdp_{platform}_user_data_dir
để khi chạy main.py không cần đăng nhập lại.
"""

import os
import subprocess
import sys
import time

from tools.browser_launcher import BrowserLauncher

PLATFORMS = {
    "1": ("dy", "Douyin (抖音)", "https://www.douyin.com"),
    "2": ("xhs", "Xiaohongshu - Tiểu Hồng Thư (小红书)", "https://www.xiaohongshu.com"),
    "3": ("ks", "Kuaishou (快手)", "https://www.kuaishou.com"),
    "4": ("bili", "Bilibili (哔哩哔哩)", "https://www.bilibili.com"),
    "5": ("wb", "Weibo (微博)", "https://www.weibo.com"),
    "6": ("zhihu", "Zhihu (知乎)", "https://www.zhihu.com"),
    "7": ("tieba", "Baidu Tieba (百度贴吧)", "https://tieba.baidu.com"),
}


def open_platform_login(code: str, name: str, url: str):
    launcher = BrowserLauncher()
    browser_paths = launcher.detect_browser_paths()
    if not browser_paths:
        print("❌ Không tìm thấy trình duyệt Chrome hoặc Edge trên máy!")
        sys.exit(1)

    browser_path = browser_paths[0]
    user_data_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "browser_data",
        f"cdp_{code}_user_data_dir",
    )
    os.makedirs(user_data_dir, exist_ok=True)

    print("\n" + "=" * 65)
    print(f"🚀 ĐANG MỞ TRÌNH DUYỆT ĐĂNG NHẬP: {name}")
    print(f"📂 Thư mục lưu phiên (Cookie/Profile): {user_data_dir}")
    print(f"🌐 Địa chỉ: {url}")
    print("=" * 65)
    print("👉 HƯỚNG DẪN:")
    print("   1. Trên cửa sổ Chrome vừa bật lên, hãy bấm '登录' (Đăng nhập).")
    print("   2. Mở App tương ứng trên điện thoại để quét mã QR (hoặc dùng SĐT/Cookie).")
    print("   3. Nếu có yêu cầu kéo mảnh ghép (Captcha), hãy kéo trực tiếp trên Chrome.")
    print("   4. Sau khi thấy đã vào tài khoản thành công, HÃY ĐÓNG CỬA SỔ CHROME ĐÓ LẠI")
    print("      để lưu phiên và chuyển sang nền tảng tiếp theo.")
    print("=" * 65)

    args = [
        browser_path,
        f"--user-data-dir={user_data_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-blink-features=AutomationControlled",
        url,
    ]

    proc = subprocess.Popen(args)
    proc.wait()
    print(f"✅ Đã đóng trình duyệt và lưu phiên đăng nhập cho [{name}]!\n")


def main():
    if len(sys.argv) > 1:
        target = sys.argv[1].strip().lower()
        for key, (code, name, url) in PLATFORMS.items():
            if target in (key, code):
                open_platform_login(code, name, url)
                return
        if target == "all":
            for key, (code, name, url) in PLATFORMS.items():
                open_platform_login(code, name, url)
            return

    while True:
        print("\n================ DANH SÁCH NỀN TẢNG MEDIACRAWLER ================")
        for key, (code, name, url) in PLATFORMS.items():
            profile_dir = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "browser_data",
                f"cdp_{code}_user_data_dir",
            )
            status = "✅ Đã có Profile" if os.path.exists(profile_dir) else "⚪ Chưa đăng nhập"
            print(f"  [{key}] {name:<38} (mã: {code:<5}) | {status}")
        print("  [all] Đăng nhập lần lượt tất cả từ 1 -> 7")
        print("  [0] Thoát")
        print("=================================================================")

        choice = input("👉 Nhập số (1-7), mã nền tảng (dy/xhs/...), 'all' hoặc '0' để thoát: ").strip().lower()
        if choice in ("0", "q", "exit"):
            print("👋 Hoàn tất thiết lập đăng nhập!")
            break
        elif choice == "all":
            for key, (code, name, url) in PLATFORMS.items():
                open_platform_login(code, name, url)
        else:
            matched = False
            for key, (code, name, url) in PLATFORMS.items():
                if choice in (key, code):
                    open_platform_login(code, name, url)
                    matched = True
                    break
            if not matched:
                print("⚠️ Lựa chọn không hợp lệ, vui lòng nhập lại!")


if __name__ == "__main__":
    main()
