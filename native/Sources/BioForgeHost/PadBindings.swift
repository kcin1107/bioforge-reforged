// The player's game controller bindings: which controller button stands for which control of KeyBindings. The left stick and the
// directional pad are always the eight directions, as the numpad's layout. Pure Foundation, so the settings window and the tests share it.
import Foundation

public enum PadButton: String, CaseIterable, Sendable {
    case a, b, x, y, leftShoulder, rightShoulder, leftTrigger, rightTrigger, leftStick, rightStick, menu, options

    /// The generic name, for when no controller is connected to name it.
    public var title: String {
        switch self {
        case .a: "A"
        case .b: "B"
        case .x: "X"
        case .y: "Y"
        case .leftShoulder: "Left Shoulder"
        case .rightShoulder: "Right Shoulder"
        case .leftTrigger: "Left Trigger"
        case .rightTrigger: "Right Trigger"
        case .leftStick: "Left Stick Press"
        case .rightStick: "Right Stick Press"
        case .menu: "Menu"
        case .options: "Options"
        }
    }
}

public struct PadBindings: Equatable, Sendable {
    /// Clockwise from straight up: the numpad's 8, 9, 6, 3, 2, 1, 4, 7.
    public static let directions = ["forward", "forwardRight", "turnRight", "sidestepRight", "back", "sidestepLeft", "turnLeft", "forwardLeft"]
    public static let deadZone = 0.35
    private static let defaults: [String: PadButton] = [
        "use": .a, "pickup": .b, "shoot": .x, "combat": .y, "kick": .leftShoulder, "punch": .rightShoulder, "run": .rightTrigger,
        "options": .menu, "pimm": .options, "inventory": .leftStick, "diagnostics": .rightStick,
    ]

    /// control id -> button
    public private(set) var buttons: [String: PadButton]

    public init() { buttons = Self.defaults }

    public func button(_ id: String) -> PadButton? { buttons[id] }
    public func control(for button: PadButton) -> String? { buttons.first { $0.value == button }?.key }

    /// Bind `button` to a control (nil clears it); the control that had the button loses it, and the directions can't be rebound.
    public mutating func bind(_ button: PadButton?, to id: String) {
        guard KeyBindings.control(id) != nil, !Self.directions.contains(id) else { return }
        if let button, let other = control(for: button) { buttons[other] = nil }
        buttons[id] = button
    }

    /// The direction control of a stick position (y up), or nil inside the dead zone.
    public static func direction(x: Double, y: Double) -> String? {
        guard hypot(x, y) >= deadZone else { return nil }
        let degrees = atan2(x, y) * 180 / .pi
        return directions[((Int((degrees / 45).rounded()) % 8) + 8) % 8]
    }

    // MARK: persistence (UserDefaults stores [id: button name]; a saved set replaces the defaults, so a cleared control stays cleared)

    public var propertyList: [String: String] { buttons.mapValues(\.rawValue) }

    public init(propertyList p: [String: String]) {
        buttons = [:]
        for (id, name) in p.sorted(by: { $0.key < $1.key }) { if let b = PadButton(rawValue: name) { bind(b, to: id) } }
    }
}

/// Turns polled controller states into press, release and direction changes.
public struct PadTracker: Sendable {
    public enum Event: Equatable, Sendable {
        case button(PadButton, down: Bool)
        case direction(from: String?, to: String?)
    }

    private var held = Set<PadButton>(), direction: String?

    public init() {}

    public mutating func update(pressed: Set<PadButton>, x: Double, y: Double) -> [Event] {
        var events = PadButton.allCases.compactMap { b -> Event? in pressed.contains(b) == held.contains(b) ? nil : .button(b, down: pressed.contains(b)) }
        let new = PadBindings.direction(x: x, y: y)
        if new != direction { events.append(.direction(from: direction, to: new)) }
        held = pressed
        direction = new
        return events
    }
}
