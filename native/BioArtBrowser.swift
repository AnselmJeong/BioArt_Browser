import AppKit
import WebKit

@main
struct BioArtMain {
    static func main() {
        let app = NSApplication.shared
        let delegate = AppDelegate()
        app.delegate = delegate
        app.setActivationPolicy(.regular)
        app.run()
        withExtendedLifetime(delegate) {}
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate, WKNavigationDelegate, WKScriptMessageHandler {
    var window: NSWindow!
    var web: WKWebView!
    var backend: Process?
    var workspace: URL!
    var port: Int = 0
    var readyName = "desktop-\(UUID().uuidString).json"
    var attempts = 0

    func applicationDidFinishLaunching(_ notification: Notification) {
        setupMenu()
        let saved = UserDefaults.standard.string(forKey: "workspace")
        let bundled = Bundle.main.url(forResource: "workspace", withExtension: "txt").flatMap { try? String(contentsOf: $0, encoding: .utf8) }.map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
        if let path = saved ?? bundled, FileManager.default.fileExists(atPath: path + "/data/catalog/catalog.sqlite") {
            workspace = URL(fileURLWithPath: path)
        } else {
            let panel = NSOpenPanel()
            panel.title = "BioArt 작업 폴더 선택"
            panel.message = "data/catalog/catalog.sqlite가 있는 BioArt_Browser 폴더를 선택하세요."
            panel.canChooseDirectories = true; panel.canChooseFiles = false
            guard panel.runModal() == .OK, let url = panel.url,
                  FileManager.default.fileExists(atPath: url.appendingPathComponent("data/catalog/catalog.sqlite").path) else {
                NSApp.terminate(nil); return
            }
            workspace = url
            UserDefaults.standard.set(url.path, forKey: "workspace")
        }
        let config = WKWebViewConfiguration()
        config.userContentController.add(self, name: "native")
        web = WKWebView(frame: .zero, configuration: config)
        web.navigationDelegate = self
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1510, height: 970), styleMask: [.titled,.closable,.miniaturizable,.resizable], backing: .buffered, defer: false)
        window.title = "BioArt Browser"
        window.minSize = NSSize(width: 1080, height: 700)
        window.contentView = web
        window.center(); window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        web.loadHTMLString("<html><body style='background:#f4f5ee;color:#456250;font:18px -apple-system;padding:100px'>BioArt 라이브러리를 여는 중입니다…<p style='font-size:13px'>macOS에서 외장 볼륨 접근을 요청하면 허용해 주세요.</p></body></html>", baseURL: nil)
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in self?.startBackend() }
    }

    func startBackend() {
        guard let resources = Bundle.main.resourceURL else { return }
        let process = Process()
        process.executableURL = resources.appendingPathComponent("backend/bioart-backend")
        process.arguments = ["serve", "--workspace", workspace.path, "--port", "0", "--ready-file", readyName]
        process.currentDirectoryURL = workspace
        var env = ProcessInfo.processInfo.environment
        env["BIOART_WORKSPACE"] = workspace.path
        env["PATH"] = "/usr/bin:/bin:/usr/sbin:/sbin"
        process.environment = env
        let logURL = workspace.appendingPathComponent("state/desktop.log")
        FileManager.default.createFile(atPath: logURL.path, contents: nil)
        if let log = try? FileHandle(forWritingTo: logURL) { process.standardOutput = log; process.standardError = log }
        do { try process.run(); backend = process; DispatchQueue.main.async { [weak self] in self?.pollReady() } }
        catch { DispatchQueue.main.async { [weak self] in self?.showError(error.localizedDescription) } }
    }

    func pollReady() {
        attempts += 1
        let ready = workspace.appendingPathComponent("state/" + readyName)
        if let data = try? Data(contentsOf: ready), let obj = try? JSONSerialization.jsonObject(with: data) as? [String:Any], let value = obj["port"] as? Int {
            port = value
            let url = URL(string: "http://127.0.0.1:\(port)/api/health")!
            URLSession.shared.dataTask(with: url) { [weak self] data, response, error in
                DispatchQueue.main.async {
                    guard let self else { return }
                    if (response as? HTTPURLResponse)?.statusCode == 200 {
                        self.web.load(URLRequest(url: URL(string: "http://127.0.0.1:\(self.port)/")!))
                    } else { self.schedulePoll() }
                }
            }.resume()
        } else { schedulePoll() }
    }

    func schedulePoll() {
        if attempts > 100 || backend?.isRunning == false { showError("라이브러리 서버를 시작하지 못했습니다. state/desktop.log를 확인하세요."); return }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.2) { [weak self] in self?.pollReady() }
    }

    func showError(_ message: String) {
        let alert = NSAlert(); alert.messageText = "BioArt Browser"; alert.informativeText = message
        alert.runModal()
    }

    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = action.request.url else { decisionHandler(.cancel); return }
        if url.scheme == "about" { decisionHandler(.allow); return }
        if url.host == "127.0.0.1", url.port == port {
            if url.path.hasPrefix("/api/exports/") {
                let name = url.lastPathComponent
                let target = workspace.appendingPathComponent("exports/" + name)
                NSWorkspace.shared.activateFileViewerSelecting([target]); decisionHandler(.cancel)
            } else { decisionHandler(.allow) }
        } else {
            if ["https","http"].contains(url.scheme ?? "") { NSWorkspace.shared.open(url) }
            decisionHandler(.cancel)
        }
    }

    func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) {
        guard message.frameInfo.isMainFrame, message.frameInfo.securityOrigin.host == "127.0.0.1",
              message.frameInfo.securityOrigin.port == port,
              let data = message.body as? [String:String], data["action"] == "reveal", let path = data["path"] else { return }
        let target = URL(fileURLWithPath: path).resolvingSymlinksInPath()
        let allowed = workspace.appendingPathComponent("exports").resolvingSymlinksInPath().path + "/"
        guard target.path.hasPrefix(allowed), FileManager.default.fileExists(atPath: target.path) else { return }
        NSWorkspace.shared.activateFileViewerSelecting([target])
    }

    func setupMenu() {
        let main = NSMenu(); let item = NSMenuItem(); main.addItem(item)
        let app = NSMenu(); app.addItem(withTitle: "BioArt Browser 종료", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q"); item.submenu = app
        let editItem = NSMenuItem(); main.addItem(editItem); let edit = NSMenu(title:"편집")
        for (title,action,key) in [("실행 취소","undo:","z"),("오려두기","cut:","x"),("복사","copy:","c"),("붙여넣기","paste:","v"),("모두 선택","selectAll:","a")] { edit.addItem(withTitle: title, action: Selector(action), keyEquivalent: key) }
        editItem.submenu = edit
        NSApp.mainMenu = main
    }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
    func applicationWillTerminate(_ notification: Notification) {
        backend?.terminate()
        if let workspace { try? FileManager.default.removeItem(at: workspace.appendingPathComponent("state/" + readyName)) }
    }
}
