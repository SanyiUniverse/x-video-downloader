#!/bin/bash
set -euo pipefail
XVL_ROOT="$(cd -- "$(dirname -- "$0")" && pwd)"
source "$XVL_ROOT/scripts/common.sh"
trap launcher_failure EXIT
cd "$XVL_ROOT"

if ! dependencies_ready; then
    printf '首次运行或依赖缺失，正在运行安装器…\n'
    XVL_INSTALL_PID=""
    stop_install() {
        trap - INT TERM
        set +u
        local installer_pid="${XVL_INSTALL_PID:-$!}"
        if [ -n "$installer_pid" ]; then
            kill -TERM -- "-$installer_pid" 2>/dev/null || true
            wait "$installer_pid" 2>/dev/null || true
        fi
        exit "$1"
    }
    trap 'stop_install 130' INT
    trap 'stop_install 143' TERM
    # 单独的安装作业组只包含本次安装器及它启动的子进程。
    set -m
    /bin/bash "$XVL_ROOT/install.command" &
    XVL_INSTALL_PID=$!
    set +m
    wait "$XVL_INSTALL_PID"
    trap - INT TERM
fi

printf '正在启动。Safari 会自动打开；关闭此终端或按 Control+C 可停止服务。\n'
exec "$XVL_ROOT/.venv/bin/python" "$XVL_ROOT/app.py" "$@"
