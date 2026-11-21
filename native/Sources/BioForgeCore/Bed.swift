// SALSA figure definition (BODY/<TYPE>.BED, text), mirrors re/formats/bed.py.
//
// Lines "KEY = file[+file...]  ; comment"; keys are case-insensitive (REAL, SKIN, SKEL, MOTN, LIST), a later duplicate
// key replaces an earlier one. File names are resolved case-insensitively inside BODY/ by the caller.
import Foundation

public struct Bed: Sendable {
    public let entries: [String: [String]]

    public init(text: String) {
        var out: [String: [String]] = [:]
        for line in text.split(whereSeparator: \.isNewline) {
            let s = Substring(line.drop { $0.isWhitespace })
            let key = s.prefix { $0.isLetter || $0.isNumber || $0 == "_" }
            var rest = s.dropFirst(key.count).drop { $0.isWhitespace }
            guard !key.isEmpty, rest.first == "=" else { continue }
            rest = rest.dropFirst().drop { $0.isWhitespace }
            let val = rest.prefix { !$0.isWhitespace && $0 != ";" }
            if !val.isEmpty { out[key.uppercased()] = val.split(separator: "+").map(String.init) }
        }
        entries = out
    }

    public init(data: [UInt8]) { self.init(text: String(String.UnicodeScalarView(data.map { Unicode.Scalar($0) }))) }
}
