#!/bin/bash
set -euo pipefail
XVL_ROOT="$(cd -- "$(dirname -- "$0")" && pwd)"
source "$XVL_ROOT/scripts/common.sh"
trap launcher_failure EXIT
cd "$XVL_ROOT"

if [ ! -x "$XVL_ROOT/.venv/bin/python" ]; then
    printf '请先运行 install.command 安装项目。\n' >&2
    exit 1
fi
printf '请先停止正在运行的工具。本操作升级项目内的解析、下载与 TLS 证书依赖。\n'
"$XVL_ROOT/.venv/bin/python" -m pip install --index-url https://pypi.org/simple --upgrade yt-dlp requests certifi charset-normalizer idna urllib3
"$XVL_ROOT/.venv/bin/python" -m pip check
printf '\n更新后的版本：\n'
"$XVL_ROOT/.venv/bin/python" -m yt_dlp --version
printf '\n更新完成。重新运行 start.command。\n'
