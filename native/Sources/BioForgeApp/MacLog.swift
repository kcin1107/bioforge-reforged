// os.Logger behind the host layer's HostLog.
import BioForgeHost
import OSLog

/// os.Logger behind HostLog: one logger per category, messages public.
struct OSLogHostLog: HostLog {
    private func logger(_ category: String) -> Logger { Logger(subsystem: "BioForge", category: category) }
    func info(_ category: String, _ message: String) { logger(category).info("\(message, privacy: .public)") }
    func error(_ category: String, _ message: String) { logger(category).error("\(message, privacy: .public)") }
}
