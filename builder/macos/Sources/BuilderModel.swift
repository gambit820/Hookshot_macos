import AppKit
import Darwin
import Foundation
import UniformTypeIdentifiers

/// Codes match nx2/make_game.py LANGUAGES. The build is told the code, not the name.
struct Language: Identifiable, Hashable {
    let code: String
    let name: String
    var id: String { code }

    static let all: [Language] = [
        Language(code: "en-US", name: "English (US)"),
        Language(code: "en-GB", name: "English (UK)"),
        Language(code: "fr", name: "French (France)"),
        Language(code: "fr-CA", name: "French (Canada)"),
        Language(code: "de", name: "German"),
        Language(code: "it", name: "Italian"),
        Language(code: "es", name: "Spanish (Spain)"),
        Language(code: "es-419", name: "Spanish (Latin America)"),
        Language(code: "pt-BR", name: "Portuguese (Brazil)"),
        Language(code: "nl", name: "Dutch"),
        Language(code: "pl", name: "Polish"),
        Language(code: "ru", name: "Russian"),
        Language(code: "ja", name: "Japanese"),
        Language(code: "ko", name: "Korean"),
        Language(code: "zh-Hans", name: "Chinese (Simplified)"),
        Language(code: "zh-Hant", name: "Chinese (Traditional)"),
    ]
}

/// A 16 GB Mac loses the device at the game's own default. 9400 still holds the 2.4 GB pool.
/// Larger Macs keep the game's usual amount. hookshot_builder.py apple_play_env is the same rule.
let appleMemoryMB = "9400"
let appleMemoryLimit: UInt64 = 18 * 1024 * 1024 * 1024

private let launcherKeys = [
    "DYLD_LIBRARY_PATH", "VK_DRIVER_FILES", "VK_ICD_FILENAMES",
    "MVK_CONFIG_USE_METAL_ARGUMENT_BUFFERS", "HOS_MEMORY_MB", "HOOKSHOT_NO_UPDATE_CHECK",
]

@MainActor
final class BuilderModel: ObservableObject {
    static let shared = BuilderModel()

    @Published var nup = ""
    @Published var output = "~/Games/Hookshot"
    @Published var language = "en-US"
    @Published var status = ""
    @Published var log = ""
    @Published var building = false
    @Published var canPlay = false

    private var ready = false
    private var loaded = false
    private var checkGeneration = 0
    private var buildProcess: Process?
    private var pump: BuildPump?
    private var lastError: String?

    func appear() {
        guard !loaded else { return }
        loaded = true
        let opened = nup.trimmingCharacters(in: .whitespacesAndNewlines)
        let cfg = BuilderConfig.load()
        nup = opened.isEmpty ? (cfg["nup"] ?? "") : opened
        output = cfg["out"] ?? "~/Games/Hookshot"
        let saved = cfg["language"] ?? "en-US"
        language = Language.all.contains(where: { $0.code == saved }) ? saved : "en-US"
        ready = true
        save()
        refreshPlay()
        if FileManager.default.fileExists(atPath: expanded(nup)) {
            checkVersion()
        } else if !toolsPresent() {
            noteMissingTools()
        } else if canPlay {
            status = "Ready to play."
        } else {
            status = "Choose your .nup, then press Build."
        }
    }

    func useNup(_ path: String) {
        nup = path
        save()
        checkVersion()
    }

    func commitNup() {
        useNup(nup.trimmingCharacters(in: .whitespacesAndNewlines))
    }

    func save() {
        guard ready else { return }
        BuilderConfig.save(["nup": nup, "out": output, "language": language])
    }

    func refreshPlay() {
        canPlay = gameExecutable(in: expanded(output)) != nil
    }

    func pickNup() {
        let panel = NSOpenPanel()
        panel.prompt = "Choose"
        panel.message = "Choose your .nup"
        panel.canChooseFiles = true
        panel.canChooseDirectories = false
        panel.allowsMultipleSelection = false
        if let type = UTType(filenameExtension: "nup") {
            panel.allowedContentTypes = [type]
        }
        panel.allowsOtherFileTypes = true
        if panel.runModal() == .OK, let url = panel.url {
            useNup(url.path)
        }
    }

    func pickOutput() {
        let panel = NSOpenPanel()
        panel.prompt = "Choose"
        panel.message = "Where to save the game"
        panel.canChooseFiles = false
        panel.canChooseDirectories = true
        panel.canCreateDirectories = true
        panel.allowsMultipleSelection = false
        if panel.runModal() == .OK, let url = panel.url {
            output = url.path
            save()
            refreshPlay()
        }
    }

    func takeDrop(_ providers: [NSItemProvider]) -> Bool {
        let wanted = providers.filter { $0.hasItemConformingToTypeIdentifier(UTType.fileURL.identifier) }
        guard !wanted.isEmpty else { return false }
        for provider in wanted {
            provider.loadItem(forTypeIdentifier: UTType.fileURL.identifier, options: nil) { item, _ in
                let path: String?
                if let url = item as? URL {
                    path = url.path
                } else if let data = item as? Data, let url = URL(dataRepresentation: data, relativeTo: nil) {
                    path = url.path
                } else {
                    path = nil
                }
                guard let path, path.lowercased().hasSuffix(".nup") else { return }
                Task { @MainActor in
                    BuilderModel.shared.useNup(path)
                }
            }
        }
        return true
    }

    func build() {
        guard !building else { return }
        let nupPath = expanded(nup.trimmingCharacters(in: .whitespacesAndNewlines))
        let outPath = expanded(output.trimmingCharacters(in: .whitespacesAndNewlines))
        guard FileManager.default.fileExists(atPath: nupPath) else {
            alert("Choose your game's .nup file.")
            return
        }
        guard !outPath.isEmpty else {
            alert("Choose a folder to save the game to.")
            return
        }
        guard let root = sourceRoot() else {
            alert("The Hookshot source was not found beside this app.")
            return
        }
        save()
        building = true
        log = ""
        lastError = nil
        status = "Building..."
        let code = language
        Task.detached {
            let python: String?
            do {
                python = try PythonTool.locate(root: root)
            } catch {
                let message = error.localizedDescription
                await MainActor.run {
                    BuilderModel.shared.failSetup(message)
                }
                return
            }
            await MainActor.run {
                guard let python else {
                    BuilderModel.shared.failSetup("Homebrew Python 3.11 or newer is needed to build. brew install python")
                    return
                }
                BuilderModel.shared.startBuild(python: python, root: root, nup: nupPath, out: outPath, language: code)
            }
        }
    }

    func stopBuild() {
        guard building else { return }
        status = "Stopping..."
        buildProcess?.terminate()
    }

    func play() {
        let folder = expanded(output.trimmingCharacters(in: .whitespacesAndNewlines))
        guard let exe = gameExecutable(in: folder) else {
            alert("No built game in that folder yet.")
            return
        }
        // The app in the game folder is for the next double-click. This start is the binary itself, in its own session,
        // so closing the builder does not close the game.
        _ = writeGameApp(folder: folder)
        if launchDetached(exe: exe, folder: folder, env: playEnvironment()) {
            status = "Starting the game."
        } else {
            alert("The game could not be started.")
        }
    }

    func checkVersion() {
        let path = expanded(nup.trimmingCharacters(in: .whitespacesAndNewlines))
        guard FileManager.default.fileExists(atPath: path) else { return }
        guard let root = sourceRoot() else {
            status = "The Hookshot source was not found beside this app."
            return
        }
        checkGeneration += 1
        let generation = checkGeneration
        status = "Checking the game version..."
        Task.detached {
            guard let python = PythonTool.existing(root: root) else {
                await MainActor.run {
                    if generation == BuilderModel.shared.checkGeneration {
                        BuilderModel.shared.status = "Press Build to set up Python, then the version is checked."
                    }
                }
                return
            }
            let said = PythonTool.check(python: python, root: root, nup: path)
            await MainActor.run {
                if generation == BuilderModel.shared.checkGeneration {
                    BuilderModel.shared.status = said
                }
            }
        }
    }

    fileprivate func failSetup(_ message: String) {
        building = false
        status = message
        alert(message)
    }

    fileprivate func startBuild(python: String, root: URL, nup: String, out: String, language: String) {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: python)
        process.arguments = [
            "-I", "-u", "-X", "utf8", root.appendingPathComponent("nx2/make_game.py").path,
            "--nup", nup, "--out", out, "--language", language,
        ]
        process.currentDirectoryURL = root
        process.environment = buildEnvironment(root: root)
        process.standardInput = FileHandle.nullDevice
        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = pipe
        do {
            try process.run()
        } catch {
            building = false
            status = "Could not start the build (\(error.localizedDescription))."
            alert(status)
            return
        }
        buildProcess = process
        let started = BuildPump(handle: pipe.fileHandleForReading, process: process)
        pump = started
        started.start()
    }

    fileprivate func appendLog(_ line: String) {
        log += line + "\n"
        if line.hasPrefix("@@stage ") {
            let parts = line.split(separator: " ", maxSplits: 2, omittingEmptySubsequences: false)
            if let last = parts.last, !last.isEmpty {
                status = String(last)
            }
        } else if line.hasPrefix("@@error ") {
            let text = String(line.dropFirst("@@error ".count))
            lastError = text
            status = text
        }
    }

    fileprivate func buildFinished(_ code: Int32) {
        building = false
        buildProcess = nil
        pump = nil
        if code == 0 {
            status = "Your game is ready."
            lastError = nil
            _ = writeGameApp(folder: expanded(output))
            refreshPlay()
        } else if status == "Stopping..." || lastError == nil || lastError?.isEmpty == true {
            status = "The build stopped."
        } else if let lastError {
            status = lastError
        }
    }

    private func writeGameApp(folder: String) -> URL? {
        guard let exe = gameExecutable(in: folder) else { return nil }
        let app = URL(fileURLWithPath: folder, isDirectory: true).appendingPathComponent("Hookshot.app", isDirectory: true)
        let macOS = app.appendingPathComponent("Contents/MacOS", isDirectory: true)
        let play = macOS.appendingPathComponent("play")
        do {
            try FileManager.default.createDirectory(at: macOS, withIntermediateDirectories: true)
            try launcherScript(exe: exe, folder: folder).write(to: play, atomically: true, encoding: .utf8)
            try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: play.path)
            try gamePlist.write(to: app.appendingPathComponent("Contents/Info.plist"), atomically: true, encoding: .utf8)
        } catch {
            return nil
        }
        let sign = Process()
        sign.executableURL = URL(fileURLWithPath: "/usr/bin/codesign")
        sign.arguments = ["-s", "-", "--force", app.path]
        sign.standardOutput = FileHandle.nullDevice
        sign.standardError = FileHandle.nullDevice
        try? sign.run()
        sign.waitUntilExit()
        return app
    }

    private func launcherScript(exe: String, folder: String) -> String {
        let env = playEnvironment()
        var lines = ["#!/bin/bash", "set -eu", "cd \"$(dirname \"$0\")/../../..\""]
        for key in launcherKeys {
            if let value = env[key] {
                lines.append("export \(key)=\(shellQuote(value))")
            }
        }
        lines.append("exec \(shellQuote("./" + relativeGamePath(exe: exe, folder: folder)))")
        return lines.joined(separator: "\n") + "\n"
    }

    private func alert(_ text: String) {
        let dialog = NSAlert()
        dialog.messageText = "Hookshot"
        dialog.informativeText = text
        dialog.alertStyle = .warning
        dialog.runModal()
    }

    private func noteMissingTools() {
        status = "MoltenVK was not found. Install it with: brew install molten-vk vulkan-headers vulkan-loader sdl2 ffmpeg pkg-config"
    }

    private func toolsPresent() -> Bool {
        FileManager.default.fileExists(atPath: brewPrefix() + "/etc/vulkan/icd.d/MoltenVK_icd.json")
    }
}

/// Reads the build's stdout off the main thread and hands each line back.
private final class BuildPump: @unchecked Sendable {
    let handle: FileHandle
    let process: Process

    init(handle: FileHandle, process: Process) {
        self.handle = handle
        self.process = process
    }

    func start() {
        DispatchQueue.global(qos: .userInitiated).async { [self] in
            var pending = Data()
            while true {
                let chunk = self.handle.availableData
                if chunk.isEmpty { break }
                pending.append(chunk)
                while let newline = pending.firstIndex(of: 0x0A) {
                    let start = pending.startIndex
                    let lineData = pending.subdata(in: start..<newline)
                    pending.removeSubrange(start...newline)
                    let decoded = String(decoding: lineData, as: UTF8.self)
                    let line = decoded.hasSuffix("\r") ? String(decoded.dropLast()) : decoded
                    Task { @MainActor in
                        BuilderModel.shared.appendLog(line)
                    }
                }
            }
            if !pending.isEmpty {
                let line = String(decoding: pending, as: UTF8.self)
                Task { @MainActor in
                    BuilderModel.shared.appendLog(line)
                }
            }
            self.process.waitUntilExit()
            let code = self.process.terminationStatus
            Task { @MainActor in
                BuilderModel.shared.buildFinished(code)
            }
        }
    }
}

/// The same ini the earlier window wrote, so a path chosen before still shows up.
private enum BuilderConfig {
    static var url: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/Hookshot/builder.ini")
    }

    static func load() -> [String: String] {
        guard let text = try? String(contentsOf: url, encoding: .utf8) else { return [:] }
        var cfg: [String: String] = [:]
        for line in text.split(separator: "\n", omittingEmptySubsequences: false) {
            let raw = String(line)
            guard let eq = raw.firstIndex(of: "=") else { continue }
            cfg[String(raw[..<eq])] = String(raw[raw.index(after: eq)...])
        }
        return cfg
    }

    static func save(_ values: [String: String]) {
        let keys = ["nup", "out", "language"]
        let text = keys.map { "\($0)=\(values[$0] ?? "")\n" }.joined()
        try? FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        try? text.write(to: url, atomically: true, encoding: .utf8)
    }
}

private enum PythonTool {
    static func locate(root: URL) throws -> String? {
        if let found = existing(root: root) { return found }
        guard let host = hostPython() else { return nil }
        let cache = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".cache/hookshot-builder/py")
        let python = cache.appendingPathComponent("bin/python3").path
        try FileManager.default.createDirectory(at: cache.deletingLastPathComponent(), withIntermediateDirectories: true)
        try run(host, ["-m", "venv", cache.path])
        try run(python, ["-m", "pip", "install", "-r", root.appendingPathComponent("requirements.txt").path])
        return imports(python, "zstandard") ? python : nil
    }

    static func existing(root: URL) -> String? {
        var candidates: [String] = []
        if let forced = ProcessInfo.processInfo.environment["HOOKSHOT_PYTHON"], !forced.isEmpty {
            candidates.append(forced)
        }
        candidates.append(root.appendingPathComponent("work/py/bin/python3").path)
        candidates.append(FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".cache/hookshot-builder/py/bin/python3").path)
        return candidates.first { FileManager.default.isExecutableFile(atPath: $0) && imports($0, "zstandard") }
    }

    static func check(python: String, root: URL, nup: String) -> String {
        let script = root.appendingPathComponent("nx2/make_game.py").path
        let output = capture(python, ["-I", script, "--check", "--nup", nup], cwd: root)
        let said = output.out.split(separator: "\n", omittingEmptySubsequences: false).compactMap { reported(String($0)) }.filter { !$0.isEmpty }
        if let last = said.last { return last }
        let err = output.err.split(separator: "\n").map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty }
        return err.last ?? "The version could not be read."
    }

    private static func hostPython() -> String? {
        let paths = [
            "/opt/homebrew/bin/python3.13", "/opt/homebrew/bin/python3.12", "/usr/local/bin/python3.13",
            "/opt/homebrew/bin/python3", "/usr/local/bin/python3",
        ]
        for path in paths where FileManager.default.isExecutableFile(atPath: path) {
            let output = capture(path, ["-c", "import sys; print(sys.version_info[0], sys.version_info[1])"], cwd: nil)
            let numbers = output.out.split(whereSeparator: { $0.isWhitespace }).compactMap { Int($0) }
            if numbers.count >= 2, (numbers[0], numbers[1]) >= (3, 11) {
                return path
            }
        }
        return nil
    }

    private static func imports(_ python: String, _ module: String) -> Bool {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: python)
        process.arguments = ["-c", "import " + module]
        process.standardOutput = FileHandle.nullDevice
        process.standardError = FileHandle.nullDevice
        do {
            try process.run()
        } catch {
            return false
        }
        process.waitUntilExit()
        return process.terminationStatus == 0
    }

    @discardableResult
    private static func run(_ exe: String, _ args: [String]) throws -> String {
        let output = capture(exe, args, cwd: nil)
        if output.code != 0 {
            let tail = output.err.split(separator: "\n").suffix(3).joined(separator: " ")
            throw SetupError(message: tail.isEmpty ? "exit \(output.code)" : tail)
        }
        return output.out
    }

    private static func capture(_ exe: String, _ args: [String], cwd: URL?) -> (out: String, err: String, code: Int32) {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: exe)
        process.arguments = args
        if let cwd { process.currentDirectoryURL = cwd }
        let out = Pipe()
        let err = Pipe()
        process.standardOutput = out
        process.standardError = err
        do {
            try process.run()
        } catch {
            return ("", error.localizedDescription, 1)
        }
        process.waitUntilExit()
        let outText = String(data: out.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
        let errText = String(data: err.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
        return (outText, errText, process.terminationStatus)
    }

    private static func reported(_ line: String) -> String? {
        if line.hasPrefix("@@error ") { return String(line.dropFirst("@@error ".count)) }
        if line.hasPrefix("@@check ") {
            let parts = line.split(separator: " ", maxSplits: 2, omittingEmptySubsequences: true).map(String.init)
            return parts.count == 3 ? parts[2] : ""
        }
        return nil
    }
}

private struct SetupError: LocalizedError {
    let message: String
    var errorDescription: String? { message }
}

private func expanded(_ path: String) -> String {
    (path as NSString).expandingTildeInPath
}

/// Checkout: the app sits in builder/macos. A shared folder: the app sits beside source/.
private func sourceRoot() -> URL? {
    let parent = Bundle.main.bundleURL.deletingLastPathComponent()
    let candidates = [
        parent.deletingLastPathComponent().deletingLastPathComponent(),
        parent.appendingPathComponent("source"),
    ]
    for root in candidates {
        if FileManager.default.fileExists(atPath: root.appendingPathComponent("nx2/make_game.py").path) {
            return root.standardizedFileURL
        }
    }
    return nil
}

private func brewPrefix() -> String {
    for prefix in ["/opt/homebrew", "/usr/local"] where FileManager.default.fileExists(atPath: prefix + "/lib") {
        return prefix
    }
    return "/opt/homebrew"
}

private func memoryBytes() -> UInt64 {
    let process = Process()
    process.executableURL = URL(fileURLWithPath: "/usr/sbin/sysctl")
    process.arguments = ["-n", "hw.memsize"]
    let pipe = Pipe()
    process.standardOutput = pipe
    process.standardError = FileHandle.nullDevice
    do {
        try process.run()
    } catch {
        return 0
    }
    process.waitUntilExit()
    let text = (String(data: pipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? "")
        .trimmingCharacters(in: .whitespacesAndNewlines)
    return UInt64(text) ?? 0
}

/// What Play adds on this Mac. A value already set is left as it is. Names starting with HOOKSHOT_ (and the AppImage's
/// own variables) are not passed on, except the update check, which is turned off after that.
private func playEnvironment() -> [String: String] {
    let drop = ["HOOKSHOT_", "PYTHON", "APPDIR", "APPIMAGE", "ARGV0", "OWD"]
    var env: [String: String] = [:]
    for (key, value) in ProcessInfo.processInfo.environment {
        if drop.contains(where: { key.hasPrefix($0) }) || key == "LD_LIBRARY_PATH" { continue }
        env[key] = value
    }
    let prefix = brewPrefix()
    let icd = prefix + "/etc/vulkan/icd.d/MoltenVK_icd.json"
    if FileManager.default.fileExists(atPath: icd), env["VK_DRIVER_FILES"] == nil, env["VK_ICD_FILENAMES"] == nil {
        env["VK_DRIVER_FILES"] = icd
    }
    let lib = prefix + "/lib"
    var isDir: ObjCBool = false
    if FileManager.default.fileExists(atPath: lib, isDirectory: &isDir), isDir.boolValue {
        let current = env["DYLD_LIBRARY_PATH"] ?? ""
        if !current.split(separator: ":").contains(Substring(lib)) {
            env["DYLD_LIBRARY_PATH"] = current.isEmpty ? lib : lib + ":" + current
        }
    }
    if env["MVK_CONFIG_USE_METAL_ARGUMENT_BUFFERS"] == nil {
        env["MVK_CONFIG_USE_METAL_ARGUMENT_BUFFERS"] = "1"
    }
    let size = memoryBytes()
    if size > 0, size <= appleMemoryLimit, env["HOS_MEMORY_MB"] == nil {
        env["HOS_MEMORY_MB"] = appleMemoryMB
    }
    env["HOOKSHOT_NO_UPDATE_CHECK"] = "1"
    return env
}

private func buildEnvironment(root: URL) -> [String: String] {
    var env = ProcessInfo.processInfo.environment
    if env["HOOKSHOT_VMA_HEADERS"] == nil {
        for rel in ["work/vma", "third_party/vma"] {
            let dir = root.appendingPathComponent(rel)
            if FileManager.default.fileExists(atPath: dir.appendingPathComponent("include/vk_mem_alloc.h").path) {
                env["HOOKSHOT_VMA_HEADERS"] = dir.path
                break
            }
        }
    }
    return env
}

private func gameExecutable(in folder: String) -> String? {
    for rel in ["hookshot", "bin/hookshot"] {
        let path = (folder as NSString).appendingPathComponent(rel)
        let image = (folder as NSString).appendingPathComponent("image.bin")
        if FileManager.default.isExecutableFile(atPath: path), FileManager.default.fileExists(atPath: image) {
            return path
        }
    }
    return nil
}

private func relativeGamePath(exe: String, folder: String) -> String {
    let root = folder.hasSuffix("/") ? folder : folder + "/"
    if exe.hasPrefix(root) {
        return String(exe.dropFirst(root.count))
    }
    return "hookshot"
}

private func shellQuote(_ value: String) -> String {
    "'" + value.replacingOccurrences(of: "'", with: "'\\''") + "'"
}

/// Start the game in a new session, in its own folder. The builder can quit without taking the game with it.
private func launchDetached(exe: String, folder: String, env: [String: String]) -> Bool {
    var attr: posix_spawnattr_t?
    if posix_spawnattr_init(&attr) != 0 { return false }
    defer { posix_spawnattr_destroy(&attr) }
    if posix_spawnattr_setflags(&attr, Int16(POSIX_SPAWN_SETSID)) != 0 { return false }

    var actions: posix_spawn_file_actions_t?
    if posix_spawn_file_actions_init(&actions) != 0 { return false }
    defer { posix_spawn_file_actions_destroy(&actions) }

    var pid: pid_t = 0
    let exeC = strdup(exe)
    defer { free(exeC) }
    var argv: [UnsafeMutablePointer<CChar>?] = [exeC, nil]
    var envStorage: [UnsafeMutablePointer<CChar>?] = env.map { strdup("\($0.key)=\($0.value)") }
    envStorage.append(nil)
    defer {
        for item in envStorage { free(item) }
    }

    let rc: Int32 = folder.withCString { cwd in
        if posix_spawn_file_actions_addchdir_np(&actions, cwd) != 0 { return -1 }
        return posix_spawn(&pid, exe, &actions, &attr, &argv, &envStorage)
    }
    return rc == 0
}

private let gamePlist = """
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>CFBundleDevelopmentRegion</key>
	<string>en</string>
	<key>CFBundleDisplayName</key>
	<string>Hookshot</string>
	<key>CFBundleExecutable</key>
	<string>play</string>
	<key>CFBundleIdentifier</key>
	<string>io.github.NotRexed.Hookshot</string>
	<key>CFBundleInfoDictionaryVersion</key>
	<string>6.0</string>
	<key>CFBundleName</key>
	<string>Hookshot</string>
	<key>CFBundlePackageType</key>
	<string>APPL</string>
	<key>CFBundleShortVersionString</key>
	<string>1.0</string>
	<key>CFBundleVersion</key>
	<string>1</string>
	<key>LSMinimumSystemVersion</key>
	<string>14.0</string>
	<key>NSHighResolutionCapable</key>
	<true/>
</dict>
</plist>
"""
