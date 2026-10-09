#!/bin/bash
set -euo pipefail
XVL_ROOT="$(cd -- "$(dirname -- "$0")" && pwd)"
source "$XVL_ROOT/scripts/common.sh"
trap launcher_failure EXIT
cd "$XVL_ROOT"

printf 'X 视频下载器 · 安装依赖\n'
if [ "$(uname -s)" != Darwin ]; then
    printf '这个双击安装器适用于 macOS。其他系统请使用 README 中的手动安装方法。\n' >&2
    exit 1
fi

if ! find_python; then
    if find_brew; then
        printf '未找到 Python 3.10 或以上版本，正在通过已有 Homebrew 安装 Python…\n'
        "$XVL_BREW" install python
        find_python
    else
        printf '需要 Python 3.10 或以上版本。请从 https://www.python.org/downloads/macos/ 安装后重试。\n' >&2
        exit 1
    fi
fi

if ! command -v ffmpeg >/dev/null 2>&1 || ! command -v ffprobe >/dev/null 2>&1; then
    if find_brew; then
        printf '正在通过已有 Homebrew 安装 FFmpeg（含 ffprobe），首次安装可能需要几分钟…\n'
        "$XVL_BREW" install ffmpeg
    else
        printf '需要 FFmpeg 和 ffprobe。请先从 https://brew.sh/ 安装 Homebrew，再重新运行此安装器。\n' >&2
        printf '也可使用 https://ffmpeg.org/download.html 提供的 macOS 构建，并把两个程序加入 PATH。\n' >&2
        exit 1
    fi
fi

if [ ! -d "$XVL_ROOT/.venv" ]; then
    printf '正在建立项目专用 Python 环境…\n'
    "$XVL_PYTHON" -m venv "$XVL_ROOT/.venv"
elif [ ! -x "$XVL_ROOT/.venv/bin/python" ] || \
    ! "$XVL_ROOT/.venv/bin/python" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
    printf '.venv 环境不完整或 Python 版本过旧。请将本项目中的 .venv 文件夹移走，再重新安装。\n' >&2
    exit 1
fi

printf '正在从官方 PyPI 安装经过固定和校验的解析、下载与 TLS 证书依赖…\n'
"$XVL_ROOT/.venv/bin/python" -m pip install --index-url https://pypi.org/simple --require-hashes -r "$XVL_ROOT/requirements.txt"
"$XVL_ROOT/.venv/bin/python" -m pip check
printf '\n验证依赖：\n'
"$XVL_ROOT/.venv/bin/python" -m yt_dlp --version
ffmpeg -version | sed -n '1p'
ffprobe -version | sed -n '1p'
printf '\n安装完成。双击 start.command 开始使用。\n'
