#!/usr/bin/env python3
# -*- coding: utf-8 -*-


import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
from datetime import datetime
from pathlib import Path

# ================= 路径配置 =================
# 本脚本位于 DouyinLiveRecorder/bin 目录下
BIN_DIR = Path(__file__).resolve().parent
SCRIPT_DIR = BIN_DIR.parent  # DouyinLiveRecorder 根目录

UPLOADER_BIN = BIN_DIR / "youtubeuploader"
LOG_FILE = Path("/root/youtube_upload.log")
CLIENT_SECRETS = Path("/etc/youtube/client_secrets.json")
REQUEST_TOKEN = Path("/etc/youtube/request.token")
BASE_DIR = SCRIPT_DIR / "downloads"
CONFIG_JSON = BIN_DIR / "channels.json"
MIN_SIZE_MB = 200
DEFAULT_DESC_FILE = BIN_DIR / "desc.txt"  # 全局默认简介，可不存在

# youtubeuploader 下载地址
YOUTUBEUPLOADER_URL = (
    "https://github.com/porjo/youtubeuploader/releases/download/"
    "v1.25.5/youtubeuploader_1.25.5_Linux_amd64.tar.gz"
)

VIDEO_EXTS = ["mp4", "flv", "ts", "mkv", "mov"]


# ================= 日志 =================
def log(msg: str) -> None:
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception as e:
        print(f"[写日志失败] {e}: {msg}", file=sys.stderr)
    print(msg)


def now_time() -> str:
    return datetime.now().strftime("%H:%M:%S")


def now_full() -> str:
    return datetime.now().strftime("%a %b %d %H:%M:%S %Z %Y")


# ================= 1. 确保 youtubeuploader 存在 =================
def ensure_youtubeuploader() -> None:
    if UPLOADER_BIN.exists():
        return

    log(f"[{now_time()}] 未找到 youtubeuploader，开始下载: {YOUTUBEUPLOADER_URL}")

    BIN_DIR.mkdir(parents=True, exist_ok=True)
    tar_path = BIN_DIR / "youtubeuploader_1.25.5_Linux_amd64.tar.gz"

    try:
        # 下载
        urllib.request.urlretrieve(YOUTUBEUPLOADER_URL, tar_path)
        log(f"[{now_time()}] 下载完成: {tar_path.name}")

        # 解压到临时目录，再定位出 youtubeuploader 二进制文件
        with tempfile.TemporaryDirectory() as tmp_dir:
            with tarfile.open(tar_path, "r:gz") as tf:
                tf.extractall(tmp_dir)

            extracted_bin = None
            for root, _dirs, files in os.walk(tmp_dir):
                if "youtubeuploader" in files:
                    extracted_bin = Path(root) / "youtubeuploader"
                    break

            if extracted_bin is None:
                raise FileNotFoundError("解压后未找到 youtubeuploader 二进制文件")

            shutil.move(str(extracted_bin), str(UPLOADER_BIN))

        # 删除压缩包
        tar_path.unlink(missing_ok=True)

        # 赋予可执行权限
        UPLOADER_BIN.chmod(0o755)

        log(f"[{now_time()}] youtubeuploader 安装完成: {UPLOADER_BIN}")

    except Exception as e:
        log(f"[{now_time()}] !!! youtubeuploader 下载/安装失败: {e}")
        # 清理残留的压缩包
        if tar_path.exists():
            tar_path.unlink(missing_ok=True)
        sys.exit(1)


# ================= 辅助函数 =================
def read_text_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def find_video_files(directory: Path, exts):
    matched = []
    for root, _dirs, files in os.walk(directory):
        for fname in files:
            for ext in exts:
                if fname.endswith(f".{ext}"):
                    matched.append(Path(root) / fname)
                    break
    return matched


def quota_exceeded(text: str) -> bool:
    return "quotaexceeded" in text.lower()


# ================= 主流程 =================
def main() -> None:
    # 强制环境编码（Python3 默认按 utf-8 处理字符串，这里仅为对齐原脚本语义，不需要额外设置）

    ensure_youtubeuploader()

    # --- 参数处理逻辑 ---
    target_ext = sys.argv[1] if len(sys.argv) > 1 else ""
    if not target_ext:
        exts = VIDEO_EXTS
        log("未指定格式，将扫描所有支持的视频类型...")
    else:
        clean_ext = target_ext[1:] if target_ext.startswith(".") else target_ext
        exts = [clean_ext]
        log(f"指定上传格式: {clean_ext}")

    # 检查环境
    if not CONFIG_JSON.exists():
        log("配置不存在")
        sys.exit(1)

    log(f"----------- 任务开始: {now_full()} -----------")

    try:
        channels = json.loads(CONFIG_JSON.read_text(encoding="utf-8"))
    except Exception as e:
        log(f"配置解析失败: {e}")
        sys.exit(1)

    default_description = read_text_file(DEFAULT_DESC_FILE) if DEFAULT_DESC_FILE.exists() else ""

    for relative_path, current_playlist in channels.items():
        full_path = BASE_DIR / relative_path

        if not full_path.is_dir():
            log(f"   [警告] 目录不存在，跳过: [{full_path}]")
            continue

        log(f">> 正在检查目录: [{relative_path}]")

        # 该目录（该频道/playlist）专属简介
        dir_desc_file = full_path / "description.txt"
        if dir_desc_file.exists():
            current_description = read_text_file(dir_desc_file)
        else:
            current_description = default_description

        for file_path in find_video_files(full_path, exts):
            if not file_path.exists():
                continue

            filename = file_path.name

            # ================= 1. 文件大小检查 =================
            try:
                file_size_bytes = file_path.stat().st_size
            except OSError:
                file_size_bytes = 0
            file_size_mb = file_size_bytes // (1024 * 1024)

            if file_size_mb < MIN_SIZE_MB:
                log(f"   [{now_time()}] 删除小文件: {filename} ({file_size_mb}MB < {MIN_SIZE_MB}MB)")
                try:
                    file_path.unlink()
                except OSError:
                    pass
                continue

            # ================= 2. TS 动态文件检测 =================
            if filename.lower().endswith(".ts"):
                size_before = file_size_bytes
                time.sleep(3)
                try:
                    size_after = file_path.stat().st_size
                except OSError:
                    size_after = None

                if size_before is None or size_before != size_after:
                    log(f"   [{now_time()}] 跳过动态文件 (正在录制): {filename}")
                    continue

            # ================= 3. 执行上传 =================
            log(f"   [{now_time()}] 准备上传: {filename} ({file_size_mb}MB)")

            cmd = [
                str(UPLOADER_BIN),
                "-secrets", str(CLIENT_SECRETS),
                "-cache", str(REQUEST_TOKEN),
                "-playlistID", str(current_playlist),
                "-privacy", "public",
                "-language", "zh-CN",
            ]
            if current_description:
                cmd += ["-description", current_description]
            cmd += ["-filename", str(file_path)]

            try:
                result = subprocess.run(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
            except Exception as e:
                log(f"   <<< 调用 youtubeuploader 失败: {e}")
                continue

            # stdout 追加到日志（原脚本中 stdout 直接 >> LOG_FILE）
            if result.stdout:
                log(result.stdout.rstrip())
            stderr_text = result.stderr or ""
            if stderr_text:
                log(stderr_text.rstrip())

            exit_code = result.returncode

            # 配额检查
            if quota_exceeded(stderr_text) or quota_exceeded(result.stdout or ""):
                log("   !!! 配额耗尽，脚本退出 !!!")
                sys.exit(1)

            # 结果处理
            if exit_code == 0:
                log("   >>> 成功，删除文件。")
                try:
                    file_path.unlink()
                except OSError:
                    pass
            else:
                log("   <<< 失败，保留文件。")

    log(f"----------- 任务结束: {now_full()} -----------")

"""
0 1-21/2 * * * flock -n /tmp/upload_douyin.lock -c "/usr/bin/python3 /root/DouyinLiveRecorder/bin/upload_douyin.py"

0 0-22/2 * * * flock -n /tmp/upload_douyin.lock -c "/usr/bin/python3 /root/DouyinLiveRecorder/bin/upload_douyin.py"
"""

if __name__ == "__main__":
    main()
