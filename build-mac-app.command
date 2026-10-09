#!/bin/bash
set -euo pipefail
XVL_SOURCE="$(cd -- "$(dirname -- "$0")" && pwd -P)"
XVL_BUNDLE="${1:-$(dirname -- "$XVL_SOURCE")/X视频下载器.app}"
case "$XVL_BUNDLE" in
    *.app) ;;
    *) printf '输出路径必须以 .app 结尾。\n' >&2; exit 1 ;;
esac
mkdir -p -- "$(dirname -- "$XVL_BUNDLE")"
XVL_PARENT="$(cd -- "$(dirname -- "$XVL_BUNDLE")" && pwd -P)"
XVL_BUNDLE="$XVL_PARENT/$(basename -- "$XVL_BUNDLE")"
XVL_IDENTIFIER="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$XVL_SOURCE/mac/Info.plist")"
check_output() {
    if [ -L "$XVL_BUNDLE" ]; then
        printf '输出位置是符号链接；请改用一个新的 .app 路径。\n' >&2
        return 1
    fi
    if [ -e "$XVL_BUNDLE" ]; then
        XVL_EXISTING_IDENTIFIER="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$XVL_BUNDLE/Contents/Info.plist" 2>/dev/null || true)"
        if [ ! -d "$XVL_BUNDLE" ] || [ "$XVL_EXISTING_IDENTIFIER" != "$XVL_IDENTIFIER" ]; then
            printf '输出位置不是本下载器，已停止以保护现有文件。\n' >&2
            return 1
        fi
    fi
}
check_output
XVL_BUILD="$(mktemp -d "${TMPDIR:-/tmp}/xvl-native.XXXXXX")"
trap '/bin/rm -rf -- "$XVL_BUILD"' EXIT
XVL_NEW="$XVL_BUILD/$(basename -- "$XVL_BUNDLE")"
mkdir -p -- "$XVL_NEW/Contents/MacOS"

printf '正在编译 Mac 独立窗口…\n'
/usr/bin/xcrun swiftc "$XVL_SOURCE/mac/main.swift" -O \
    -target "$(uname -m)-apple-macosx12.0" \
    -framework Cocoa -framework WebKit -o "$XVL_NEW/Contents/MacOS/XVideoDownloader"
cp -- "$XVL_SOURCE/mac/Info.plist" "$XVL_NEW/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Set :XVLProjectFolder $(basename -- "$XVL_SOURCE")" "$XVL_NEW/Contents/Info.plist"
if [ -f "$XVL_SOURCE/mac/AppIcon.icns" ]; then
    mkdir -p -- "$XVL_NEW/Contents/Resources"
    cp -- "$XVL_SOURCE/mac/AppIcon.icns" "$XVL_NEW/Contents/Resources/AppIcon.icns"
fi
# 仅清理本次生成应用的 Finder 元数据，保留其他扩展属性。
/usr/bin/xattr -d com.apple.FinderInfo "$XVL_NEW" 2>/dev/null || true
/usr/bin/xattr -d com.apple.ResourceFork "$XVL_NEW" 2>/dev/null || true
/usr/bin/codesign --force --sign - "$XVL_NEW"
/usr/bin/codesign --verify "$XVL_NEW"
# Check again after compilation; never write through an existing application link.
check_output
XVL_BACKUP=""
if [ -e "$XVL_BUNDLE" ]; then
    XVL_BACKUP="$HOME/.Trash/X视频下载器-$(date '+%Y%m%d-%H%M%S')-$$-$RANDOM.app"
    /bin/mv -h -- "$XVL_BUNDLE" "$XVL_BACKUP"
fi
if ! /bin/mv -h -- "$XVL_NEW" "$XVL_BUNDLE"; then
    if [ -n "$XVL_BACKUP" ] && [ ! -e "$XVL_BUNDLE" ] && [ ! -L "$XVL_BUNDLE" ]; then
        /bin/mv -h -- "$XVL_BACKUP" "$XVL_BUNDLE"
    fi
    exit 1
fi
printf '已生成：%s\n请将应用与项目文件夹「%s」「视频」放在一起。\n' "$XVL_BUNDLE" "$(basename -- "$XVL_SOURCE")"
