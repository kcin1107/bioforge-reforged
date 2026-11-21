// Where a shell's diagnostics go (the Mac app: os.Logger; other hosts: a file or stderr). Messages are plain text, already public.
import Foundation

public protocol HostLog: Sendable {
    func info(_ category: String, _ message: String)
    func error(_ category: String, _ message: String)
}
