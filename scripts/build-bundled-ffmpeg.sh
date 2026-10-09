#!/bin/bash
set -euo pipefail
# Only Apple system libraries are linked; no Homebrew runtime is required.
XVL_VERSION=9.0.2
XVL_SHA256=8c3850283eb25fa026482078a04051e0be17347b09ef81a0849bec15a96e002e
XVL_URL="https://ffmpeg.org/releases/ffmpeg-$XVL_VERSION.tar.xz"
XVL_WORK="${1:-$PWD/build/ffmpeg}"
if [ "$(uname -s)" != Darwin ] || [ "$(uname -m)" != arm64 ]; then
    printf '此构建脚本需要 Apple 芯片 Mac 和 Xcode Command Line Tools。\n' >&2
    exit 1
fi
mkdir -p -- "$XVL_WORK"
XVL_WORK="$(cd -- "$XVL_WORK" && pwd -P)"
XVL_ARCHIVE="$XVL_WORK/ffmpeg-$XVL_VERSION.tar.xz"
if [ ! -f "$XVL_ARCHIVE" ]; then
    /usr/bin/curl --fail --location --retry 3 --connect-timeout 30 --output "$XVL_ARCHIVE" "$XVL_URL"
fi
printf '%s  %s\n' "$XVL_SHA256" "$XVL_ARCHIVE" | /usr/bin/shasum -a 256 -c -
/usr/bin/tar -xf "$XVL_ARCHIVE" -C "$XVL_WORK"
cd -- "$XVL_WORK/ffmpeg-$XVL_VERSION"
XVL_OPTIONS=(
    --arch=arm64 --target-os=darwin --cc=/usr/bin/clang
    --enable-static --disable-shared --disable-autodetect
    --disable-gpl --disable-nonfree --disable-version3
    --enable-small --disable-doc --disable-debug --disable-checkasm
    --disable-network --disable-avdevice --disable-everything
    --disable-programs --enable-ffmpeg --enable-ffprobe
    --enable-demuxer=mov,mpegts,aac,concat
    --enable-muxer=mp4,mov,ipod
    --enable-parser=h264,aac
    --enable-decoder=h264,aac
    --enable-bsf=aac_adtstoasc,h264_mp4toannexb
    --enable-protocol=file,pipe
    --extra-cflags=-mmacosx-version-min=12.0
    --extra-ldflags=-mmacosx-version-min=12.0
)
MACOSX_DEPLOYMENT_TARGET=12.0 ./configure "${XVL_OPTIONS[@]}"
MACOSX_DEPLOYMENT_TARGET=12.0 /usr/bin/make -j "${XVL_JOBS:-8}" ffmpeg ffprobe
mkdir -p -- "$XVL_WORK/ffmpeg-bin"
cp -- ffmpeg ffprobe "$XVL_WORK/ffmpeg-bin/"
printf 'FFmpeg %s\nSource: %s\nSHA-256: %s\nConfiguration:\n' \
    "$XVL_VERSION" "$XVL_URL" "$XVL_SHA256" > "$XVL_WORK/FFmpeg-build.txt"
printf '  %s\n' "${XVL_OPTIONS[@]}" >> "$XVL_WORK/FFmpeg-build.txt"
printf '已生成：%s/ffmpeg-bin\n请保留源码压缩包，随二进制一并发布。\n' "$XVL_WORK"
