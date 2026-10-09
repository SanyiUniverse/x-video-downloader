# X 视频下载器

<img src="mac/AppIcon.png" width="72" align="right" alt="应用图标">

粘贴公开 X（Twitter）推文链接，一键下载 MP4。中文界面，默认下载最高可用清晰度，也可手动选择。

**[下载 Mac 安装包](https://github.com/SanyiUniverse/x-video-downloader/releases/latest/download/XVideoDownloader-arm64.dmg)** · 适用于 Apple Silicon Mac（M 系列芯片）

## 安装与使用

1. 下载并打开 `.dmg`，把 **X视频下载器** 拖入“应用程序”。
2. 从“应用程序”打开，或用 Spotlight 搜索 **X视频下载器**。
3. 粘贴完整推文链接，点击“下载视频”；完成后点击“在 Finder 中查看”。

安装包自带运行环境，无需安装 Python、Homebrew 或其他工具，无需 API Key 或付费服务。下载在本机完成，界面显示视频保存位置。

安装包未做 Apple 公证，其他 Mac 首次打开可能需要在“隐私与安全性”中确认来源。

需要选清晰度时，先勾选“下载前选择视频与清晰度”。工具自动处理 HLS 分段和单独音轨，最终保存为 MP4。

进度条显示整条视频的估算进度，画面、音轨和合并阶段分别标明，切换阶段不会归零。可以随时取消；关闭应用会停止当前任务，已保存的视频会保留。

## 更新

下载最新版安装包，关闭旧应用，把新版本拖入“应用程序”替换即可。已下载的视频保留。

## 验证与范围

已完整下载 **4:22:29、1080p** 视频，画面和音频全片解码通过；**26 项自动化测试通过**。详见 [测试记录](TESTING.md)。平台和网络变化仍可能影响其他链接。

支持公开推文中的原生视频；登录限制、私人内容、DRM、直播和 X Spaces 不支持，不绕过访问权限。请只保存有权使用的内容，并遵守 [X 服务条款](https://x.com/en/tos)。

解析与下载使用 [yt-dlp](https://github.com/yt-dlp/yt-dlp)，合并使用 [FFmpeg](https://ffmpeg.org/)。本项目源码采用 [MIT License](LICENSE)，包含的开源组件遵循各自许可证。

<details>
<summary>源码与自行构建</summary>

源码入口：[下载服务](app.py)、[中文界面](web/)、[Mac 窗口](mac/)、[测试](tests/)。开发构建需要 Python 3.10+ 和 Apple Command Line Tools；先运行 `install.command`，再运行 `build-mac-app.command`。自包含应用由 `bundle-mac-app.command` 打包。

</details>
