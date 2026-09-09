#!/usr/bin/env python3
# -*- coding: utf-8 -*-


import json
import os
import pty
import select
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


def run_with_live_log(cmd):

    master_out, slave_out = pty.openpty()
    master_err, slave_err = pty.openpty()

    proc = subprocess.Popen(
        cmd,
        stdout=slave_out,
        stderr=slave_err,
        close_fds=True,
    )
    # 父进程不需要 slave 端，关闭它自己持有的副本
    os.close(slave_out)
    os.close(slave_err)

    output_chunks = []
    error_chunks = []
    buffers = {master_out: "", master_err: ""}
    open_fds = {master_out, master_err}

    while open_fds:
        try:
            readable, _, _ = select.select(list(open_fds), [], [], 0.5)
        except InterruptedError:
            continue

        if not readable:
            if proc.poll() is not None:
                break
            continue

        for fd in readable:
            try:
                data = os.read(fd, 4096)
            except OSError:
                data = b""

            if not data:
                open_fds.discard(fd)
                os.close(fd)
                continue

            text = data.decode("utf-8", errors="replace")
            buffers[fd] += text

            # 按 \n 或 \r 拆分：\r 用于处理进度条同行刷新的情况，
            # 这样每次进度更新都能单独写一行到日志里，而不是等到最后。
            while True:
                idx_n = buffers[fd].find("\n")
                idx_r = buffers[fd].find("\r")
                candidates = [i for i in (idx_n, idx_r) if i != -1]
                if not candidates:
                    break
                idx = min(candidates)
                line = buffers[fd][:idx]
                buffers[fd] = buffers[fd][idx + 1:]
                if line.strip():
                    log(f"   [{now_time()}] {line.rstrip()}")
                    (output_chunks if fd == master_out else error_chunks).append(line)

    proc.wait()

    # 冲刷两个缓冲区里残留、没有换行符结尾的最后一段内容
    for fd, chunks in ((master_out, output_chunks), (master_err, error_chunks)):
        remainder = buffers.get(fd, "")
        if remainder.strip():
            log(f"   [{now_time()}] {remainder.rstrip()}")
            chunks.append(remainder)

    combined_out = "\n".join(output_chunks)
    combined_err = "\n".join(error_chunks)
    return proc.returncode, combined_out, combined_err


# ================= 主流程 =================
def main() -> None:
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

            # ================= 1. 动态文件检测（是否仍在写入/录制中） =================
            try:
                size_before = file_path.stat().st_size
            except OSError:
                # 文件可能已被其他进程移动/删除，跳过
                continue

            time.sleep(3)

            try:
                size_after = file_path.stat().st_size
            except OSError:
                # 检测期间文件消失了，跳过
                continue

            if size_before != size_after:
                log(f"   [{now_time()}] 跳过动态文件 (正在录制): {filename}")
                continue

            file_size_bytes = size_after
            file_size_mb = file_size_bytes // (1024 * 1024)

            # ================= 2. 文件大小检查 =================
            if file_size_mb < MIN_SIZE_MB:
                log(f"   [{now_time()}] 删除小文件: {filename} ({file_size_mb}MB < {MIN_SIZE_MB}MB)")
                try:
                    file_path.unlink()
                except OSError:
                    pass
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
                exit_code, stdout_text, stderr_text = run_with_live_log(cmd)
            except Exception as e:
                log(f"   <<< 调用 youtubeuploader 失败: {e}")
                continue

            # 注意：run_with_live_log 内部已经把每一行/每次进度更新实时写入日志了，
            # 这里不需要再整体 log 一次，避免重复输出。

            # 配额检查
            if quota_exceeded(stderr_text) or quota_exceeded(stdout_text or ""):
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
0 1-23/2 * * * flock -n /tmp/upload_douyin.lock -c "/usr/bin/python3 /root/DouyinLiveRecorder/bin/upload_douyin.py"

0 0-22/2 * * * flock -n /tmp/upload_douyin.lock -c "/usr/bin/python3 /root/DouyinLiveRecorder/bin/upload_douyin.py"
"""

if __name__ == "__main__":
    main()