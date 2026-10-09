#!/usr/bin/env python3
"""Local, public-X-only interface around yt-dlp. No credentials or webpage parser."""
from __future__ import annotations

import argparse
import copy
import json
import multiprocessing as mp
import os
from pathlib import Path
import queue
import re
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import quote, urlsplit

ROOT = Path(__file__).resolve().parent
TERMINAL = {"done", "error", "cancelled"}


class UserError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code, self.message = code, message


def normalize_url(value):
    if not isinstance(value, str) or len(value) > 2048:
        raise UserError("invalid_url", "请粘贴完整的公开 X 推文链接。")
    try:
        parsed = urlsplit(value.strip())
        host = parsed.hostname
        port = parsed.port
    except ValueError:
        raise UserError("invalid_url", "链接格式不正确。") from None
    if (parsed.scheme not in ("http", "https") or
            host not in {"x.com", "www.x.com", "twitter.com", "www.twitter.com", "mobile.twitter.com"} or
            parsed.username or parsed.password or port is not None):
        raise UserError("invalid_url", "只接受 x.com 或 twitter.com 的推文链接。")
    match = re.fullmatch(r"/(?:([A-Za-z0-9_]{1,15})|i/web)/status/(\d{1,25})(?:/(?:video|photo)/[1-9]\d*)?/?", parsed.path)
    if not match:
        raise UserError("invalid_url", "请使用带有 /status/数字 的推文链接，不支持主页、直播或短链接。")
    return f"https://x.com/{match.group(1) or 'i/web'}/status/{match.group(2)}"


def friendly_error(exc):
    if isinstance(exc, UserError):
        return {"code": exc.code, "message": exc.message}
    text = str(exc).lower()
    if isinstance(exc, OSError) and getattr(exc, "errno", None) == 28:
        code, message = "storage", "磁盘空间不足，请清理下载位置后重试。"
    elif any(s in text for s in ("drm", "widevine", "fairplay")):
        code, message = "drm", "视频受 DRM 保护，工具不会解密或绕过保护。"
    elif any(s in text for s in ("private", "protected", "not authorized", "403", "unauthorized", "401")):
        code, message = "access", "内容受访问限制或平台拒绝请求。仅支持无需登录即可访问的公开视频。"
    elif any(s in text for s in ("log in", "login", "sign in", "authentication", "cookies")):
        code, message = "login", "平台要求登录。工具不读取浏览器登录信息，请使用无需登录的公开推文。"
    elif any(s in text for s in ("429", "rate-limit", "rate limit", "too many requests")):
        code, message = "rate_limit", "X 暂时限制了请求，请稍后重试。"
    elif any(s in text for s in ("ffmpeg", "ffprobe")):
        code, message = "ffmpeg", "FFmpeg 处理失败或未安装。请运行 install.command 后重试。"
    elif any(s in text for s in ("not found", "404", "deleted", "does not exist", "unavailable")):
        code, message = "unavailable", "推文已删除、不可用，或当前地区无法访问。请在 Safari 中核对原链接。"
    elif any(s in text for s in ("no video", "no media", "does not contain a video", "no formats")):
        code, message = "no_video", "这条推文没有可下载的视频。"
    elif any(s in text for s in ("certificate", "ssl")):
        code, message = "network", "安全连接验证失败。请检查系统时间、网络证书，并运行 update.command 更新依赖。"
    elif any(s in text for s in ("timeout", "timed out", "connection", "resolve", "network", "urlopen", "incompleteread", "bytes read")):
        code, message = "network", "网络连接失败或超时。请确认这台 Mac 能访问 X 和视频服务器后重试。"
    elif any(s in text for s in ("permission denied", "read-only", "no space")):
        code, message = "storage", "下载目录不可写或磁盘空间不足。请检查文件夹权限和剩余空间。"
    else:
        code, message = "extractor", "视频解析或下载失败。请更新 yt-dlp，并核对原推文是否仍可公开播放。"
    detail = re.sub(r"https?://\S+", "[远程地址]", str(exc))
    detail = re.sub(r"\x1b\[[0-9;]*m", "", detail)[-600:]
    return {"code": code, "message": message, "detail": detail}


def make_video(entry):
    if entry.get("is_live") or entry.get("live_status") == "is_live":
        raise UserError("live", "暂不支持正在进行的直播，请等待发布普通视频。")
    if entry.get("has_drm"):
        raise UserError("drm", "视频受 DRM 保护，工具不会解密或绕过保护。")
    formats = []
    for fmt in entry.get("formats", []):
        protocol = fmt.get("protocol", "https")
        if (fmt.get("has_drm") or fmt.get("vcodec") == "none" or
                fmt.get("ext") != "mp4" or protocol not in {"http", "https", "m3u8", "m3u8_native"}):
            continue
        codec = fmt.get("vcodec") or "unknown"
        if codec != "unknown" and not codec.startswith(("avc", "h264")):
            continue
        fid = str(fmt.get("format_id", ""))
        if not fid or not re.fullmatch(r"[A-Za-z0-9_.-]+", fid):
            continue
        w, h = fmt.get("width"), fmt.get("height")
        label = f"{w} × {h}" if w and h else (fmt.get("format_note") or "原始分辨率")
        fps = fmt.get("fps")
        if fps:
            label += f" · {fps:g} fps"
        label += " · HLS 分片" if protocol.startswith("m3u8") else " · MP4 直链"
        formats.append({"id": fid, "label": label, "width": w, "height": h,
                        "fps": fps, "protocol": protocol,
                        "size": fmt.get("filesize") or fmt.get("filesize_approx"),
                        "bitrate": fmt.get("tbr")})
    # Match the upstream X extractor's preference for HLS at equal resolution.
    # Direct MP4 metadata may describe an unavailable or incompatible CDN variant.
    formats.sort(key=lambda f: ((f["width"] or 0) * (f["height"] or 0), f["fps"] or 0,
                               f["protocol"].startswith("m3u8"), f["bitrate"] or 0), reverse=True)
    if not formats:
        if any(f.get("has_drm") for f in entry.get("formats", [])):
            raise UserError("drm", "可用视频受 DRM 保护，工具不会绕过保护。")
        raise UserError("no_video", "没有可用的 Safari 兼容 MP4/HLS 视频；可能仅含图片、外站媒体或受限内容。")
    return {"id": str(entry.get("id", "")), "title": str(entry.get("title") or "X 视频")[:400],
            "duration": entry.get("duration"), "formats": formats}


def video_entries(info):
    if not info:
        return []
    if info.get("_type") in {"playlist", "multi_video"}:
        return [entry for item in info.get("entries") or [] for entry in video_entries(item)]
    # Do not follow generic external embeds or accept audio broadcasts.
    if info.get("extractor_key", "Twitter") != "Twitter":
        return []
    return [info]


def ydl_options(events=None):
    class QuietLogger:
        def debug(self, message):
            pass
        def warning(self, message):
            pass
        def error(self, message):
            pass
    return {"quiet": True, "no_warnings": True, "logger": QuietLogger(),
            "socket_timeout": 30, "retries": 10, "fragment_retries": 10,
            "concurrent_fragment_downloads": 8,
            "retry_sleep_functions": {"http": lambda n: min(2 ** (n - 1), 20),
                                      "fragment": lambda n: min(2 ** (n - 1), 20)},
            "extractor_retries": 2, "skip_unavailable_fragments": False,
            "allowed_extractors": ["Twitter"], "allow_unplayable_formats": False,
            "hls_prefer_native": True, "overwrites": False,
            "noprogress": True, "cachedir": False}


def download_entry(entry, format_id, directory, emit, allow_fallback=True):
    """Download a known entry with yt-dlp and verify Safari-ready MP4."""
    import yt_dlp
    formats = {f["id"] for f in make_video(entry)["formats"]}
    if format_id not in formats:
        raise UserError("format_changed", "原清晰度已不可用，请重新检测并选择。")
    selected = next(f for f in entry["formats"] if str(f.get("format_id")) == format_id)
    selector = format_id
    audio = None
    if selected.get("acodec") == "none":
        # Separate AAC audio is merged by yt-dlp/FFmpeg. Silent clips remain silent.
        audios = [f for f in entry["formats"] if f.get("vcodec") == "none" and
                  not f.get("has_drm") and f.get("ext") in {"m4a", "mp4"} and
                  (not f.get("acodec") or f.get("acodec", "").startswith(("mp4a", "aac")))]
        if audios:
            audio = max(audios, key=lambda f: f.get("abr") or f.get("tbr") or 0)
            selector += "+" + str(audio["format_id"])
    # Estimate each stream's share once; keep total progress monotonic across
    # video, audio and native checkpoint retries. Reserve 5% for merge/verification.
    video_rate = selected.get("tbr") or selected.get("vbr") or 0
    audio_rate = (audio.get("abr") or audio.get("tbr") or 128) if audio else 0
    video_share = video_rate / (video_rate + audio_rate) if video_rate and audio else (0.9 if audio else 1)
    progress_floor = 0.0
    def hook(data):
        nonlocal progress_floor
        audio_stage = data.get("info_dict", {}).get("vcodec") == "none"
        total = data.get("total_bytes") or data.get("total_bytes_estimate")
        downloaded = data.get("downloaded_bytes", 0)
        finished = data.get("status") == "finished"
        fraction = 1 if finished else min(1, downloaded / total) if total else 0
        share, offset = (1 - video_share, video_share) if audio_stage and audio else (video_share, 0)
        progress_floor = max(progress_floor, 95 * (offset + share * fraction))
        percent = progress_floor if total or finished or progress_floor else None
        if data.get("status") == "finished":
            if audio and not audio_stage:
                emit({"message": "画面已下载，正在准备音轨…", "progress": {"percent": percent}})
            else:
                emit({"message": "下载完成，正在合并 MP4…", "progress": {"percent": 95}})
        else:
            emit({"message": "正在下载音轨…" if audio_stage else "正在下载画面…", "progress": {"percent": percent,
                  "stage": "音轨" if audio_stage else "画面",
                  "downloaded_bytes": downloaded, "total_bytes": total,
                  "speed": data.get("speed"), "eta": data.get("eta")}})
    opts = ydl_options()
    opts.update({"format": selector, "outtmpl": str(directory / "source.%(ext)s"),
                 "merge_output_format": "mp4", "progress_hooks": [hook]})
    try:
        stalled, last_size = 0, 0
        while True:
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    ydl.process_ie_result(copy.deepcopy(entry), download=True)
                break
            except yt_dlp.utils.DownloadError as exc:
                # Reuse yt-dlp's native .part/.ytdl checkpoint after transient faults.
                transient = bool(re.search(r"(did not get any data blocks|incompleteread|bytes read|timed out|connection|downloaded .+ expected|HTTP Error (500|502|503|504))", str(exc), re.I))
                restricted = bool(re.search(r"HTTP Error (401|403|429)\b|drm|login|private|protected", str(exc), re.I))
                current_size = sum(p.stat().st_size for p in directory.glob("source*") if p.is_file())
                stalled = 0 if current_size > last_size else stalled + 1
                last_size = current_size
                if not transient or restricted or stalled >= 5:
                    raise
                emit({"message": "网络传输中断，正在从已有进度继续下载…"})
                time.sleep(min(2 ** max(stalled, 1), 20))
    except yt_dlp.utils.DownloadError as exc:
        # Some X direct-CDN variants are stale while the public HLS playback works.
        # Retry only media availability/network errors, never authorization or DRM.
        text = str(exc).lower()
        eligible = any(s in text for s in ("404", "500", "502", "503", "504", "timed out", "connection reset"))
        restricted = any(s in text for s in ("401", "403", "429", "drm", "login", "private", "protected"))
        alternatives = [f for f in entry["formats"] if f.get("protocol", "").startswith("m3u8") and
                        f.get("width") == selected.get("width") and f.get("height") == selected.get("height") and
                        str(f.get("format_id")) in formats and str(f.get("format_id")) != format_id]
        if not (allow_fallback and eligible and not restricted and alternatives):
            raise
        alternate = max(alternatives, key=lambda f: f.get("tbr") or 0)
        emit({"message": "MP4 直链暂不可用，正在改用同清晰度的公开 HLS 视频…", "progress": {"percent": None}})
        for partial in directory.glob("source.*"):
            if partial.is_file():
                partial.unlink()
        return download_entry(entry, str(alternate["format_id"]), directory, emit, allow_fallback=False)
    sources = list(directory.glob("source.mp4"))
    if len(sources) != 1:
        raise UserError("ffmpeg", "未生成完整 MP4 文件，下载可能中断。")
    emit({"message": "正在验证 MP4 的完整性…", "progress": {"percent": 97}})
    # yt-dlp already fixes HLS containers and merges MP4 with +faststart.
    target = sources[0]
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json",
                            str(target)], capture_output=True, text=True, timeout=30, check=True)
    metadata = json.loads(probe.stdout)
    if "mp4" not in metadata.get("format", {}).get("format_name", "").split(","):
        raise UserError("invalid_media", "输出文件不是有效 MP4，未保存为成品。")
    streams = metadata.get("streams", [])
    if not any(s.get("codec_type") == "video" for s in streams) or target.stat().st_size < 128:
        raise UserError("invalid_media", "输出文件不包含有效视频，未保存为成品。")
    if any(s.get("codec_type") == "video" and s.get("codec_name") != "h264" for s in streams) or any(
            s.get("codec_type") == "audio" and s.get("codec_name") != "aac" for s in streams):
        raise UserError("unsupported_codec", "视频编码不适合 Safari 播放，请重新检测并选择其他格式。")
    expected = entry.get("duration")
    actual = float(metadata.get("format", {}).get("duration", 0))
    # X supplies duration_millis; allow mux rounding without accepting minutes of missing media.
    if expected and actual < float(expected) - max(2, float(expected) * 0.0001):
        raise UserError("incomplete", "视频时长明显不足，已停止交付不完整文件，请重试。")
    return target


def worker(kind, payload, events):
    # Own a process group so cancellation also terminates FFmpeg descendants.
    os.setsid()
    try:
        import yt_dlp
        emit = lambda data: events.put(("update", data))
        emit({"message": "正在请求 X 的公开视频信息…"})
        for attempt in range(3):
            try:
                with yt_dlp.YoutubeDL(ydl_options()) as ydl:
                    info = ydl.extract_info(payload["url"], download=False)
                break
            except Exception as exc:
                network = friendly_error(exc)["code"] == "network"
                transient_server = bool(re.search(r"HTTP Error (500|502|503|504)\b", str(exc)))
                if attempt == 2 or not (network or transient_server):
                    raise
                emit({"message": "网络响应中断，正在重新读取公开视频信息…"})
                time.sleep(2 ** attempt)
        entries = video_entries(info)
        if kind == "inspect":
            videos, errors = [], []
            for entry in entries:
                try:
                    videos.append(make_video(entry))
                except UserError as exc:
                    errors.append(exc)
            if not videos:
                raise errors[0] if errors else UserError("no_video", "这条推文没有可用的原生 X 视频。")
            events.put(("done", {"title": str(info.get("title") or videos[0]["title"])[:400],
                                 "url": payload["url"], "videos": videos}))
        else:
            entry = next((e for e in entries if str(e.get("id")) == payload["video_id"]), None)
            if entry is None:
                raise UserError("video_changed", "这段视频已不可用，请重新检测推文。")
            target = download_entry(entry, payload["format_id"], Path(payload["work_dir"]), emit)
            safe_title = re.sub(r"[^\w\u4e00-\u9fff .-]", "_", str(entry.get("title") or "X 视频"))[:70].strip(" .")
            events.put(("done", {"path": str(target), "filename": f"{safe_title or 'X 视频'}_{entry['id']}.mp4"}))
    except Exception as exc:
        events.put(("error", friendly_error(exc)))


class AppState:
    def __init__(self, download_dir):
        self.download_dir = Path(download_dir).expanduser().resolve()
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.csrf = secrets.token_urlsafe(32)
        self.lock = threading.RLock()
        self.jobs, self.inspections, self.files = {}, {}, {}
        self.closing = False

    def start_job(self, kind, payload):
        with self.lock:
            if self.closing:
                raise UserError("closing", "工具正在退出，请重新启动。")
            if any(j["status"] not in TERMINAL for j in self.jobs.values()):
                raise UserError("busy", "已有任务正在进行，请完成或取消后重试。")
            # Bound in-memory session history and stale metadata.
            if len(self.jobs) >= 100:
                oldest = next(iter(self.jobs))
                self.jobs.pop(oldest)
            job_id = secrets.token_urlsafe(18)
            context = mp.get_context("spawn")
            events = context.Queue()
            work_dir = None
            if kind == "download":
                work_dir = tempfile.mkdtemp(prefix=".xvl-", dir=self.download_dir)
                payload = dict(payload, work_dir=work_dir)
            process = context.Process(target=worker, args=(kind, payload, events), daemon=True)
            job = {"id": job_id, "kind": kind, "status": "running", "message": "任务已开始…",
                   "progress": {"percent": None}, "process": process, "work_dir": work_dir}
            self.jobs[job_id] = job
            process.start()
            threading.Thread(target=self._monitor, args=(job, events, payload), daemon=True).start()
            return job_id

    def _monitor(self, job, events, payload):
        process = job["process"]
        started, last_update = time.monotonic(), 0
        try:
            while True:
                limit = 180 if job["kind"] == "inspect" else 12 * 3600
                if time.monotonic() - started > limit:
                    self.cancel(job["id"])
                    with self.lock:
                        job.update(status="error", error={"code": "timeout", "message": "任务超时，已停止。请检查网络后重试。"})
                    break
                try:
                    event, data = events.get(timeout=0.2)
                except queue.Empty:
                    if not process.is_alive():
                        with self.lock:
                            if job["status"] not in TERMINAL:
                                job.update(status="error", error={"code": "worker", "message": "任务意外停止，请重试。"})
                        break
                    continue
                with self.lock:
                    if job["status"] == "cancelled":
                        break
                    if event == "update":
                        # Limit progress churn without losing terminal transitions.
                        if time.monotonic() - last_update > 0.12:
                            job.update(data)
                            last_update = time.monotonic()
                    elif event == "error":
                        job.update(status="error", error=data, message=data["message"])
                        break
                    elif event == "done":
                        if job["kind"] == "inspect":
                            inspection_id = secrets.token_urlsafe(18)
                            data["inspection_id"] = inspection_id
                            if len(self.inspections) >= 100:
                                self.inspections.pop(next(iter(self.inspections)))
                            self.inspections[inspection_id] = dict(data, created=time.time())
                        else:
                            source = Path(data.pop("path")).resolve()
                            if source.parent != Path(job["work_dir"]).resolve():
                                raise UserError("file", "输出路径验证失败。")
                            destination = self.download_dir / data["filename"]
                            # Never overwrite a user's existing file, including on concurrent launches.
                            base = destination.stem
                            for counter in range(10000):
                                if counter:
                                    destination = self.download_dir / f"{base} ({counter}).mp4"
                                try:
                                    os.link(source, destination)
                                    break
                                except FileExistsError:
                                    continue
                            else:
                                raise UserError("storage", "同名文件太多，请更换下载文件夹。")
                            file_id = secrets.token_urlsafe(18)
                            self.files[file_id] = destination
                            data = {"file_id": file_id, "filename": destination.name, "size": destination.stat().st_size}
                        job.update(status="done", message="完成", progress={"percent": 100}, result=data)
                        break
        except Exception as exc:
            with self.lock:
                job.update(status="error", error=friendly_error(exc))
        finally:
            process.join(timeout=2)
            if process.is_alive():
                self._terminate(process)
            if job["work_dir"]:
                shutil.rmtree(job["work_dir"], ignore_errors=True)
            events.close()

    @staticmethod
    def _terminate(process):
        if process.is_alive():
            try:
                if os.getpgid(process.pid) == process.pid:
                    os.killpg(process.pid, signal.SIGTERM)
                else:
                    process.terminate()
            except ProcessLookupError:
                pass
            process.join(timeout=2)
            if process.is_alive():
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.join(timeout=1)

    def cancel(self, job_id):
        with self.lock:
            job = self.jobs.get(job_id)
            if not job:
                raise UserError("not_found", "任务不存在或已清理。")
            if job["status"] in TERMINAL:
                return
            job.update(status="cancelled", message="任务已取消，临时文件会自动清理。")
        self._terminate(job["process"])

    def public_job(self, job_id):
        with self.lock:
            job = self.jobs.get(job_id)
            if not job:
                raise UserError("not_found", "任务不存在或已清理。")
            return {key: copy.deepcopy(value) for key, value in job.items() if key not in {"process", "work_dir"}}

    def close(self):
        self.closing = True
        for job_id in list(self.jobs):
            self.cancel(job_id)
        # All child processes are stopped before removing only our temporary dirs.
        for job in self.jobs.values():
            if job["work_dir"]:
                shutil.rmtree(job["work_dir"], ignore_errors=True)


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self, address, state):
        self.state = state
        super().__init__(address, Handler)
        self.origin = f"http://127.0.0.1:{self.server_address[1]}"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def respond(self, status, body, content_type="application/json; charset=utf-8", extra=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def check_local(self, mutate=False):
        port = self.server.server_address[1]
        if self.headers.get("Host") not in {f"127.0.0.1:{port}", f"localhost:{port}"}:
            raise UserError("forbidden", "请求来源无效。请使用启动时打开的本地地址。")
        origin = self.headers.get("Origin")
        if origin and origin not in {self.server.origin, f"http://localhost:{port}"}:
            raise UserError("forbidden", "已阻止外部网页调用本地工具。")
        if self.headers.get("Sec-Fetch-Site") == "cross-site":
            raise UserError("forbidden", "已阻止跨站请求。")
        if mutate and not secrets.compare_digest(self.headers.get("X-CSRF-Token", ""), self.server.state.csrf):
            raise UserError("forbidden", "页面验证已失效，请刷新本地页面。")

    def do_GET(self):
        try:
            self.check_local()
            path = urlsplit(self.path).path
            if path == "/":
                html = (ROOT / "web/index.html").read_text().replace("__CSRF_TOKEN__", self.server.state.csrf)
                self.respond(200, html, "text/html; charset=utf-8")
            elif path in {"/static/app.js", "/static/style.css"}:
                kind = "text/javascript" if path.endswith(".js") else "text/css"
                self.respond(200, (ROOT / "web" / Path(path).name).read_bytes(), kind + "; charset=utf-8")
            elif path == "/api/status":
                from yt_dlp.version import __version__
                version = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True, timeout=5).stdout.splitlines()[0]
                state = self.server.state
                with state.lock:
                    active = next((j for j in reversed(list(state.jobs.values()))
                                   if j["kind"] == "download" and j["status"] not in TERMINAL), None)
                    active = state.public_job(active["id"]) if active else None
                self.respond(200, {"yt_dlp_version": __version__, "ffmpeg_version": version,
                                   "download_dir": str(state.download_dir), "active_job": active})
            elif path.startswith("/api/jobs/"):
                self.respond(200, self.server.state.public_job(path.removeprefix("/api/jobs/")))
            elif path.startswith("/files/"):
                file = self.server.state.files.get(path.removeprefix("/files/"))
                if not file or not file.is_file():
                    raise UserError("not_found", "文件不存在或已移动。")
                self.send_response(200)
                self.send_header("Content-Type", "video/mp4")
                self.send_header("Content-Length", str(file.stat().st_size))
                self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quote(file.name)}")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                with file.open("rb") as stream:
                    shutil.copyfileobj(stream, self.wfile)
            else:
                raise UserError("not_found", "页面不存在。")
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:
            error = friendly_error(exc)
            self.respond(403 if error["code"] == "forbidden" else 404 if error["code"] == "not_found" else 500, {"error": error})

    def do_POST(self):
        try:
            self.check_local(mutate=True)
            if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
                raise UserError("bad_request", "请使用 JSON 请求。")
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 8192:
                raise UserError("bad_request", "请求大小无效。")
            data = json.loads(self.rfile.read(size))
            if not isinstance(data, dict):
                raise UserError("bad_request", "请求格式无效。")
            state = self.server.state
            path = urlsplit(self.path).path
            if path == "/api/inspect":
                url = normalize_url(data.get("url"))
                self.respond(202, {"job_id": state.start_job("inspect", {"url": url})})
            elif path == "/api/download":
                with state.lock:
                    inspection = state.inspections.get(data.get("inspection_id"))
                    if not inspection or time.time() - inspection["created"] > 3600:
                        raise UserError("expired", "检测结果已过期，请重新检测。")
                    video = next((v for v in inspection["videos"] if v["id"] == data.get("video_id")), None)
                    if not video or data.get("format_id") not in {f["id"] for f in video["formats"]}:
                        raise UserError("bad_request", "请选择检测结果中的视频和清晰度。")
                    payload = {"url": inspection["url"], "video_id": video["id"], "format_id": data["format_id"]}
                self.respond(202, {"job_id": state.start_job("download", payload)})
            elif path.startswith("/api/jobs/") and path.endswith("/cancel"):
                state.cancel(path[len("/api/jobs/"):-len("/cancel")])
                self.respond(200, {"ok": True})
            elif path == "/api/reveal":
                file = state.files.get(data.get("file_id"))
                if not file or not file.exists():
                    raise UserError("not_found", "文件不存在或已移动。")
                subprocess.run(["open", "-R", str(file)], check=True, timeout=10)
                self.respond(200, {"ok": True})
            elif path == "/api/shutdown":
                self.respond(200, {"ok": True})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
            else:
                raise UserError("not_found", "操作不存在。")
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:
            error = friendly_error(exc)
            self.respond(403 if error["code"] == "forbidden" else 404 if error["code"] == "not_found" else 400, {"error": error})


def main():
    parser = argparse.ArgumentParser(description="X 视频下载器，仅在本机运行")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--download-dir", type=Path, default=Path.home() / "Downloads/X-Video-Lab")
    args = parser.parse_args()
    try:
        import yt_dlp  # noqa: F401
        if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
            raise UserError("ffmpeg", "请先双击 install.command 安装 FFmpeg。")
        state = AppState(args.download_dir)
        server = LocalServer(("127.0.0.1", args.port), state)
    except Exception as exc:
        print(friendly_error(exc)["message"], file=sys.stderr)
        return 1
    print(f"X 视频下载器已启动：{server.origin}", flush=True)
    print(f"保存位置：{state.download_dir}\n退出：页面底部「退出工具」或在终端按 Control+C。", flush=True)
    if not args.no_browser:
        subprocess.run(["open", "-a", "Safari", server.origin], check=False)
    def stop(signum, frame):
        threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    try:
        server.serve_forever(poll_interval=0.2)
    finally:
        state.close()
        server.server_close()
        print("工具已退出，临时文件已清理。", flush=True)
    return 0


if __name__ == "__main__":
    mp.freeze_support()
    sys.exit(main())
