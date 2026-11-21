// Offline General MIDI renderer on Apple's built-in synth (same approach the native app will use).
//   swift re/tools/midi2wav.swift in.json out.wav [rate]      (or swiftc -O it once and run the binary)
// in.json: {"duration": seconds, "events": [{"t": seconds, "b": [status, d1, d2]}, ...]} (1-byte
// messages like program change may omit d2; "b" has 2 or 3 bytes). Output: stereo 16-bit PCM WAV,
// `rate` Hz (default 44100). Events are applied at their exact sample: rendering is split at each one.
import AVFoundation
import AudioToolbox

let args = CommandLine.arguments
guard args.count >= 3 else { FileHandle.standardError.write(Data("usage: midi2wav in.json out.wav [rate]\n".utf8)); exit(2) }
let rate = args.count > 3 ? Double(args[3])! : 44100
let spec = try JSONSerialization.jsonObject(with: Data(contentsOf: URL(fileURLWithPath: args[1]))) as! [String: Any]
let total = AVAudioFrameCount(((spec["duration"] as! NSNumber).doubleValue * rate).rounded())
let events = (spec["events"] as! [[String: Any]]).map { e -> (AVAudioFramePosition, [UInt8]) in
    (AVAudioFramePosition(((e["t"] as! NSNumber).doubleValue * rate).rounded()), (e["b"] as! [NSNumber]).map { $0.uint8Value })
}.enumerated().sorted { ($0.element.0, $0.offset) < ($1.element.0, $1.offset) }.map { $0.element }   // stable

let synth = AVAudioUnitMIDIInstrument(audioComponentDescription: AudioComponentDescription(
    componentType: kAudioUnitType_MusicDevice, componentSubType: kAudioUnitSubType_MIDISynth,
    componentManufacturer: kAudioUnitManufacturer_Apple, componentFlags: 0, componentFlagsMask: 0))
let engine = AVAudioEngine()
engine.attach(synth)
let format = AVAudioFormat(standardFormatWithSampleRate: rate, channels: 2)!
engine.connect(synth, to: engine.mainMixerNode, format: format)   // deprecated in macOS 27 but still fine
try engine.enableManualRenderingMode(.offline, format: format, maximumFrameCount: 4096)
var bank = URL(fileURLWithPath: "/System/Library/Components/CoreAudio.component/Contents/Resources/gs_instruments.dls") as CFURL
var st: OSStatus = -1
withUnsafePointer(to: &bank) { p in
    synth.withAudioUnit { au in
        st = AudioUnitSetProperty(au, AudioUnitPropertyID(kMusicDeviceProperty_SoundBankURL),
                                  AudioUnitScope(kAudioUnitScope_Global), 0, p, UInt32(MemoryLayout<CFURL>.size))
    }
}
guard st == noErr else { FileHandle.standardError.write(Data("sound bank load failed: \(st)\n".utf8)); exit(1) }
try engine.start()

var out: AVAudioFile? = try AVAudioFile(forWriting: URL(fileURLWithPath: args[2]), settings: [
    AVFormatIDKey: kAudioFormatLinearPCM, AVSampleRateKey: rate, AVNumberOfChannelsKey: 2,
    AVLinearPCMBitDepthKey: 16, AVLinearPCMIsFloatKey: false, AVLinearPCMIsBigEndianKey: false])
let buf = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: 4096)!
var pos: AVAudioFramePosition = 0, next = 0
while pos < AVAudioFramePosition(total) {
    while next < events.count && events[next].0 <= pos {
        let b = events[next].1
        synth.sendMIDIEvent(b[0], data1: b[1], data2: b.count > 2 ? b[2] : 0)
        next += 1
    }
    var n = AVAudioFramePosition(total) - pos
    if next < events.count { n = min(n, events[next].0 - pos) }
    let want = AVAudioFrameCount(min(n, 4096))
    guard try engine.renderOffline(want, to: buf) == .success else { FileHandle.standardError.write(Data("render failed\n".utf8)); exit(1) }
    try out!.write(from: buf)
    pos += AVAudioFramePosition(buf.frameLength)
}
out = nil                                                  // closes the file (writes the WAV header sizes)
