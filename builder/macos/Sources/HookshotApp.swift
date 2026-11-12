import AppKit
import SwiftUI
import UniformTypeIdentifiers

@main
struct HookshotApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var appDelegate

    var body: some Scene {
        Window("Hookshot Builder", id: "main") {
            BuilderView(model: .shared)
        }
        .defaultSize(width: 720, height: 560)
        .windowResizability(.contentMinSize)
        .commands {
            CommandGroup(replacing: .newItem) {}
        }
    }
}

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        for arg in CommandLine.arguments.dropFirst() where !arg.hasPrefix("-psn") && arg.lowercased().hasSuffix(".nup") {
            let path = (arg as NSString).expandingTildeInPath
            if FileManager.default.fileExists(atPath: path) {
                BuilderModel.shared.useNup(path)
            }
        }
    }

    func application(_ application: NSApplication, open urls: [URL]) {
        for url in urls where url.pathExtension.lowercased() == "nup" {
            BuilderModel.shared.useNup(url.path)
        }
    }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        BuilderModel.shared.stopBuild()
        return .terminateNow
    }
}

struct BuilderView: View {
    @ObservedObject var model: BuilderModel

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("Your .nup stays on this Mac. The build only reads it.")
                .font(.callout)
                .foregroundStyle(.secondary)

            VStack(alignment: .leading, spacing: 10) {
                LabeledContent("Game package") {
                    HStack(spacing: 8) {
                        TextField("Your .nup file", text: $model.nup)
                            .truncationMode(.middle)
                            .onSubmit { model.commitNup() }
                        Button("Browse…") { model.pickNup() }
                    }
                }
                LabeledContent("Save the game to") {
                    HStack(spacing: 8) {
                        TextField("~/Games/Hookshot", text: $model.output)
                            .truncationMode(.middle)
                        Button("Choose…") { model.pickOutput() }
                    }
                }
                LabeledContent("Language") {
                    Picker("Language", selection: $model.language) {
                        ForEach(Language.all) { item in
                            Text(item.name).tag(item.code)
                        }
                    }
                    .labelsHidden()
                    .frame(maxWidth: 280, alignment: .leading)
                }
            }

            Text(model.status)
                .font(.callout)
                .foregroundStyle(.secondary)
                .frame(maxWidth: .infinity, alignment: .leading)
                .lineLimit(3)

            ZStack(alignment: .topLeading) {
                LogView(text: model.log)
                if model.log.isEmpty {
                    Text("Build progress appears here.")
                        .foregroundStyle(.tertiary)
                        .padding(12)
                        .allowsHitTesting(false)
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .clipShape(RoundedRectangle(cornerRadius: 6))
            .overlay(RoundedRectangle(cornerRadius: 6).stroke(Color(nsColor: .separatorColor)))

            HStack {
                Spacer()
                Button("Play") { model.play() }
                    .disabled(!model.canPlay || model.building)
                if model.building {
                    Button("Stop") { model.stopBuild() }
                        .keyboardShortcut(.cancelAction)
                } else {
                    Button("Build") { model.build() }
                        .keyboardShortcut(.defaultAction)
                }
            }
        }
        .padding(20)
        .frame(minWidth: 640, minHeight: 480)
        .onAppear { model.appear() }
        .onChange(of: model.nup) { _, _ in model.save() }
        .onChange(of: model.output) { _, _ in
            model.save()
            model.refreshPlay()
        }
        .onChange(of: model.language) { _, _ in model.save() }
        .onDrop(of: [.fileURL], isTargeted: nil) { model.takeDrop($0) }
    }
}

/// The build log. Appending keeps a long compile from redrawing the lines already on screen.
struct LogView: NSViewRepresentable {
    var text: String

    func makeCoordinator() -> Coordinator { Coordinator() }

    func makeNSView(context: Context) -> NSScrollView {
        context.coordinator.shown = 0
        let scroll = NSTextView.scrollableTextView()
        guard let textView = scroll.documentView as? NSTextView else { return scroll }
        textView.isEditable = false
        textView.isSelectable = true
        textView.isRichText = false
        textView.font = logFont
        textView.textColor = .labelColor
        textView.backgroundColor = .textBackgroundColor
        textView.drawsBackground = true
        textView.textContainerInset = NSSize(width: 8, height: 8)
        textView.textContainer?.widthTracksTextView = true
        textView.isAutomaticQuoteSubstitutionEnabled = false
        textView.isAutomaticDashSubstitutionEnabled = false
        textView.isAutomaticTextReplacementEnabled = false
        return scroll
    }

    func updateNSView(_ scroll: NSScrollView, context: Context) {
        guard let textView = scroll.documentView as? NSTextView else { return }
        let shown = context.coordinator.shown
        if text.count < shown {
            textView.string = text
            context.coordinator.shown = text.count
            return
        }
        guard text.count > shown else { return }
        let piece = String(text[text.index(text.startIndex, offsetBy: shown)...])
        let atEnd = visibleMaxY(scroll) >= textView.bounds.height - 24
        textView.textStorage?.append(NSAttributedString(string: piece, attributes: [
            .font: logFont,
            .foregroundColor: NSColor.labelColor,
        ]))
        context.coordinator.shown = text.count
        if atEnd {
            textView.scrollToEndOfDocument(nil)
        }
    }

    final class Coordinator {
        var shown = 0
    }
}

private let logFont = NSFont.monospacedSystemFont(ofSize: 12, weight: .regular)

private func visibleMaxY(_ scroll: NSScrollView) -> CGFloat {
    scroll.contentView.bounds.maxY
}
