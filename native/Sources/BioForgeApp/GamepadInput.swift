// A game controller, through Apple's Game Controller framework: found automatically, polled 60 times a second, and reported as PadTracker
// events. The keyboard always keeps working (HIG "Game controls": support the platform's default input, detect controllers automatically).
import AppKit
import BioForgeCore
import BioForgeHost
import GameController

@MainActor
final class GamepadInput {
    var onEvent: ((PadTracker.Event) -> Void)?
    var onStick: ((Double, Double) -> Void)?
    private var tracker = PadTracker()
    private var timer: Timer?

    func start() {
        timer = Timer.scheduledTimer(withTimeInterval: 1.0 / 60, repeats: true) { [weak self] _ in
            MainActor.assumeIsolated { self?.poll() }
        }
    }

    private var pad: GCExtendedGamepad? { (GCController.current ?? GCController.controllers().first)?.extendedGamepad }

    private func element(_ b: PadButton, _ p: GCExtendedGamepad) -> GCControllerButtonInput? {
        switch b {
        case .a: p.buttonA
        case .b: p.buttonB
        case .x: p.buttonX
        case .y: p.buttonY
        case .leftShoulder: p.leftShoulder
        case .rightShoulder: p.rightShoulder
        case .leftTrigger: p.leftTrigger
        case .rightTrigger: p.rightTrigger
        case .leftStick: p.leftThumbstickButton
        case .rightStick: p.rightThumbstickButton
        case .menu: p.buttonMenu
        case .options: p.buttonOptions
        }
    }

    private func poll() {
        var pressed = Set<PadButton>(), x = 0.0, y = 0.0
        if let p = pad {
            pressed = Set(PadButton.allCases.filter { element($0, p)?.isPressed == true })
            let stick = p.dpad.xAxis.value != 0 || p.dpad.yAxis.value != 0 ? p.dpad : p.leftThumbstick
            (x, y) = (Double(stick.xAxis.value), Double(stick.yAxis.value))
        }
        for e in tracker.update(pressed: pressed, x: x, y: y) { onEvent?(e) }
        onStick?(x, y)
    }

    /// The connected controller's own label and symbol for a button (HIG: match its labels, prefer symbols); the generic name without one.
    func label(_ b: PadButton) -> (title: String, image: NSImage?) {
        guard let p = pad, let e = element(b, p) else { return (b.title, nil) }
        let image = e.sfSymbolsName.flatMap { NSImage(systemSymbolName: $0, accessibilityDescription: e.localizedName ?? b.title) }
        return (e.localizedName ?? b.title, image)
    }
}
