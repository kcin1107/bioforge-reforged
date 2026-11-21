// Diagnostics of the SDL shell go to stderr as "category: message".
import BioForgeHost
import Foundation

public struct SDLLog: HostLog {
    public init() {}
    public func info(_ category: String, _ message: String) { FileHandle.standardError.write(Data("\(category): \(message)\n".utf8)) }
    public func error(_ category: String, _ message: String) { info(category, message) }
}
