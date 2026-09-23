#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bilibili UP主视频批量下载器 v2.0
=================================
直接使用 yt-dlp 引擎获取视频列表并下载，无需手动处理 WBI 签名和风控。
yt-dlp 已内置对 B站反爬机制的完整处理。

使用方法：
  1. 确保已安装: pip install yt-dlp
  2. 确保 ffmpeg 可用（用于合并音视频）
  3. 运行: python bilibili_downloader.py

可选：
  - 在浏览器中登录 B站后，设置 COOKIE_FROM_BROWSER 可下载更高画质
"""

import json
import os
import re
import sys
import time
from pathlib import Path

try:
    import yt_dlp
except ImportError:
    print("❌ 未安装 yt-dlp，请运行: pip install yt-dlp")
    sys.exit(1)

# ============================================================
#  配置区 — 按需修改
# ============================================================

# UP主的空间 URL 或 UID
UP_SPACE_URL = "https://space.bilibili.com/517717593"

# 视频保存目录（留空则自动以 UP主名称创建文件夹）
SAVE_DIR = ""

# 视频画质偏好
#   best    = 最高画质（需要登录才能获取 1080P+）
#   1080p   = 最高 1080P
#   720p    = 最高 720P
#   480p    = 最高 480P
QUALITY = "best"

# 是否下载字幕
DOWNLOAD_SUBTITLE = True

# 是否下载封面缩略图
DOWNLOAD_THUMBNAIL = True

# 是否保存视频信息到 .info.json
WRITE_INFO_JSON = False

# 每个视频下载间隔（秒），避免被风控
DOWNLOAD_INTERVAL = 3

# 最大并行下载的分片数
CONCURRENT_FRAGMENTS = 4

# 失败重试次数
MAX_RETRIES = 5

# Cookie 设置（可选，用于下载 1080P+ 高画质视频）
# 方式1: 从浏览器自动获取（推荐，填写浏览器名称: chrome / firefox / edge）
COOKIE_FROM_BROWSER = ""  # 例如: "chrome"
# 方式2: 直接粘贴 Cookie 字符串
COOKIE_STRING = ""

# ============================================================
#  辅助函数
# ============================================================

def sanitize_filename(name: str) -> str:
    """清理文件名中的非法字符"""
    return re.sub(r'[\\/:*?"<>|]', "_", name).strip()


def detect_ffmpeg() -> str | None:
    """自动检测 ffmpeg 路径"""
    # 优先检查 conda 环境中的 ffmpeg
    conda_ffmpeg = os.path.join(sys.prefix, "Library", "bin")
    if os.path.isfile(os.path.join(conda_ffmpeg, "ffmpeg.exe")):
        return conda_ffmpeg

    # 检查系统 PATH
    import shutil
    if shutil.which("ffmpeg"):
        return None  # yt-dlp 会自动从 PATH 找到

    print("⚠️  未检测到 ffmpeg，音视频可能无法合并为 MP4！")
    print("   请安装 ffmpeg 或通过 conda 安装: conda install ffmpeg")
    return None


def build_base_opts(save_dir: str) -> dict:
    """构建 yt-dlp 基础选项"""
    format_map = {
        "best": "bestvideo+bestaudio/best",
        "1080p": "bestvideo[height<=1080]+bestaudio/best[height<=1080]",
        "720p": "bestvideo[height<=720]+bestaudio/best[height<=720]",
        "480p": "bestvideo[height<=480]+bestaudio/best[height<=480]",
    }

    opts = {
        "format": format_map.get(QUALITY, format_map["best"]),
        "outtmpl": os.path.join(save_dir, "%(title)s [%(id)s].%(ext)s"),
        "ignoreerrors": True,
        "no_warnings": False,
        "quiet": False,
        "retries": MAX_RETRIES,
        "fragment_retries": MAX_RETRIES,
        "merge_output_format": "mp4",
        "concurrent_fragment_downloads": CONCURRENT_FRAGMENTS,
        "sleep_interval": 1,
        "max_sleep_interval": 3,
        "download_archive": os.path.join(save_dir, ".downloaded_archive.txt"),
        "break_on_existing": False,
        "extractor_args": {"bilibili": {"comment_sort": ["0"]}},
    }

    # ffmpeg 路径
    ffmpeg_dir = detect_ffmpeg()
    if ffmpeg_dir:
        opts["ffmpeg_location"] = ffmpeg_dir

    # Cookie 设置
    if COOKIE_FROM_BROWSER:
        opts["cookiesfrombrowser"] = (COOKIE_FROM_BROWSER,)
    elif COOKIE_STRING:
        cookie_file = os.path.join(save_dir, ".cookies.txt")
        _write_netscape_cookie(cookie_file, COOKIE_STRING)
        opts["cookiefile"] = cookie_file

    # 字幕
    if DOWNLOAD_SUBTITLE:
        opts["writesubtitles"] = True
        opts["writeautomaticsub"] = True
        opts["subtitleslangs"] = ["zh-CN", "zh-Hans", "ai-zh", "zh"]

    # 封面缩略图
    if DOWNLOAD_THUMBNAIL:
        opts["writethumbnail"] = True

    # 信息 JSON
    if WRITE_INFO_JSON:
        opts["writeinfojson"] = True

    return opts


def _write_netscape_cookie(filepath: str, cookie_str: str):
    """将 Cookie 字符串转为 Netscape 格式"""
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("# Netscape HTTP Cookie File\n")
        for item in cookie_str.split(";"):
            item = item.strip()
            if "=" in item:
                key, val = item.split("=", 1)
                f.write(
                    f".bilibili.com\tTRUE\t/\tFALSE\t0\t"
                    f"{key.strip()}\t{val.strip()}\n"
                )


# ============================================================
#  第一步：获取视频列表
# ============================================================

def fetch_video_list(space_url: str, save_dir: str) -> list:
    """
    使用 yt-dlp 提取 UP主空间的全部视频信息。
    yt-dlp 内置了对 B站反爬的完整处理，无需手动处理 WBI 签名。
    遇到 412 风控时会自动等待并重试。
    """
    print(f"\n📋 正在获取视频列表（使用 yt-dlp 引擎）...")
    print(f"   空间地址: {space_url}")
    print(f"   ⏳ 这可能需要一些时间，请耐心等待...\n")

    extract_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,      # 快速提取 URL 列表
        "ignoreerrors": True,
        "sleep_interval": 2,
        "max_sleep_interval": 5,
        "retries": MAX_RETRIES,
    }

    # Cookie 设置（提取列表时也可能需要）
    if COOKIE_FROM_BROWSER:
        extract_opts["cookiesfrombrowser"] = (COOKIE_FROM_BROWSER,)
    elif COOKIE_STRING:
        cookie_file = os.path.join(save_dir, ".cookies.txt")
        if not os.path.exists(cookie_file):
            _write_netscape_cookie(cookie_file, COOKIE_STRING)
        extract_opts["cookiefile"] = cookie_file

    ffmpeg_dir = detect_ffmpeg()
    if ffmpeg_dir:
        extract_opts["ffmpeg_location"] = ffmpeg_dir

    # 带重试的提取（应对临时性 412 风控）
    for attempt in range(MAX_RETRIES):
        videos = []
        try:
            with yt_dlp.YoutubeDL(extract_opts) as ydl:
                info = ydl.extract_info(space_url, download=False)

                if info is None:
                    if attempt < MAX_RETRIES - 1:
                        wait = 15 * (attempt + 1)
                        print(f"  ⚠️  获取失败（可能被 412 风控），"
                              f"等待 {wait} 秒后重试 "
                              f"({attempt + 1}/{MAX_RETRIES})...")
                        time.sleep(wait)
                        continue
                    print("❌ 无法获取空间信息（已用尽重试次数）")
                    return []

                # yt-dlp 返回 playlist 格式，entries 可能是 generator
                entries = info.get("entries", [])
                entry_list = list(entries) if entries else []

                if not entry_list:
                    if info.get("id"):
                        videos.append({
                            "url": info.get("webpage_url", info.get("url", "")),
                            "id": info.get("id", ""),
                            "title": info.get("title", "未知标题"),
                            "duration": info.get("duration"),
                        })
                    if not videos and attempt < MAX_RETRIES - 1:
                        wait = 15 * (attempt + 1)
                        print(f"  ⚠️  未获取到视频，"
                              f"等待 {wait} 秒后重试 "
                              f"({attempt + 1}/{MAX_RETRIES})...")
                        time.sleep(wait)
                        continue
                    return videos

                for entry in entry_list:
                    if entry is None:
                        continue
                    vid_url = entry.get("url", entry.get("webpage_url", ""))
                    vid_id = entry.get("id", "")
                    title = entry.get("title") or vid_id or "未知标题"
                    videos.append({
                        "url": vid_url,
                        "id": vid_id,
                        "title": title,
                        "duration": entry.get("duration"),
                    })

                # 成功获取，跳出重试循环
                break

        except Exception as e:
            err_msg = str(e)
            if ("412" in err_msg or "banned" in err_msg.lower()
                    or "风控" in err_msg):
                if attempt < MAX_RETRIES - 1:
                    wait = 20 * (attempt + 1)
                    print(f"  ⚠️  被风控拦截 (412)，等待 {wait} 秒后重试 "
                          f"({attempt + 1}/{MAX_RETRIES})...")
                    time.sleep(wait)
                    continue
            print(f"❌ 获取视频列表时出错: {e}")
            return []

    print(f"✅ 共获取到 {len(videos)} 个视频\n")
    return videos


# ============================================================
#  第二步：批量下载
# ============================================================

def download_videos(videos: list, save_dir: str):
    """批量下载视频列表"""
    opts = build_base_opts(save_dir)
    total = len(videos)
    success_count = 0
    fail_count = 0
    skip_count = 0
    failed_videos = []

    print("=" * 60)
    print(f"🚀 开始下载，共 {total} 个视频")
    print(f"📁 保存目录: {save_dir}")
    print(f"🎬 画质设置: {QUALITY}")
    print("=" * 60)

    for idx, video in enumerate(videos, 1):
        title = video.get("title", "未知")
        url = video.get("url", "")

        if not url:
            print(f"\n[{idx}/{total}] ⏭️  跳过（无有效 URL）: {title}")
            skip_count += 1
            continue

        # 确保 URL 完整
        if not url.startswith("http"):
            url = f"https://www.bilibili.com/video/{url}"

        duration_str = ""
        if video.get("duration"):
            m, s = divmod(int(video["duration"]), 60)
            duration_str = f" ({m}:{s:02d})"

        print(f"\n{'─' * 50}")
        print(f"[{idx}/{total}] 📹 {title}{duration_str}")
        print(f"         🔗 {url}")

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                result = ydl.download([url])
                if result == 0:
                    success_count += 1
                    print(f"         ✅ 下载成功")
                else:
                    skip_count += 1
                    print(f"         ⏭️  已存在或已跳过")
        except yt_dlp.utils.ExistingVideoReached:
            skip_count += 1
            print(f"         ⏭️  已下载过，跳过")
        except yt_dlp.utils.DownloadError as e:
            if "already been recorded" in str(e).lower():
                skip_count += 1
                print(f"         ⏭️  已下载过，跳过")
            else:
                fail_count += 1
                failed_videos.append(video)
                print(f"         ❌ 下载失败: {e}")
        except Exception as e:
            fail_count += 1
            failed_videos.append(video)
            print(f"         ❌ 下载失败: {e}")

        # 下载间隔
        if idx < total:
            time.sleep(DOWNLOAD_INTERVAL)

    # 打印统计
    print("\n")
    print("=" * 60)
    print(f"📊 下载完成！统计如下：")
    print(f"   ✅ 成功: {success_count}")
    print(f"   ⏭️  跳过: {skip_count}")
    print(f"   ❌ 失败: {fail_count}")
    print("=" * 60)

    if failed_videos:
        print("\n❌ 以下视频下载失败：")
        for v in failed_videos:
            print(f"   - {v['title']} ({v.get('id', '')})")

        fail_file = os.path.join(save_dir, "_failed_videos.json")
        with open(fail_file, "w", encoding="utf-8") as f:
            json.dump(failed_videos, f, ensure_ascii=False, indent=2)
        print(f"\n💾 失败列表已保存到: {fail_file}")
        print("   重新运行脚本即可重试，已成功的视频会自动跳过。")


# ============================================================
#  主程序
# ============================================================

def main():
    print("""
╔══════════════════════════════════════════════════════════╗
║       Bilibili UP主视频批量下载器 v2.0 (yt-dlp 引擎)    ║
╚══════════════════════════════════════════════════════════╝
    """)

    # 确定保存目录
    if SAVE_DIR:
        save_dir = SAVE_DIR
    else:
        # 从 URL 提取 UID 作为临时目录名
        uid = UP_SPACE_URL.rstrip("/").split("/")[-1]
        save_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            f"bilibili_{uid}"
        )
    Path(save_dir).mkdir(parents=True, exist_ok=True)

    # 1. 获取视频列表
    videos = fetch_video_list(UP_SPACE_URL, save_dir)

    if not videos:
        print("❌ 未获取到任何视频。可能的原因：")
        print("   1. UP主 UID 不正确")
        print("   2. UP主没有投稿视频")
        print("   3. 被 B站风控拦截 — 尝试设置 COOKIE_FROM_BROWSER")
        print(f"      例如: COOKIE_FROM_BROWSER = \"chrome\"")
        sys.exit(1)

    # 更新保存目录名为更友好的名称（如果能获取到 UP主名称）
    if not SAVE_DIR and videos:
        # 从第一个视频的 URL 中可能无法直接获取 UP主名，保持 UID 目录名即可
        pass

    # 保存视频列表
    list_file = os.path.join(save_dir, "_video_list.json")
    with open(list_file, "w", encoding="utf-8") as f:
        json.dump(videos, f, ensure_ascii=False, indent=2)
    print(f"💾 视频列表已保存到: {list_file}")

    # 展示视频列表
    print(f"\n📋 视频列表预览（前 10 个）：")
    print("─" * 50)
    for i, v in enumerate(videos[:10], 1):
        duration_str = ""
        if v.get("duration"):
            m, s = divmod(int(v["duration"]), 60)
            duration_str = f" [{m}:{s:02d}]"
        print(f"  {i:3d}. {v['title']}{duration_str}")
    if len(videos) > 10:
        print(f"  ... 还有 {len(videos) - 10} 个视频")
    print("─" * 50)

    # 确认下载
    print(f"\n⚡ 即将下载 {len(videos)} 个视频到: {save_dir}")
    try:
        confirm = input("   是否继续？(Y/n): ").strip().lower()
        if confirm and confirm != "y":
            print("👋 已取消下载")
            sys.exit(0)
    except (EOFError, KeyboardInterrupt):
        print("\n👋 已取消下载")
        sys.exit(0)

    # 开始下载
    download_videos(videos, save_dir)


if __name__ == "__main__":
    main()
