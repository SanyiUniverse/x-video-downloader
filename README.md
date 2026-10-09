# X 视频下载器

在 Mac 上粘贴一条公开 X（Twitter）推文链接，点击下载，自动保存最高可用清晰度的 MP4。需要时勾选“下载前选择视频与清晰度”，再手动选择。中文界面在本机运行，提供 Mac 独立窗口和 Safari 网页入口；解析和下载交给成熟的 [yt-dlp](https://github.com/yt-dlp/yt-dlp)，网络请求使用 [Requests](https://requests.readthedocs.io/)，合并和 MP4 处理交给 [FFmpeg](https://ffmpeg.org/)。无需 API Key、付费 API、X 开发者账户或在线下载网站，完整源代码可用于学习。

## Mac 独立窗口（推荐）

本次本机交付中，双击桌面成品文件夹里的 **X视频下载器.app**，粘贴链接并点击“下载视频”。文件直接保存到同一文件夹的 `视频/`。无需保持终端窗口；关闭下载器窗口会停止本机服务及当前任务。整个成品文件夹一起移动，应用和 `下载器/` 源码应保持相邻。

如果 macOS 首次询问是否允许访问该成品所在的桌面文件夹，请允许应用读取相邻源码和保存下载结果。

独立窗口使用 macOS 系统 WebKit 显示同一套中文界面，后端仍是 yt-dlp 与 FFmpeg。本机界面不会经过 Safari 的 HTTP 导航，适合启用了 HTTPS-only 的 Safari；不修改 Safari 安全设置、不安装证书或外网服务。Safari 网页方式保留为可选入口。新 Mac 首次运行仍需按下方说明安装 Python 和 FFmpeg。

从 GitHub 源码自行生成独立窗口：先双击 `install.command`，再双击 `build-mac-app.command`；构建需要 Apple Command Line Tools（提供 Swift 编译器），生成的 `.app` 与整个项目文件夹相邻。构建的应用是供本机使用的未公证程序；下载他人构建的二进制时，macOS 可能要求检查来源。直接在本机从源码编译不需要绕过浏览器安全提示。

## Safari 网页入口

1. 把整个项目文件夹放在希望长期保存的位置。
2. 双击 `start.command`。首次使用会自动安装缺失依赖，然后打开 Safari。也可以先双击 `install.command`，看见“安装完成”后再启动。
3. 粘贴 `https://x.com/用户名/status/推文编号` 或 `https://twitter.com/用户名/status/推文编号`，点击下载。默认选择检测到的第一个视频和最高可用清晰度。
4. 等待下载和处理完成。在 Finder 中打开结果；需要 Safari 另存一份时使用“另存一份”。

要下载其他视频或较低清晰度，先勾选默认未选中的“下载前选择视频与清晰度”，再提交链接。检测后会显示视频和清晰度选项，选好再下载。

默认文件夹为 `~/Downloads/X-Video-Lab`。下载由本地服务完成，不依赖 Safari 的下载权限；浏览器另存功能会额外创建一个副本。视频文件名包含视频编号，便于核对来源；同名结果自动另起名称，不覆盖原有文件。

运行期间保留启动时出现的终端窗口。按 `Control+C` 停止服务，再关闭窗口。仅关闭 Safari 标签页不会停止服务。端口自动选择，不必设置固定端口；启动窗口会显示可重新打开的网址。

**首次安装需要联网。** 安装器复用已有 Python 3.10 或更高版本和已有 Homebrew；缺 Python 时通过 Homebrew 安装，缺 FFmpeg/ffprobe 时通过 Homebrew 安装 FFmpeg。Python 包只进入本项目 `.venv` 文件夹。Homebrew 安装 FFmpeg 时可能安装或升级它所需的共享库；启动器关闭 Homebrew 的自动更新及安装后自动清理。

如果没有 Homebrew，请先通过 [Homebrew 官方入口](https://brew.sh/) 安装，或从 [FFmpeg 官方下载入口](https://ffmpeg.org/download.html) 获取 macOS 构建并将 `ffmpeg` 和 `ffprobe` 加入 PATH。缺 Python 且没有 Homebrew 时，安装器会提示从 [Python 官网](https://www.python.org/downloads/macos/) 安装。安装器不自动安装 Homebrew，不要求额外付费。

从互联网下载的文件若被 macOS 拦截，请先确认来源和源代码；可在终端中使用下面的方法启动。无需关闭系统安全保护。

```bash
cd "/你保存项目的位置/x-video-downloader"
/bin/bash install.command
/bin/bash start.command
```

复制或移动已安装的项目后，旧 `.venv` 可能仍指向原路径。请先停止服务，将本项目的 `.venv` 移到废纸篓，再运行安装器。源代码和下载的视频无需删除。[Python 的虚拟环境文档](https://docs.python.org/3/library/venv.html#how-venvs-work)解释了这一限制。

## 能做什么

- 默认一键检测并下载第一个视频的最高可用清晰度；可勾选“下载前选择视频与清晰度”切换为手动选择。
- 检测一条公开推文中的一个或多个原生视频；手动选择时显示分辨率、格式、时长和能获得的大小信息。
- 下载适合 Safari 的 MP4 视频清晰度；清晰度来自平台实际返回的源，不制造“更高清”的版本。
- 下载直接 MP4，或由 yt-dlp 获取 M3U8/HLS 分段，再自动使用 FFmpeg 合并和处理 MP4。平台单独提供音频时自动合并。
- 显示整条视频的总进度（估算）、速度和明确的画面／音轨阶段。按源流码率估算两者比重，进入音轨或断点重试时总进度不归零；合并与验证保留最后 5%，仅文件保存成功后显示 100%。HLS 大小会变动，数字是估算而非精确完成时间；剩余时间明确标为当前阶段。
- 取消检测或下载会停止当前任务及其 FFmpeg 子进程，并清理该任务的临时文件。已有视频保留。
- 在中文界面中提示无视频、链接错误、网络失败、平台限流、登录限制、私人或删除内容、DRM 与依赖问题。

范围是单条 X 推文的原生视频；外链视频、X Spaces 音频和实时直播不属于此工具的下载目标。检测结果随 X 接口和内容变化；此前可用的公开视频以后也可能要求登录。

默认先按分辨率和帧率选择；条件相同时优先 HLS 播放源，与上游 X 提取器的格式排序保持一致。HLS 通过 yt-dlp 同时获取最多 8 个分段，Requests 复用 HTTP 连接。网络中断和临时服务器错误会重试，等待间隔逐步增加至最多 20 秒；当前任务保留已下载分段并从断点继续。连续 5 次恢复都没有新增数据时停止，一项下载任务最长运行 12 小时。取消任务或停止服务会清理该任务的临时文件。

直接 MP4 失效时，可自动尝试一次同分辨率的公开 HLS 源；登录、私人内容、DRM、401/403 拒绝和 429 限流不会触发这个替换。

## 工作原理

```mermaid
flowchart LR
    A[粘贴公开推文链接] --> B[本机 Python 服务]
    B --> C[yt-dlp 检测视频和格式]
    C --> D[默认最高可用清晰度 或手动选择]
    D --> E[yt-dlp 获取 MP4 或 HLS 分段]
    E --> F[必要时使用 FFmpeg 合并和修复 MP4]
    F --> G[保存到 Mac 下载文件夹]
```

Safari 只显示界面并与本机服务通信。yt-dlp 负责跟随平台的公开播放数据，项目没有自己维护 X 网页解析器。yt-dlp 在需要时调用 FFmpeg 合并或修复 MP4；项目避免额外重复封装，不进行画质放大或视频重编码。最终用 ffprobe 检查 MP4 容器、H.264 视频、可选 AAC 音频和时长，再保存结果。检测与验证通过也不能保证所有平台内容始终可下载，实际验证范围见 [TESTING.md](TESTING.md)。

项目仅监听 `127.0.0.1`，检查请求主机和网页来源，并为操作请求验证会话令牌，适合个人本机学习，不作为公网网站部署。链接、检测结果和任务状态在本地处理；检测和下载会向 X 及其媒体服务发送网络请求。工具不读取 Safari Cookie，不读取浏览器登录信息，不上传本地文件，也不调用第三方解析网站。下载前会重新检测所选视频和格式，减少播放地址过期的问题。

## 登录、权限与版权

公开链接并不保证可以匿名下载。平台可能要求登录、限制地区或频率，内容也可能属于私人账户、已删除、受年龄限制或受 DRM 保护。遇到这些情况，工具停止并说明原因；它不导入账户 Cookie、不实现登录、不破解 DRM，也不绕过访问权限。

请只保存你有权保存和使用的内容，并遵守 [X 服务条款](https://x.com/en/tos)、创作者要求和适用规则。公开可观看不等于获得转载或商业使用许可。学习用途也不能替代必要授权。

## 更新与常见问题

X 的接口变化可能使当前 yt-dlp 失效。先停止工具，再双击 `update.command` 更新项目内的解析、HTTP 和证书依赖，随后重新启动。更新器从官方 PyPI 获取最新稳定版，不更改 FFmpeg 或 Python。首次安装的完整版本和 SHA-256 校验值固定在 `requirements.txt`；运行安装器可重新安装这些固定版本。主要版本为 [yt-dlp 2026.8.19](https://pypi.org/project/yt-dlp/2026.8.19/)、[Requests 2.34.2](https://pypi.org/project/requests/2.34.2/) 与 [certifi 2026.7.22](https://pypi.org/project/certifi/2026.7.22/)，在 2026-10-10 核对官方发布信息。certifi 提供可信 TLS 根证书，工具始终保留 HTTPS 证书验证。

| 现象 | 处理方式 |
| --- | --- |
| 提示链接不正确 | 使用完整 `x.com` 或 `twitter.com` 推文链接；不要粘贴用户名页、搜索页或短链接。 |
| 没有可下载视频 | 确认推文含原生视频；纯图片、外链和直播可能不符合范围。 |
| 需要登录、私人内容、DRM | 在平台内确认自己的访问权限；工具不支持下载这类内容。 |
| 超时、连接失败 | 确认本机能够正常访问 X；稍后重试，并检查当前网络设置。 |
| 平台限流（429） | 等待后再试，减少连续检测；反复点击不会解除限制。 |
| FFmpeg 或 ffprobe 缺失 | 重新运行 `install.command`，查看安装器提示。需要的是可执行程序，不是同名 Python 包。 |
| 下载链接过期或 403 | 重新检测，再下载；若仍失败，停止后更新 yt-dlp。仍可能是平台访问限制。 |
| 磁盘空间不足或文件夹不可写 | 清出空间，或用下方 `--download-dir` 指定可写文件夹。 |
| Safari 页面对话无法连接 | 确认终端中的服务还在运行，使用启动窗口显示的当前地址重新打开。 |

升级并不保证解除平台限制。实际完成的测试和已知局限见 [TESTING.md](TESTING.md)；离线自动测试不能证明每一条当前 X 链接都可用。

## 命令行与源代码

项目不需要 Node.js 或前端编译。可选 Mac 独立窗口用系统 Swift 编译器构建。本地网页服务使用 Python 标准库；Python 依赖为 yt-dlp、Requests、certifi 以及 Requests 的 charset-normalizer、idna、urllib3 依赖，全部固定版本并校验。另需 `ffmpeg` 和 `ffprobe` 可执行程序。

```text
x-video-downloader/
├── app.py                  本机服务、检测和下载任务
├── web/                    中文网页界面
├── mac/                    Mac 独立窗口源码与应用信息
├── build-mac-app.command    本机构建独立窗口
├── tests/                  自动化验证
├── scripts/common.sh       Mac 启动器共用函数
├── install.command         安装固定依赖
├── start.command           安装检查并启动
├── update.command          升级项目内的解析和网络依赖
├── requirements.txt        Python 依赖版本与校验
├── TESTING.md               实际验证记录与限制
├── README.md
└── LICENSE
```

指定保存位置：

```bash
./start.command --download-dir "$HOME/Movies/X-Videos"
```

使用固定端口并保留手动打开浏览器的方式：

```bash
.venv/bin/python app.py --port 8765 --no-browser
```

默认端口 `0` 表示由系统分配空闲端口。使用 `--no-browser` 后，打开终端显示的 URL。所有命令都在项目文件夹内执行。

运行测试：

```bash
.venv/bin/python -m unittest discover -s tests -v
```

支持和验证的平台是 macOS。下面是手动安装方式；其他系统若用于源码学习，请自行安装 FFmpeg，用 `--no-browser` 启动后手动打开显示的网址，系统集成功能不作兼容保证：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --index-url https://pypi.org/simple --require-hashes -r requirements.txt
.venv/bin/python app.py --no-browser
```

进一步阅读：[yt-dlp 嵌入用法与进度回调](https://github.com/yt-dlp/yt-dlp#embedding-yt-dlp)、[yt-dlp 格式选择](https://github.com/yt-dlp/yt-dlp#format-selection)、[上游 X 提取器源码](https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/extractor/twitter.py)、[FFmpeg 文档](https://ffmpeg.org/documentation.html)。

## 卸载与许可证

先停止服务，然后将整个项目文件夹移到废纸篓。项目内的 `.venv` 会一起删除；`~/Downloads/X-Video-Lab` 中的视频保留。安装器安装的 Homebrew 依赖可能也被其他软件使用，因此不会自动删除；不要为卸载本项目而直接删除系统 Python 或 Homebrew。

本项目源代码使用 [MIT License](LICENSE)。yt-dlp 的 PyPI 源码和 wheel 使用 [Unlicense](https://github.com/yt-dlp/yt-dlp/blob/master/LICENSE)，Requests 使用 [Apache-2.0](https://github.com/psf/requests/blob/main/LICENSE)，certifi 使用 [MPL-2.0](https://github.com/certifi/python-certifi/blob/master/LICENSE)。charset-normalizer 与 urllib3 使用 MIT，idna 使用 BSD-3-Clause，详见各安装包中的许可证。FFmpeg 的许可证随构建选项而变化，具体参阅 [FFmpeg 许可证说明](https://ffmpeg.org/legal.html)和已安装构建的 `ffmpeg -L`。项目不附带或再分发 FFmpeg 二进制文件。视频版权属于各自权利人。
