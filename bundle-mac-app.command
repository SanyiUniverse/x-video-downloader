#!/bin/bash
set -euo pipefail
XVL_ROOT="$(cd -- "$(dirname -- "$0")" && pwd -P)"
XVL_OUTPUT="${1:-$(dirname -- "$XVL_ROOT")/安装包}"
XVL_BUILD="$(mktemp -d "${TMPDIR:-/tmp}/xvl-package.XXXXXX")"
trap 'rm -rf -- "$XVL_BUILD"' EXIT
mkdir -p -- "$XVL_OUTPUT"
XVL_OUTPUT="$(cd -- "$XVL_OUTPUT" && pwd -P)"
XVL_PYTHON="${XVL_BUILD_PYTHON:-}"
if [ -z "$XVL_PYTHON" ]; then
    python3 -m venv "$XVL_BUILD/venv"
    XVL_PYTHON="$XVL_BUILD/venv/bin/python"
    "$XVL_PYTHON" -m pip install --index-url https://pypi.org/simple --require-hashes -r "$XVL_ROOT/requirements.txt"
    "$XVL_PYTHON" -m pip install --index-url https://pypi.org/simple -r "$XVL_ROOT/build-requirements.txt"
fi
XVL_FFMPEG="${XVL_FFMPEG_DIR:-}"
if [ -z "$XVL_FFMPEG" ]; then
    /bin/bash "$XVL_ROOT/scripts/build-bundled-ffmpeg.sh" "$XVL_BUILD/ffmpeg"
    XVL_FFMPEG="$XVL_BUILD/ffmpeg/ffmpeg-bin"
fi
printf '正在打包下载组件和运行环境…\n'
"$XVL_PYTHON" -m PyInstaller --noconfirm --onedir --name x-video-engine --target-arch arm64 \
    --distpath "$XVL_BUILD/dist" --workpath "$XVL_BUILD/cache" --specpath "$XVL_BUILD" \
    --add-data "$XVL_ROOT/web:web" --copy-metadata yt-dlp --copy-metadata requests \
    --copy-metadata certifi --copy-metadata charset-normalizer --copy-metadata idna \
    --copy-metadata urllib3 "$XVL_ROOT/app.py"
cp -- "$XVL_FFMPEG/ffmpeg" "$XVL_FFMPEG/ffprobe" "$XVL_BUILD/dist/x-video-engine/_internal/"
XVL_APP="$XVL_BUILD/dmg/X视频下载器.app"
mkdir -p -- "$XVL_BUILD/dmg"
/bin/bash "$XVL_ROOT/build-mac-app.command" "$XVL_APP"
/usr/bin/ditto "$XVL_BUILD/dist/x-video-engine" "$XVL_APP/Contents/Resources/engine"
/usr/bin/ditto "$XVL_ROOT/licenses" "$XVL_APP/Contents/Resources/Licenses"
cp -- "$XVL_ROOT/LICENSE" "$XVL_APP/Contents/Resources/Licenses/Project-MIT.txt"
cp -- "$XVL_ROOT/scripts/build-bundled-ffmpeg.sh" "$XVL_APP/Contents/Resources/Licenses/"
cp -- "$(dirname -- "$XVL_FFMPEG")/ffmpeg-9.0.2.tar.xz" "$XVL_APP/Contents/Resources/Licenses/"
XVL_PYTHON_LICENSE="$("$XVL_PYTHON" -c 'import sysconfig; print(sysconfig.get_path("stdlib") + "/LICENSE.txt")')"
cp -- "$XVL_PYTHON_LICENSE" "$XVL_APP/Contents/Resources/Licenses/Python-PSF.txt"
XVL_BOOT_LICENSE="$("$XVL_PYTHON" -c 'from importlib.metadata import distribution; d=distribution("PyInstaller"); print(next(str(d.locate_file(f)) for f in d.files if str(f).endswith("licenses/COPYING.txt")))')"
cp -- "$XVL_BOOT_LICENSE" "$XVL_APP/Contents/Resources/Licenses/PyInstaller.txt"
"$XVL_PYTHON" - "$XVL_APP/Contents/Resources/Licenses" <<'PY'
from importlib.metadata import distribution
from pathlib import Path
import shutil, sys
for name in ("setuptools", "packaging"):
    dist = distribution(name)
    for file in dist.files or ():
        if ".." in file.parts or not any(word in file.name.lower() for word in ("license", "copying", "notice")):
            continue
        source = Path(dist.locate_file(file))
        if source.is_file():
            target = Path(sys.argv[1]) / name / file
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
PY
/usr/bin/xattr -d com.apple.FinderInfo "$XVL_APP" 2>/dev/null || true
/usr/bin/xattr -d com.apple.ResourceFork "$XVL_APP" 2>/dev/null || true
/usr/bin/codesign --force --sign - "$XVL_APP"
/usr/bin/codesign --verify --deep --strict "$XVL_APP"
ln -s /Applications "$XVL_BUILD/dmg/应用程序"
printf '将 X视频下载器 拖入「应用程序」，然后打开并粘贴链接下载。\n适用于 Apple Silicon Mac（M系列芯片），macOS 12 或更新版本。\n' > "$XVL_BUILD/dmg/安装说明.txt"
XVL_DMG="$XVL_OUTPUT/XVideoDownloader-arm64.dmg"
/usr/bin/hdiutil create -volname 'X视频下载器' -srcfolder "$XVL_BUILD/dmg" -format UDZO -ov "$XVL_DMG"
(cd -- "$XVL_OUTPUT" && /usr/bin/shasum -a 256 "$(basename -- "$XVL_DMG")" > SHA256SUMS.txt)
printf '安装包已生成：%s\n' "$XVL_DMG"
