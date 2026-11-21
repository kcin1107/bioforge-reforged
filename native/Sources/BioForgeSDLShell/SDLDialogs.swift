// The two dialogs of the shell: a message box with buttons, and the folder chooser. The chooser's callback may run on another thread, so it
// only hands the path to the main loop as a user event.
import CSDL3
import Foundation

/// The user event type of a finished folder dialog (registered by the shell); `data1` is a C string from SDL_strdup, or nil when cancelled.
nonisolated(unsafe) var folderEventType: UInt32 = 0

private let folderDialogCallback: SDL_DialogFileCallback = { _, files, _ in
    var e = SDL_Event()
    e.user.type = folderEventType
    if let files, let first = files[0] { e.user.data1 = UnsafeMutableRawPointer(SDL_strdup(first)) }
    SDL_PushEvent(&e)
}

enum Dialogs {
    /// A message box; the index of the button pressed (the last one also answers Escape), or -1 when it could not be shown.
    @discardableResult
    static func box(_ message: String, _ info: String = "", buttons: [String] = ["OK"], window: OpaquePointer?, warning: Bool = true) -> Int {
        var data = buttons.enumerated().map { i, title in
            SDL_MessageBoxButtonData(flags: (i == 0 ? BF_BUTTON_RETURNKEY_DEFAULT : 0) | (i == buttons.count - 1 ? BF_BUTTON_ESCAPEKEY_DEFAULT : 0),
                                     buttonID: Int32(i), text: SDL_strdup(title))
        }
        defer { for b in data { SDL_free(UnsafeMutableRawPointer(mutating: b.text)) } }
        var pressed: Int32 = -1
        let shown = "BioForge".withCString { title in
            (info.isEmpty ? message : message + "\n\n" + info).withCString { text in
                data.withUnsafeMutableBufferPointer { b in
                    var box = SDL_MessageBoxData(flags: warning ? BF_MESSAGEBOX_WARNING : BF_MESSAGEBOX_INFORMATION, window: window, title: title, message: text,
                                                 numbuttons: Int32(b.count), buttons: b.baseAddress, colorScheme: nil)
                    return SDL_ShowMessageBox(&box, &pressed)
                }
            }
        }
        return shown ? Int(pressed) : -1
    }

    static func chooseFolder(window: OpaquePointer?) { SDL_ShowOpenFolderDialog(folderDialogCallback, nil, window, nil, false) }

    /// The path of a folder user event (frees it), nil when the dialog was cancelled.
    static func path(of event: SDL_Event) -> String? {
        guard let p = event.user.data1 else { return nil }
        defer { SDL_free(p) }
        return String(cString: p.assumingMemoryBound(to: CChar.self))
    }
}
