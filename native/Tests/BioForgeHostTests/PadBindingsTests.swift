import Testing
@testable import BioForgeHost

struct PadBindingsTests {
    @Test func theStickGivesTheNumpadsEightDirections() {
        let cases: [(Double, Double, String)] = [(0, 1, "forward"), (1, 1, "forwardRight"), (1, 0, "turnRight"), (1, -1, "sidestepRight"),
                                                 (0, -1, "back"), (-1, -1, "sidestepLeft"), (-1, 0, "turnLeft"), (-1, 1, "forwardLeft")]
        for (x, y, id) in cases { #expect(PadBindings.direction(x: x, y: y) == id) }
        #expect(PadBindings.direction(x: 0.1, y: -0.2) == nil)
    }

    @Test func aButtonMeansOneThingAndDirectionsStayFixed() {
        var b = PadBindings()
        b.bind(.a, to: "shoot")
        #expect(b.button("shoot") == .a && b.button("use") == nil && b.control(for: .a) == "shoot")
        b.bind(.y, to: "forward")
        #expect(b.button("forward") == nil && b.control(for: .y) == "combat")
    }

    @Test func aClearedControlStaysClearedAfterSaving() {
        var b = PadBindings()
        b.bind(nil, to: "use")
        #expect(PadBindings(propertyList: b.propertyList) == b)
    }

    @Test func everyDefaultIsARealControlAndNoDirection() {
        for id in PadBindings().buttons.keys { #expect(KeyBindings.control(id) != nil && !PadBindings.directions.contains(id)) }
    }

    @Test func theTrackerReportsOnlyChanges() {
        var t = PadTracker()
        #expect(t.update(pressed: [.a], x: 0, y: 1) == [.button(.a, down: true), .direction(from: nil, to: "forward")])
        #expect(t.update(pressed: [.a], x: 0, y: 1).isEmpty)
        #expect(t.update(pressed: [], x: 0, y: 0) == [.button(.a, down: false), .direction(from: "forward", to: nil)])
    }
}
