// BioForge XMIDI music sequencer. Mirrors re/formats/xmi.py, music.py and musicseq.py:
// a fixed 120 Hz Miles timeline, song table transitions when the music task's update (30 Hz) sees the measure count (0x77) move,
// and the 0x74/0x75 loop and 0x78 branch controllers. Rendering is deliberately left to the app.
// The XMIDI layer as AIL runs it (musicseq.py docstring): events in file order, a 32-entry note queue whose notes end
// before a step's events, stop = note offs for the queued notes + sustain off where on (no all-notes-off), resume
// resends the cached controllers, bend and program, and entering at a branch marker sends no earlier state.
//
// Music level (options dialog, FUN_1100_0dc2(sfx, music)): `volume` (0...100, nil = unscaled) is the level in force and `setVolume`
// changes it. Level > 0 enables music: if no song is current it starts the options music (song 4, _OptionsMusic) or resumes the
// last requested one, then FUN_1198_1b62 sets the XMIDI relative volume min(level, 127); level 0 stops the music (MUSIC -4) and
// disables it, so requests are ignored until it is raised. AIL's relative volume is a percentage (the XMIDI layer every AIL driver
// shares): each channel volume controller (CC 7) is sent as min(127, v * rel / 100), and the current channel volumes are re-sent
// when the level changes (musicseq.py does the same).
//
// Arrangements: `MusicArrangement.generalMIDI` (songs 0..., transitions 258) is what the game plays with its MT-32 / AWE32
// drivers, `.adlib` (songs 128..., an empty entry falls back to the first arrangement; transitions 260) what it plays with its
// AdLib driver (AdLib.swift).
import Foundation

public struct MusicMIDIEvent: Sendable, Equatable {
    public let time: Double
    public let bytes: [UInt8]
    public init(time: Double, bytes: [UInt8]) { self.time = time; self.bytes = bytes }
}

public enum MusicArrangement: String, Sendable, CaseIterable { case generalMIDI, adlib }

public final class MusicLibrary: @unchecked Sendable {
    fileprivate static let songCount = 49
    private static let tableEntry = 261
    fileprivate let songs: [Song]
    fileprivate let table: [TransitionKey: [Int]]
    private let songData: [[UInt8]]
    private let transitions: [[UInt8]]
    fileprivate var songCache: [Int: Sequence] = [:]
    fileprivate var transitionCache: [Int: Sequence] = [:]

    public convenience init(game: GameFolder, arrangement: MusicArrangement = .generalMIDI) throws {
        try self.init(data: game.read("MUSIC/MUSIC.FLX"), arrangement: arrangement)
    }

    public init(data: [UInt8], arrangement: MusicArrangement = .generalMIDI) throws {
        let flex = try Flex(data: data)
        guard flex.entries.count > Self.tableEntry else { throw FormatError("MUSIC.FLX is missing its music table") }
        func entry(_ index: Int) -> [UInt8] { flex.bytes(flex.entries[index]) }
        let lines = entry(Self.tableEntry).split(separator: 10, omittingEmptySubsequences: false)
            .map { String(bytes: $0, encoding: .isoLatin1) ?? "" }
        guard lines.count >= Self.songCount else { throw FormatError("MUSIC.FLX song table has \(lines.count) rows") }
        var parsedSongs: [Song] = []
        var ids: [String: Int] = [:]
        for (index, line) in lines.prefix(Self.songCount).enumerated() {
            let fields = line.split(whereSeparator: \.isWhitespace)
            guard fields.count == 4, let measures = Int(fields[2]), let loop = Int(fields[3]) else {
                throw FormatError("bad MUSIC.FLX song row: \(line)")
            }
            let song = Song(file: String(fields[0]), measures: measures, loopMeasure: loop)
            parsedSongs.append(song); ids[song.file] = index
        }
        var parsedTable: [TransitionKey: [Int]] = [:]
        for line in lines.dropFirst(Self.songCount) {
            let fields = line.split(whereSeparator: \.isWhitespace)
            guard fields.count >= 3, fields[0].hasSuffix(".xmi"), fields[1].hasSuffix(".xmi"),
                  let from = ids[String(fields[0])], let to = ids[String(fields[1])] else { continue }
            var values: [Int] = []
            for field in fields.dropFirst(2) {
                let s = String(field), negative = s.hasPrefix("!")
                guard let value = Int(negative ? String(s.dropFirst()) : s) else { throw FormatError("bad MUSIC transition value: \(s)") }
                values.append(negative ? -value : value)
            }
            parsedTable[TransitionKey(from, to)] = values
        }
        songs = parsedSongs; table = parsedTable
        let adlib = arrangement == .adlib
        songData = try (0..<Self.songCount).map { index in
            let sequences = try XMIDI.sequences(entry(adlib && flex.entries[128 + index].size > 0 ? 128 + index : index))
            guard let first = sequences.first else { throw FormatError("MUSIC.FLX song \(index) has no XMIDI sequence") }
            return first
        }
        transitions = try XMIDI.sequences(entry(adlib ? 260 : 258))
    }

    fileprivate func song(_ id: Int) throws -> Sequence {
        guard songs.indices.contains(id) else { throw FormatError("MUSIC song id \(id) is outside 0...48") }
        if let cached = songCache[id] { return cached }
        let sequence = try Sequence(evnt: songData[id])
        songCache[id] = sequence
        return sequence
    }

    fileprivate func transition(_ reference: Int) throws -> Sequence {
        guard reference > 0, transitions.indices.contains(reference - 1) else { throw FormatError("MUSIC transition \(reference) is missing") }
        if let cached = transitionCache[reference] { return cached }
        let sequence = try Sequence(evnt: transitions[reference - 1])
        transitionCache[reference] = sequence
        return sequence
    }
}

public final class MusicSequencer {
    private let library: MusicLibrary
    private var main: Player?
    private var transition: Player?
    private var songID: Int?
    private var entries: [Int: Int] = [:]
    private var wait: (song: Int, transition: Int)?   // switch when main's measure count moves on (musicseq.py states 1, 3, 6)
    private var ref = 0                           // 7197: the measure count stored when the switch or transition began
    private var tick = 0                          // next music task update, in 1 / pollHz s
    private var polling = false                   // 72f3: the update does not re-enter
    private static let pollHz = 30.0              // the music task's update (FUN_1198_1054), inferred once per game tick
    private var after: Int?
    private var pending: Int?
    private var pausedAt: Double?
    private var held: Int?
    private var output: [MusicMIDIEvent] = []
    private var serving = false                   // a song loaded and not paused: the driver is served (adlib.py "Timing")
    private var servingChanges: [(time: Double, on: Bool)] = []
    private var lastTime = 0.0
    private var volume: Int?                      // music level 0...100 (nil = unscaled); 0 = disabled (DAT_4b6e)
    private var lastSong: Int?                    // song to resume when music is re-enabled (the engine's saved DAT_4e30)
    private var cc7: [Int: Int] = [:]             // channel -> latest volume controller value of the songs (unscaled)
    private static let optionsMusic = 4           // script constant _OptionsMusic (GAMEDAT/VARS.DEF _OPTIONSMUSIC)

    public init(library: MusicLibrary, volume: Int? = nil) { self.library = library; self.volume = volume }

    /// The music level changed (World.musicVolLog); same ordering rules as `request`.
    public func setVolume(_ level: Int, at seconds: Double) {
        guard seconds >= lastTime else { return }
        do {
            try process(before: seconds)
            lastTime = seconds
            if level < 1 {
                if volume == nil || volume! > 0 {
                    let keep = lastSong
                    try accept(-4, at: seconds)
                    lastSong = keep                // a volume stop does not forget the song
                }
                volume = level
                return
            }
            volume = level
            if songID == nil { try accept(lastSong ?? Self.optionsMusic, at: seconds) }
            for channel in cc7.keys.sorted() { emit(seconds, [UInt8(0xb0 | channel), 7, UInt8(scale(cc7[channel]!))]) }
        } catch { stopAll() }
    }

    /// Submit a script MUSIC value. Calls must have nondecreasing timestamps.
    public func request(_ id: Int, at seconds: Double) {
        guard seconds >= lastTime else { return }
        do {
            try process(before: seconds)
            lastTime = seconds
            try accept(id, at: seconds)
        } catch { stopAll() }
    }

    /// Advance the 120 Hz timeline and return all emitted MIDI messages up to and including `seconds`.
    public func advance(to seconds: Double) -> [MusicMIDIEvent] {
        guard seconds >= lastTime else { return [] }
        do {
            try process(through: seconds)
            lastTime = seconds
        } catch { stopAll() }
        let result = output
        output.removeAll(keepingCapacity: true)
        return result
    }

    /// When the driver is served since the last call (adlib.py `serving`: on at a song start or resume, off at a stop or pause).
    public func takeServingChanges() -> [(time: Double, on: Bool)] {
        defer { servingChanges.removeAll(keepingCapacity: true) }
        return servingChanges
    }

    private func setServing(_ on: Bool, at time: Double) { serving = on; servingChanges.append((time, on)) }

    private func emit(_ time: Double, _ bytes: [UInt8]) { output.append(MusicMIDIEvent(time: time, bytes: bytes)) }

    private func scale(_ v: Int) -> Int { volume.map { min(127, v * max(0, min($0, 127)) / 100) } ?? v }      // a hand-edited negative volume must not trap UInt8()

    /// Emit a song message: channel volume controllers are tracked and scaled by the music level. `player`: the sequence that
    /// sends it, whose caches follow (AIL 220f, 28c0, 28dc).
    private func put(_ time: Double, _ bytes: [UInt8], from player: Player? = nil) {
        let hi = bytes[0] & 0xf0, channel = Int(bytes[0] & 15)
        if let player {
            if hi == 0xb0, bytes.count >= 3, Player.cached.contains(Int(bytes[1])) { player.controllers[Int(bytes[1]) << 4 | channel] = bytes[2] }
            else if hi == 0xc0, bytes.count >= 2 { player.programs[channel] = bytes[1] }
            else if hi == 0xe0, bytes.count >= 3 { player.bends[channel] = [bytes[1], bytes[2]] }
        }
        if bytes[0] & 0xf0 == 0xb0, bytes.count >= 3, bytes[1] == 7 {
            cc7[Int(bytes[0] & 15)] = Int(bytes[2])
            emit(time, [bytes[0], 7, UInt8(scale(Int(bytes[2])))])
        } else { emit(time, bytes) }
    }

    private func stopAll() {
        main = nil; transition = nil; songID = nil; wait = nil; after = nil; pending = nil; pausedAt = nil; held = nil
        if serving { setServing(false, at: lastTime) }
    }

    /// AIL 1fc3: note off for every queued note, in entry order.
    private func flush(_ player: Player, at time: Double) {
        for i in 0..<Player.queueSize { if let e = player.queue[i] { emit(time, [0x80 | e.channel, e.key, 0]); player.queue[i] = nil } }
    }

    /// AIL 2021: sustain off where the sequence left it on.
    private func release(_ player: Player, at time: Double) {
        for channel in 0..<16 where (player.controllers[64 << 4 | channel] ?? 0) >= 64 { emit(time, [UInt8(0xb0 | channel), 64, 0]) }
    }

    /// _XMI_STOP_SEQUENCE: only for a playing sequence.
    private func stop(_ player: Player, at time: Double) {
        guard player.status == 1 else { return }
        flush(player, at: time)
        release(player, at: time)
        player.status = 0
    }

    /// AIL 20c8: resend the cached controllers, then each channel's pitch bend and program.
    private func resume(_ player: Player, at time: Double) {
        for controller in Player.cached {
            for channel in 0..<16 {
                if let value = player.controllers[controller << 4 | channel] { put(time, [UInt8(0xb0 | channel), UInt8(controller), value]) }
            }
        }
        for channel in 0..<16 {
            if let bend = player.bends[channel] { emit(time, [UInt8(0xe0 | channel)] + bend) }
            if let program = player.programs[channel] { emit(time, [UInt8(0xc0 | channel), program]) }
        }
    }

    private func kill(at time: Double) {
        if let main { stop(main, at: time); self.main = nil }
        if let transition { stop(transition, at: time); self.transition = nil }
    }

    private func start(_ id: Int, at time: Double, restart: Bool = false) throws {
        let sequence = try library.song(id)
        let index: Int
        if restart { index = sequence.markers[126] ?? 0 }
        else {
            var entry = entries[id] ?? -1
            if entry >= 0 && sequence.markers[entry] == nil { entry = sequence.markers[0] == nil ? -1 : 0 }
            index = entry >= 0 ? sequence.markers[entry]! : 0
            entries[id] = entry + 1
        }
        let player = Player(sequence: sequence, time: time, index: index)
        main = player; songID = id
        setServing(true, at: time)
    }

    private func begin(_ id: Int, at time: Double) throws {
        wait = nil; after = nil; transition = nil
        try start(id, at: time)
        let remembered = pending; pending = nil
        if let remembered { try accept(remembered, at: time) }
    }

    private func accept(_ id: Int, at time: Double) throws {
        if let volume, volume < 1 { return }                  // music is disabled: requests are ignored
        if id >= 0 { lastSong = id } else if id == -1 || id == -4 { lastSong = nil }
        if id == -1 || id == -4 {
            kill(at: time); songID = nil; wait = nil; after = nil; pending = nil; pausedAt = nil; held = nil
            setServing(false, at: time)
            return
        }
        if id == -2 {
            if pausedAt == nil, main != nil || transition != nil {
                pausedAt = time
                setServing(false, at: time)
                if let main { stop(main, at: time) }
                if let transition { stop(transition, at: time) }
            }
            return
        }
        if id == -3 {
            if let pausedAt {
                for player in [main, transition].compactMap({ $0 }) {
                    player.baseStep += Player.step(time) - Player.step(pausedAt)
                    if player.status == 0 { resume(player, at: time); player.status = 1 }
                }
                self.pausedAt = nil
                setServing(true, at: time)
                let request = held; held = nil
                if let request { try accept(request, at: time) }
            }
            return
        }
        guard id >= 0 else { return }
        if pausedAt != nil { held = id; return }
        if wait != nil || transition != nil { pending = id; return }
        if id == songID { return }
        let row = songID.flatMap { library.table[TransitionKey($0, id)] }
        if let main, main.status != 2, let row {
            wait = (id, row.first ?? 0)                   // the transition value at measure 1
            ref = main.count
        } else { kill(at: time); try start(id, at: time) }     // nothing playing, an ended song or no row: switch now
        try poll(at: time)                                // 1668 ends with the music task's update (183b)
    }

    /// FUN_1198_09fc: the measure count differs from the stored one, or the sequence no longer plays.
    private func moved(_ player: Player?) -> Bool {
        guard let player else { return true }
        return player.status != 1 || max(1, player.count) != ref
    }

    /// The music task's update (FUN_1198_1054); paused music is left alone.
    private func poll(at time: Double) throws {
        guard !polling, pausedAt == nil else { return }
        polling = true
        defer { polling = false }
        if let main, main.status == 2, wait == nil, transition == nil, let id = songID, library.songs[id].loopMeasure > 0 {
            try start(id, at: time, restart: true)
        } else if let request = wait, moved(main) {
            wait = nil
            if request.transition == 0 { kill(at: time); try begin(request.song, at: time); return }
            if request.transition > 0, let main { stop(main, at: time); self.main = nil }
            let player = Player(sequence: try library.transition(abs(request.transition)), time: time)
            transition = player; after = request.song
            ref = player.count
        } else if let player = transition, moved(player), let after {
            kill(at: time); try begin(after, at: time)
        }
    }

    private func step(_ player: Player) throws {
        let time = player.nextTime
        if let due = player.dueStep, due <= player.itemStep {
            for i in 0..<Player.queueSize {
                if let e = player.queue[i], e.end <= due { emit(time, [0x80 | e.channel, e.key, 0]); player.queue[i] = nil }
            }
            return
        }
        let item = player.sequence.items[player.index]
        player.index += 1
        switch item.kind {
        case .note:
            let i = player.queue.firstIndex { $0 == nil } ?? 0
            player.queue[i] = (item.bytes[0] & 15, item.bytes[1], Player.step(time) + max(item.value, 1))
            put(time, item.bytes)
        case .message: put(time, item.bytes, from: player)
        case .bar: player.measure = item.value
        case .forLoop: player.stack.append((player.index, item.value))
        case .next:
            if let top = player.stack.last {
                if top.count == 0 || top.count > 1 {
                    player.stack[player.stack.count - 1].count -= top.count > 0 ? 1 : 0
                    player.jump(to: top.index, at: Player.step(time))
                } else { player.stack.removeLast() }
            }
        case .end:
            release(player, at: time)
            player.status = 2                              // done: no longer served; the next update acts on it
        case .branch: break
        }
    }

    /// Run what is due before `time` (or through it): at equal times a request (already ordered by the callers), then the
    /// update, then the players.
    private func process(until time: Double, inclusive: Bool) throws {
        while true {
            var best: (time: Double, kind: Int, player: Player?) = (Double(tick) / Self.pollHz, 1, nil)
            if pausedAt == nil {
                for player in [main, transition] where player?.status == 1 {
                    let next = player!.nextTime
                    if next < best.time { best = (next, 2, player) }
                }
            }
            guard inclusive ? best.time <= time : best.time < time else { return }
            if let player = best.player { try step(player) } else { tick += 1; try poll(at: best.time) }
        }
    }

    private func process(before time: Double) throws { try process(until: time, inclusive: false) }
    private func process(through time: Double) throws { try process(until: time, inclusive: true) }
}

private struct TransitionKey: Hashable { let from: Int, to: Int; init(_ from: Int, _ to: Int) { self.from = from; self.to = to } }
private struct Song { let file: String, measures: Int, loopMeasure: Int }

/// One registered sequence (musicseq.Player): position on a 120 Hz step timeline, its note queue and its controller caches.
private final class Player {
    static let cached = [7, 1, 10, 11, 64, 114]   // the controllers _XMI_RESUME_SEQUENCE resends, in its order
    static let queueSize = 32
    static func step(_ seconds: Double) -> Int { Int((seconds * 120 + 0.5).rounded(.down)) }
    let sequence: Sequence
    var index: Int
    var baseStep: Int
    var baseTick: Int
    var measure = -1                               // the driver's measure count (sequence +0x40): -1 at start, then the last 0x77 value
    var stack: [(index: Int, count: Int)] = []
    var queue = [(channel: UInt8, key: UInt8, end: Int)?](repeating: nil, count: Player.queueSize)
    var controllers: [Int: UInt8] = [:]            // controller << 4 | channel -> last value sent
    var programs: [Int: UInt8] = [:], bends: [Int: [UInt8]] = [:]
    var status = 1                                 // the driver's sequence status: 1 playing, 0 stopped, 2 done (reached FF 2F)
    init(sequence: Sequence, time: Double, index: Int = 0) {
        self.sequence = sequence; self.index = index; baseStep = Player.step(time); baseTick = sequence.items[index].tick
    }
    var count: Int { max(0, measure) }              // _XMI_MEASURE_COUNT: at least 0
    var itemStep: Int { baseStep + sequence.items[index].tick - baseTick }
    var dueStep: Int? { queue.compactMap { $0?.end }.min() }
    var nextTime: Double { Double(dueStep.map { min($0, itemStep) } ?? itemStep) / 120.0 }
    func jump(to index: Int, at step: Int) { self.index = index; baseStep = step; baseTick = sequence.items[index].tick }
}

private final class Sequence {
    enum Kind { case message, note, forLoop, next, bar, branch, end }
    struct Item { let tick: Int, kind: Kind, value: Int, bytes: [UInt8] }   // a note's value is its duration
    let items: [Item]
    let markers: [Int: Int]
    init(evnt: [UInt8]) throws {
        let events = try XMIDI.decode(evnt)                // file order; each note on is followed by its note off
        var result: [Item] = []
        var end = 0
        for (i, event) in events.enumerated() {
            end = max(end, event.tick)
            guard event.order == 1 || event.order == 2 else { continue }   // the note off XMIDI derives from a duration
            guard let status = event.bytes.first, status < 0xf0 else { continue }
            if status & 0xf0 == 0x90 {
                result.append(Item(tick: event.tick, kind: .note, value: events[i + 1].tick - event.tick, bytes: event.bytes))
            } else if status & 0xf0 == 0xb0, event.bytes.count >= 3 {
                switch event.bytes[1] {
                case 0x74: result.append(Item(tick: event.tick, kind: .forLoop, value: Int(event.bytes[2]), bytes: []))
                case 0x75: result.append(Item(tick: event.tick, kind: .next, value: Int(event.bytes[2]), bytes: []))
                case 0x77: result.append(Item(tick: event.tick, kind: .bar, value: Int(event.bytes[2]), bytes: []))
                case 0x78: result.append(Item(tick: event.tick, kind: .branch, value: Int(event.bytes[2]), bytes: []))
                case 0x6e...0x78: break
                default: result.append(Item(tick: event.tick, kind: .message, value: 0, bytes: event.bytes))
                }
            } else { result.append(Item(tick: event.tick, kind: .message, value: 0, bytes: event.bytes)) }
        }
        result.append(Item(tick: end, kind: .end, value: 0, bytes: [])); items = result
        var markerMap: [Int: Int] = [:]
        for (index, item) in result.enumerated() where item.kind == .branch && markerMap[item.value] == nil { markerMap[item.value] = index }
        markers = markerMap
    }
}

private enum XMIDI {
    struct Event { let tick: Int, order: Int, serial: Int, bytes: [UInt8] }
    private static let channelLengths: [UInt8: Int] = [0x80: 2, 0x90: 2, 0xa0: 2, 0xb0: 2, 0xc0: 1, 0xd0: 1, 0xe0: 2]
    static func sequences(_ data: [UInt8]) throws -> [[UInt8]] {
        func walk(_ nodes: [IFFNode], into output: inout [[UInt8]]) {
            for node in nodes {
                if node.id == "FORM", node.type == "XMID", let children = node.children {
                    for child in children where child.id == "EVNT" { output.append(data.slice(child.offset, child.offset + child.size)) }
                } else if let children = node.children { walk(children, into: &output) }
            }
        }
        var output: [[UInt8]] = []; walk(try IFF.parse(data), into: &output); return output
    }
    static func decode(_ data: [UInt8]) throws -> [Event] {
        var position = 0, tick = 0, serial = 0, output: [Event] = []
        func varlen(_ position: inout Int) throws -> Int {
            var value = 0
            while true { guard position < data.count else { throw FormatError("truncated XMIDI varlen") }; let byte = data[position]; position += 1; value = value << 7 | Int(byte & 0x7f); if byte & 0x80 == 0 { return value } }
        }
        func append(_ tick: Int, _ order: Int, _ bytes: [UInt8]) { output.append(Event(tick: tick, order: order, serial: serial, bytes: bytes)); serial += 1 }
        while position < data.count {
            let status = data[position]
            if status < 0x80 { tick += Int(status); position += 1; continue }
            position += 1; let hi = status & 0xf0
            if status == 0xff {
                guard position < data.count else { throw FormatError("truncated XMIDI meta event") }; let type = data[position]; position += 1
                let length = try varlen(&position); guard position + length <= data.count else { throw FormatError("truncated XMIDI meta payload") }
                append(tick, 1, [status, type] + putVarlen(length) + data.slice(position, position + length)); position += length
                if type == 0x2f { break }
            } else if status == 0xf0 || status == 0xf7 {
                let length = try varlen(&position); guard position + length <= data.count else { throw FormatError("truncated XMIDI sysex") }
                append(tick, 1, [status] + putVarlen(length) + data.slice(position, position + length)); position += length
            } else if hi == 0x90 {
                guard position + 2 <= data.count else { throw FormatError("truncated XMIDI note") }
                let note = data[position], velocity = data[position + 1]; position += 2; let duration = try varlen(&position)
                append(tick, 2, [status, note, velocity]); append(tick + duration, duration == 0 ? 3 : 0, [0x80 | (status & 15), note, 0])
            } else if let length = channelLengths[hi] {
                guard position + length <= data.count else { throw FormatError("truncated XMIDI channel event") }
                append(tick, 1, [status] + data.slice(position, position + length)); position += length
            } else { throw FormatError("bad XMIDI status \(status) at \(position - 1)") }
        }
        return output
    }
    private static func putVarlen(_ value: Int) -> [UInt8] {
        var value = value, result = [UInt8(value & 0x7f)]; value >>= 7
        while value > 0 { result.append(UInt8(value & 0x7f) | 0x80); value >>= 7 }
        return result.reversed()
    }
}
