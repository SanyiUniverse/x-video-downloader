#!/bin/bash
set -euo pipefail
XVL_SOURCE="$(cd -- "$(dirname -- "$0")" && pwd -P)"
XVL_BUNDLE="$(dirname -- "$XVL_SOURCE")/X视频下载器.app"
XVL_BUILD="$(mktemp -d "${TMPDIR:-/tmp}/xvl-native.XXXXXX")"
trap 'if [ -f "$XVL_BUILD/XVideoDownloader" ]; then unlink "$XVL_BUILD/XVideoDownloader"; fi; rmdir "$XVL_BUILD"' EXIT

printf '正在编译 Mac 独立窗口…\n'
/usr/bin/xcrun swiftc "$XVL_SOURCE/mac/main.swift" -O \
    -target "$(uname -m)-apple-macosx12.0" \
    -framework Cocoa -framework WebKit -o "$XVL_BUILD/XVideoDownloader"
mkdir -p -- "$XVL_BUNDLE/Contents/MacOS"
cp -- "$XVL_BUILD/XVideoDownloader" "$XVL_BUNDLE/Contents/MacOS/XVideoDownloader"
cp -- "$XVL_SOURCE/mac/Info.plist" "$XVL_BUNDLE/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Set :XVLProjectFolder $(basename -- "$XVL_SOURCE")" "$XVL_BUNDLE/Contents/Info.plist"
# 仅清理本次生成应用的 Finder 元数据，保留其他扩展属性。
/usr/bin/xattr -d com.apple.FinderInfo "$XVL_BUNDLE" 2>/dev/null || true
/usr/bin/xattr -d com.apple.ResourceFork "$XVL_BUNDLE" 2>/dev/null || true
/usr/bin/codesign --force --sign - "$XVL_BUNDLE"
/usr/bin/codesign --verify "$XVL_BUNDLE"
printf '已生成：%s\n请将应用与项目文件夹「%s」「视频」放在一起。\n' "$XVL_BUNDLE" "$(basename -- "$XVL_SOURCE")"
