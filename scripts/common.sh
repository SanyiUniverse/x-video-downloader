#!/bin/bash
# Shared launcher helpers. Sourcing this file does not install anything.

export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
export PYTHONDONTWRITEBYTECODE=1
export PIP_DISABLE_PIP_VERSION_CHECK=1
export HOMEBREW_NO_AUTO_UPDATE=1
export HOMEBREW_NO_INSTALL_CLEANUP=1

launcher_failure() {
    local status=$?
    if [ "$status" -ne 0 ]; then
        printf '\n操作未完成。请查看上方提示；网络错误可稍后重试。\n' >&2
        if [ -t 0 ]; then
            read -r -p '按回车关闭窗口…' _xvl_response || true
        fi
    fi
}

find_python() {
    local candidate
    local found
    found="$(command -v python3 || true)"
    shopt -s nullglob
    for candidate in "$found" /opt/homebrew/bin/python3 /usr/local/bin/python3 \
        /Library/Frameworks/Python.framework/Versions/Current/bin/python3 \
        /Library/Frameworks/Python.framework/Versions/3*/bin/python3; do
        if [ -n "$candidate" ] && [ -x "$candidate" ] && \
            "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
            XVL_PYTHON="$candidate"
            shopt -u nullglob
            return 0
        fi
    done
    shopt -u nullglob
    return 1
}

find_brew() {
    local candidate
    for candidate in /opt/homebrew/bin/brew /usr/local/bin/brew; do
        if [ -x "$candidate" ]; then
            XVL_BREW="$candidate"
            return 0
        fi
    done
    if command -v brew >/dev/null 2>&1; then
        XVL_BREW="$(command -v brew)"
        return 0
    fi
    return 1
}

dependencies_ready() {
    [ -x "$XVL_ROOT/.venv/bin/python" ] && \
        "$XVL_ROOT/.venv/bin/python" -c 'import sys, yt_dlp, certifi, requests; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1 && \
        command -v ffmpeg >/dev/null 2>&1 && \
        command -v ffprobe >/dev/null 2>&1
}
