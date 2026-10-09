import Cocoa
import WebKit

final class DownloaderApp: NSObject, NSApplicationDelegate, NSWindowDelegate, WKNavigationDelegate {
    private var window: NSWindow!
    private var webView: WKWebView!
    private let service = Process()
    private let output = Pipe()
    private var log = ""
    private var localURL: URL?
    private var stopping = false

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        let menu = NSMenu()
        let appMenu = NSMenu()
        appMenu.addItem(withTitle: "退出 X视频下载器", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        let appItem = NSMenuItem(); appItem.submenu = appMenu; menu.addItem(appItem)
        let editMenu = NSMenu(title: "编辑")
        for (title, action, key) in [("剪切", "cut:", "x"), ("复制", "copy:", "c"),
                                     ("粘贴", "paste:", "v"), ("全选", "selectAll:", "a")] {
            editMenu.addItem(withTitle: title, action: Selector(action), keyEquivalent: key)
        }
        let editItem = NSMenuItem(title: "编辑", action: nil, keyEquivalent: "")
        editItem.submenu = editMenu; menu.addItem(editItem); NSApp.mainMenu = menu
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 900, height: 720),
                          styleMask: [.titled, .closable, .miniaturizable, .resizable],
                          backing: .buffered, defer: false)
        window.title = "X视频下载器"
        window.minSize = NSSize(width: 800, height: 650)
        window.delegate = self
        webView = WKWebView(frame: window.contentView!.bounds)
        webView.autoresizingMask = [.width, .height]
        webView.navigationDelegate = self
        window.contentView = webView
        showStatus("正在启动下载器…", "正在准备下载窗口，请稍候。")
        window.center(); window.makeKeyAndOrderFront(nil); NSApp.activate(ignoringOtherApps: true)
        let engine = Bundle.main.resourceURL?.appendingPathComponent("engine/x-video-engine")
        let bundled = engine.map { FileManager.default.fileExists(atPath: $0.path) } ?? false
        let downloadDirectory: URL
        if bundled, let engine = engine {
            service.executableURL = engine
            service.currentDirectoryURL = engine.deletingLastPathComponent()
            var environment = ProcessInfo.processInfo.environment
            let tools = engine.deletingLastPathComponent().appendingPathComponent("_internal").path
            environment["PATH"] = tools + ":" + (environment["PATH"] ?? "/usr/bin:/bin:/usr/sbin:/sbin")
            service.environment = environment
            let preferred = UserDefaults.standard.string(forKey: "DownloadDirectory") ?? ""
            let path = (preferred as NSString).expandingTildeInPath
            downloadDirectory = path.hasPrefix("/") ? URL(fileURLWithPath: path, isDirectory: true)
                : FileManager.default.urls(for: .downloadsDirectory, in: .userDomainMask)[0]
                    .appendingPathComponent("X视频下载器", isDirectory: true)
        } else {
            let folder = Bundle.main.bundleURL.deletingLastPathComponent()
            let project = Bundle.main.object(forInfoDictionaryKey: "XVLProjectFolder") as? String ?? "下载器"
            guard !project.isEmpty, !project.contains("/"), !project.contains("..") else {
                fail("下载器文件夹名称无效。", detail: "请重新运行项目中的 build-mac-app.command。"); return
            }
            let source = folder.appendingPathComponent(project, isDirectory: true)
            let launcher = source.appendingPathComponent("start.command")
            guard FileManager.default.fileExists(atPath: launcher.path) else {
                fail("未找到下载组件。", detail: "请安装完整版本，或将开发版应用与「\(project)」文件夹放在一起。"); return
            }
            service.executableURL = URL(fileURLWithPath: "/bin/bash")
            service.arguments = [launcher.path]
            service.currentDirectoryURL = source
            downloadDirectory = folder.appendingPathComponent("视频", isDirectory: true)
            showStatus("正在启动本机下载服务…", "首次运行会自动安装所需组件，请稍候。")
        }
        service.arguments = (service.arguments ?? []) + ["--no-browser", "--port", "0", "--download-dir", downloadDirectory.path]
        service.standardOutput = output; service.standardError = output
        service.standardInput = FileHandle.nullDevice
        output.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            if data.isEmpty { handle.readabilityHandler = nil; return }
            let chunk = String(decoding: data, as: UTF8.self)
            DispatchQueue.main.async { self?.receive(chunk) }
        }
        service.terminationHandler = { [weak self] process in
            DispatchQueue.main.async {
                guard let self = self else { return }
                if self.stopping { NSApp.reply(toApplicationShouldTerminate: true) }
                else if process.terminationStatus != 0 {
                    self.fail("下载服务未能启动或已停止。", detail: self.log)
                } else { NSApp.terminate(nil) }
            }
        }
        do { try service.run() }
        catch { fail("无法启动下载器。", detail: "请重新安装完整版本。\n\(error.localizedDescription)") }
    }

    private func receive(_ chunk: String) {
        log = String((log + chunk).suffix(12000))
        guard localURL == nil,
              let range = log.range(of: #"http://127\.0\.0\.1:[0-9]+"#, options: .regularExpression),
              let url = URL(string: String(log[range]) + "/?native=1") else { return }
        localURL = url
        webView.load(URLRequest(url: url))
        print("X视频下载器窗口已连接：\(url.absoluteString)")
        fflush(stdout)
    }

    private func showStatus(_ title: String, _ detail: String) {
        webView.loadHTMLString("""
            <!doctype html><html lang="zh-CN"><meta charset="utf-8">
            <style>body{font:17px -apple-system;background:#f5f7fb;color:#17233a;padding:100px 60px;line-height:1.7}h1{font-size:26px}</style>
            <h1>\(title)</h1><p>\(detail)</p></html>
            """, baseURL: nil)
    }

    private func fail(_ message: String, detail: String) {
        let alert = NSAlert()
        alert.messageText = message; alert.informativeText = String(detail.suffix(2500))
        alert.addButton(withTitle: "关闭"); alert.runModal(); NSApp.terminate(nil)
    }

    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = action.request.url else { decisionHandler(.cancel); return }
        if url.absoluteString == "about:blank" { decisionHandler(.allow); return }
        if let local = localURL, url.scheme == "http", url.host == "127.0.0.1", url.port == local.port,
           url.user == nil, url.password == nil {
            if action.targetFrame == nil { webView.load(action.request); decisionHandler(.cancel) }
            else { decisionHandler(.allow) }
            return
        }
        if ["https", "http"].contains(url.scheme ?? "") { NSWorkspace.shared.open(url) }
        decisionHandler(.cancel)
    }

    func windowShouldClose(_ sender: NSWindow) -> Bool { NSApp.terminate(nil); return false }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        guard service.isRunning else { return .terminateNow }
        if !stopping {
            stopping = true
            showStatus("正在退出…", "正在停止下载并清理本次临时文件。")
            service.interrupt()
        }
        return .terminateLater
    }
}

let delegate = DownloaderApp()
NSApplication.shared.delegate = delegate
NSApplication.shared.run()
