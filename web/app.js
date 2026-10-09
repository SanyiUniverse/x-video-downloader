"use strict";

(() => {
  const $ = (id) => document.getElementById(id);
  const elements = {
    form: $("inspect-form"), url: $("tweet-url"), inspect: $("inspect-button"), inspectLabel: $("inspect-label"), manual: $("manual-choice"), notice: $("notice"),
    selection: $("selection-panel"), title: $("tweet-title"), video: $("video-select"), quality: $("quality-select"),
    formatDetails: $("format-details"), download: $("download-button"), empty: $("empty-state"),
    job: $("job-panel"), jobTitle: $("job-title"), message: $("job-message"), track: $("progress-track"),
    fill: $("progress-fill"), percent: $("progress-percent"), progressMeta: $("progress-meta"), cancel: $("cancel-button"),
    complete: $("complete-panel"), filename: $("complete-filename"), size: $("complete-size"), reveal: $("reveal-button"),
    saveCopy: $("save-copy"), environment: $("environment-state"), environmentMessage: $("environment-message"),
    versions: $("environment-versions"), retry: $("retry-button"), shutdown: $("shutdown-button"), folder: $("save-folder"),
  };
  const csrf = document.querySelector('meta[name="csrf-token"]').content;
  if (new URLSearchParams(location.search).has("native")) {
    elements.saveCopy.hidden = true;
    document.querySelector(".brand").href = "/?native=1";
  }
  const state = { ready: false, stopped: false, busy: false, inspection: null, activeJob: null, epoch: 0, file: null, pollTimer: null, cancelling: false, autoDownload: false, downloadDir: "下载 / X-Video-Lab" };

  async function api(path, options = {}) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), options.timeout || 12000);
    const method = options.method || "GET";
    try {
      const response = await fetch(path, {
        method, credentials: "same-origin", cache: "no-store", signal: controller.signal,
        headers: method === "GET" ? { Accept: "application/json" } : { Accept: "application/json", "Content-Type": "application/json", "X-CSRF-Token": csrf },
        ...(method === "GET" ? {} : { body: JSON.stringify(options.body || {}) }),
      });
      const contentType = response.headers.get("content-type") || "";
      const data = contentType.includes("application/json") ? await response.json() : null;
      if (!response.ok) {
        const detail = data && (data.error || data.message);
        throw new Error(typeof detail === "string" ? detail : (detail && detail.message) || `请求未成功（${response.status}）。请稍后重试。`);
      }
      if (!data) throw new Error("本机服务返回了无法识别的响应。请重新启动工具。");
      return data;
    } catch (error) {
      if (error.name === "AbortError") throw new Error("本机服务响应超时。可重新检查环境或重新启动工具。");
      if (error instanceof TypeError) throw new Error("无法连接本机服务。请确认工具仍在运行，或重新打开启动文件。");
      throw error;
    } finally {
      clearTimeout(timeout);
    }
  }

  function showNotice(message, info = false) {
    elements.notice.textContent = String(message || "发生未知错误，请稍后重试。");
    elements.notice.classList.toggle("info", info);
    elements.notice.hidden = false;
  }

  function clearNotice() { elements.notice.hidden = true; elements.notice.textContent = ""; }

  function updateControls() {
    elements.inspect.disabled = !state.ready || state.busy || state.stopped;
    elements.url.disabled = state.busy || state.stopped;
    elements.manual.disabled = state.busy || state.stopped;
    elements.inspectLabel.textContent = elements.manual.checked ? "检测视频" : "下载视频";
    elements.video.disabled = state.busy || state.stopped;
    elements.quality.disabled = state.busy || state.stopped;
    elements.download.disabled = !state.ready || state.busy || state.stopped || !selectedFormat();
    elements.cancel.disabled = state.cancelling || !state.activeJob;
    elements.cancel.textContent = state.cancelling ? "正在取消…" : "取消";
    elements.shutdown.disabled = state.busy || state.stopped;
    elements.reveal.disabled = state.stopped || !state.file;
  }

  function selectedVideo() {
    return state.inspection && state.inspection.videos.find((video) => String(video.id) === elements.video.value);
  }

  function selectedFormat() {
    const video = selectedVideo();
    return video && video.formats.find((format) => String(format.id) === elements.quality.value);
  }

  function humanBytes(value) {
    const bytes = Number(value);
    if (!Number.isFinite(bytes) || bytes <= 0) return "";
    if (bytes < 1024) return `${Math.round(bytes)} B`;
    const units = ["KB", "MB", "GB", "TB"];
    let size = bytes / 1024;
    let index = 0;
    while (size >= 1024 && index < units.length - 1) { size /= 1024; index += 1; }
    return `${size >= 10 ? size.toFixed(0) : size.toFixed(1)} ${units[index]}`;
  }

  function humanDuration(value) {
    const seconds = Math.round(Number(value));
    if (!Number.isFinite(seconds) || seconds <= 0) return "";
    const hours = Math.floor(seconds / 3600);
    const mins = Math.floor(seconds / 60) % 60;
    return `${hours ? `${hours}:${String(mins).padStart(2, "0")}` : mins}:${String(seconds % 60).padStart(2, "0")}`;
  }

  function protocolLabel(protocol) {
    return /m3u8|hls/i.test(String(protocol)) ? "HLS / M3U8 · 自动合并" : /https?|mp4/i.test(String(protocol)) ? "直接 MP4" : String(protocol || "MP4");
  }

  function formatLabel(format) {
    if (format.label) return String(format.label);
    const resolution = format.height ? `${format.height}p` : format.width ? `${format.width} px` : "可用清晰度";
    return [resolution, format.fps ? `${format.fps} fps` : "", /m3u8|hls/i.test(String(format.protocol)) ? "HLS" : "MP4"].filter(Boolean).join(" · ");
  }

  function renderFormatDetails() {
    elements.formatDetails.replaceChildren();
    const format = selectedFormat();
    const video = selectedVideo();
    if (!format) { updateControls(); return; }
    const labels = [
      protocolLabel(format.protocol),
      format.width && format.height ? `${format.width} × ${format.height}` : "",
      format.fps ? `${format.fps} fps` : "",
      humanDuration(video.duration) ? `时长 ${humanDuration(video.duration)}` : "",
      humanBytes(format.size) ? `约 ${humanBytes(format.size)}` : "",
      !format.size && format.bitrate ? `${Math.round(format.bitrate)} kbps` : "",
    ].filter(Boolean);
    for (const label of labels) {
      const tag = document.createElement("span");
      tag.className = "format-tag";
      tag.textContent = label;
      elements.formatDetails.appendChild(tag);
    }
    updateControls();
  }

  function renderFormats() {
    elements.quality.replaceChildren();
    const video = selectedVideo();
    if (video && Array.isArray(video.formats)) {
      for (const format of video.formats) {
        const option = document.createElement("option");
        option.value = String(format.id);
        option.textContent = formatLabel(format);
        elements.quality.appendChild(option);
      }
    }
    renderFormatDetails();
  }

  function renderInspection(result, showSelection = true) {
    if (!result || !result.inspection_id || !Array.isArray(result.videos) || !result.videos.length) {
      throw new Error("这条推文未检测到可下载的视频。它可能只有图片，或内容已删除、需要登录。");
    }
    const videos = result.videos.filter((video) => Array.isArray(video.formats) && video.formats.length);
    if (!videos.length) throw new Error("检测到视频，但没有可用的 MP4 或 HLS 格式。受保护或受限的内容无法下载。");
    state.inspection = { ...result, videos };
    elements.title.textContent = String(result.title || "公开推文视频");
    elements.video.replaceChildren();
    videos.forEach((video, index) => {
      const option = document.createElement("option");
      option.value = String(video.id);
      const duration = humanDuration(video.duration);
      const label = video.title && String(video.title) !== String(result.title) ? String(video.title) : `视频 ${index + 1}`;
      option.textContent = `${label.slice(0, 75)}${duration ? ` · ${duration}` : ""}`;
      elements.video.appendChild(option);
    });
    elements.selection.hidden = !showSelection;
    elements.empty.hidden = true;
    renderFormats();
  }

  function renderProgress(job) {
    const progress = job.progress;
    const details = progress && typeof progress === "object" ? progress : {};
    let percent = typeof progress === "number" ? progress : details.percent;
    if (percent !== undefined && percent !== null && percent !== "") percent = Number(percent);
    const known = Number.isFinite(percent);
    elements.track.classList.toggle("indeterminate", !known);
    if (known) {
      percent = Math.max(0, Math.min(100, percent));
      elements.fill.style.width = `${percent}%`;
      elements.track.setAttribute("aria-valuenow", String(Math.round(percent)));
      elements.percent.textContent = `${Math.round(percent)}%`;
    } else {
      elements.track.removeAttribute("aria-valuenow");
      elements.fill.style.width = "";
      elements.percent.textContent = "";
    }
    elements.message.textContent = String(job.message || (job.kind === "download" ? "正在下载与处理视频…" : "正在读取可用视频信息…"));
    const downloaded = humanBytes(details.downloaded_bytes);
    const total = humanBytes(details.total_bytes);
    const speed = humanBytes(details.speed);
    const eta = Number(details.eta);
    elements.progressMeta.textContent = [downloaded ? `${details.stage ? `${details.stage} ` : ""}${downloaded}${total ? ` / ${total}` : ""}` : "", speed ? `${speed}/s` : "", Number.isFinite(eta) && eta > 0 ? `本阶段约剩 ${eta >= 60 ? `${Math.ceil(eta / 60)} 分钟` : `${Math.ceil(eta)} 秒`}` : ""].filter(Boolean).join(" · ");
  }

  function finishBusy() {
    clearTimeout(state.pollTimer);
    state.activeJob = null;
    state.busy = false;
    state.cancelling = false;
    elements.job.hidden = true;
    elements.empty.hidden = Boolean(state.inspection || state.file);
    updateControls();
  }

  async function pollJob(jobId, kind, epoch, failures = 0) {
    if (epoch !== state.epoch || state.stopped) return;
    try {
      const job = await api(`/api/jobs/${encodeURIComponent(jobId)}`);
      if (epoch !== state.epoch || state.stopped) return;
      renderProgress(job);
      const status = String(job.status || "").toLowerCase();
      if (["done", "completed", "complete", "success", "succeeded"].includes(status)) {
        const autoDownload = kind === "inspect" && state.autoDownload;
        state.autoDownload = false;
        finishBusy();
        if (kind === "inspect") {
          renderInspection(job.result, !autoDownload);
          if (autoDownload) {
            const video = selectedVideo();
            const format = selectedFormat();
            startJob("download", { inspection_id: state.inspection.inspection_id, video_id: video.id, format_id: format.id });
            if (state.inspection.videos.length > 1) showNotice(`检测到 ${state.inspection.videos.length} 段视频，本次自动下载第 1 段。需要选择其他视频时，可勾选「下载前选择视频与清晰度」。`, true);
          } else elements.download.focus();
        } else {
          const result = job.result;
          if (!result || !result.file_id) throw new Error("下载结束，但没有返回保存文件。请在下载文件夹中检查。");
          state.file = result;
          elements.filename.textContent = String(result.filename || "视频.mp4");
          elements.size.textContent = `${humanBytes(result.size) || "MP4 视频"} · ${state.downloadDir}`;
          elements.saveCopy.href = `/files/${encodeURIComponent(result.file_id)}`;
          elements.saveCopy.download = String(result.filename || "视频.mp4");
          elements.complete.hidden = false;
          updateControls();
          elements.reveal.focus();
        }
        return;
      }
      if (["failed", "error"].includes(status)) {
        const detail = job.error;
        throw new Error(typeof detail === "string" ? detail : (detail && detail.message) || job.message || "操作未完成，请检查链接并重试。");
      }
      if (["cancelled", "canceled"].includes(status)) {
        state.autoDownload = false;
        finishBusy();
        showNotice("任务已取消。你可以重新检测或选择清晰度后下载。", true);
        return;
      }
      state.pollTimer = setTimeout(() => pollJob(jobId, kind, epoch), 700);
    } catch (error) {
      if (epoch !== state.epoch || state.stopped) return;
      // A transient local connection failure should not silently discard an active download.
      if (/无法连接|响应超时/.test(error.message) && failures < 2) {
        elements.message.textContent = "正在重新连接本机服务…";
        state.pollTimer = setTimeout(() => pollJob(jobId, kind, epoch, failures + 1), 1200);
        return;
      }
      finishBusy();
      state.autoDownload = false;
      showNotice(error.message);
    }
  }

  async function startJob(kind, body) {
    if (state.busy || !state.ready || state.stopped) return;
    clearNotice();
    state.busy = true;
    state.cancelling = false;
    state.epoch += 1;
    const epoch = state.epoch;
    state.file = null;
    elements.complete.hidden = true;
    elements.empty.hidden = true;
    elements.job.hidden = false;
    const format = kind === "download" && selectedFormat();
    elements.jobTitle.textContent = kind === "inspect" ? (state.autoDownload ? "正在准备下载" : "正在检测视频") : `整条视频总进度（估算）${format && format.height ? ` · ${format.height}p` : ""}`;
    renderProgress({ kind, message: kind === "inspect" ? (state.autoDownload ? "正在读取视频，自动选择最高可用清晰度…" : "正在连接 X，读取视频信息…") : "正在准备下载…" });
    updateControls();
    try {
      const result = await api(`/api/${kind}`, { method: "POST", body });
      if (epoch !== state.epoch || state.stopped) return;
      if (!result.job_id) throw new Error("本机服务没有返回任务编号。请重新启动工具。");
      state.activeJob = result.job_id;
      updateControls();
      pollJob(result.job_id, kind, epoch);
    } catch (error) {
      if (epoch !== state.epoch || state.stopped) return;
      finishBusy();
      state.autoDownload = false;
      showNotice(error.message);
    }
  }

  function cleanTweetUrl(raw) {
    let value = raw.trim();
    if (!/^https?:\/\//i.test(value)) value = `https://${value}`;
    let url;
    try { url = new URL(value); } catch (_) { throw new Error("请粘贴完整的公开 X 推文链接，例如 https://x.com/用户名/status/推文编号。"); }
    const hosts = ["x.com", "www.x.com", "twitter.com", "www.twitter.com", "mobile.twitter.com"];
    if (!hosts.includes(url.hostname.toLowerCase()) || !/^\/(?:[A-Za-z0-9_]{1,15}\/status|i\/web\/status)\/\d{1,25}(?:\/(?:video|photo)\/[1-9]\d*)?\/?$/.test(url.pathname) || url.username || url.password || url.port) {
      throw new Error("需要一条公开 X 推文链接。请从推文的分享菜单复制链接，而不是账号主页或其他网站地址。");
    }
    url.protocol = "https:";
    url.hash = "";
    return url.toString();
  }

  async function checkEnvironment() {
    if (state.stopped || state.busy) return;
    state.ready = false;
    elements.environment.className = "environment-state";
    elements.environmentMessage.textContent = "正在检查本机环境…";
    elements.retry.hidden = true;
    updateControls();
    try {
      const data = await api("/api/status");
      const version = (value) => value ? String(value).replace(/^ffmpeg version\s+/i, "").split(/\s+/)[0].slice(0, 40) : "未检测到";
      elements.versions.textContent = `yt-dlp ${version(data.yt_dlp_version)} · FFmpeg ${version(data.ffmpeg_version)}`;
      if (data.ready === false || !data.yt_dlp_version || !data.ffmpeg_version) throw new Error(data.message || "下载依赖尚未就绪。请重新运行安装文件，再启动工具。");
      state.ready = true;
      elements.environment.className = "environment-state ready";
      elements.environmentMessage.textContent = "本机环境已就绪";
      if (data.download_dir) {
        const path = String(data.download_dir);
        state.downloadDir = path.endsWith("/Downloads/X-Video-Lab") ? "下载 / X-Video-Lab" : path.replace(/^\/Users\/[^/]+\//, "~/");
        elements.folder.textContent = state.downloadDir;
        document.querySelector(".save-note").title = path;
      }
      const activeJob = data.active_job;
      if (activeJob && activeJob.id && activeJob.kind === "download" && !["done", "completed", "error", "failed", "cancelled", "canceled"].includes(String(activeJob.status).toLowerCase())) {
        state.busy = true;
        state.autoDownload = false;
        state.inspection = null;
        state.file = null;
        state.activeJob = activeJob.id;
        state.epoch += 1;
        elements.selection.hidden = true;
        elements.complete.hidden = true;
        elements.empty.hidden = true;
        elements.job.hidden = false;
        elements.jobTitle.textContent = "整条视频总进度（估算）";
        renderProgress(activeJob);
        pollJob(activeJob.id, "download", state.epoch);
      }
      updateControls();
    } catch (error) {
      elements.environment.className = "environment-state error";
      elements.environmentMessage.textContent = error.message;
      elements.retry.hidden = false;
      updateControls();
    }
  }

  elements.form.addEventListener("submit", (event) => {
    event.preventDefault();
    if (state.busy || !state.ready || state.stopped) return;
    try {
      const url = cleanTweetUrl(elements.url.value);
      elements.url.value = url;
      state.inspection = null;
      state.autoDownload = !elements.manual.checked;
      elements.selection.hidden = true;
      startJob("inspect", { url });
    } catch (error) { showNotice(error.message); elements.url.focus(); }
  });

  elements.video.addEventListener("change", renderFormats);
  elements.quality.addEventListener("change", renderFormatDetails);
  elements.manual.addEventListener("change", () => {
    if (state.inspection && !state.busy) elements.selection.hidden = !elements.manual.checked;
    updateControls();
  });
  elements.download.addEventListener("click", () => {
    const video = selectedVideo();
    const format = selectedFormat();
    if (!video || !format || !state.inspection) return;
    startJob("download", { inspection_id: state.inspection.inspection_id, video_id: video.id, format_id: format.id });
  });

  elements.cancel.addEventListener("click", async () => {
    if (!state.activeJob || state.cancelling) return;
    const epoch = state.epoch;
    state.cancelling = true;
    updateControls();
    try {
      await api(`/api/jobs/${encodeURIComponent(state.activeJob)}/cancel`, { method: "POST" });
      if (epoch === state.epoch && state.busy) elements.message.textContent = "正在停止任务并清理未完成文件…";
    } catch (error) {
      if (epoch !== state.epoch) return;
      state.cancelling = false;
      updateControls();
      showNotice(error.message);
    }
  });

  elements.reveal.addEventListener("click", async () => {
    if (!state.file || state.stopped) return;
    const fileId = state.file.file_id;
    elements.reveal.disabled = true;
    try { await api("/api/reveal", { method: "POST", body: { file_id: fileId } }); }
    catch (error) { showNotice(error.message); }
    finally { updateControls(); }
  });

  elements.retry.addEventListener("click", checkEnvironment);
  elements.shutdown.addEventListener("click", async () => {
    if (state.busy || state.stopped) return;
    elements.shutdown.disabled = true;
    try {
      await api("/api/shutdown", { method: "POST" });
      state.stopped = true;
      state.ready = false;
      state.epoch += 1;
      clearTimeout(state.pollTimer);
      elements.environment.className = "environment-state";
      elements.environmentMessage.textContent = "工具已退出 · 已保存的视频保留在下载文件夹中";
      elements.retry.hidden = true;
      elements.shutdown.textContent = "已退出";
      elements.saveCopy.removeAttribute("href");
      elements.saveCopy.setAttribute("aria-disabled", "true");
      showNotice("本机服务已停止。可以关闭此标签页；再次使用时，重新打开启动文件。", true);
      updateControls();
    } catch (error) { showNotice(error.message); updateControls(); }
  });

  checkEnvironment();
})();
