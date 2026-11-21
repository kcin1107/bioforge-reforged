// Gameplay half of the engine binding (world.py): player keys, scripted movement (GO / FACE / TURN / MOTION), extent-based PHYS
// collision, the nurse AI / combat helpers, LOADLEVEL, the automatic camera manager and the per-tick step.
//
// One tick = one VM tick (30 Hz). Motions advance one frame per 2 ticks (POSE_RATE); a figure moving by GO, AI or manual control adds
// each frame's root delta rotated by -heading to its position; melee hits are in WorldCombat.swift.
// Cameras (FUN_1130_0fa3): while the script's auto flag is on, the current camera keeps the followed object while it still accepts
// it; else the enabled accepting camera with the smallest distance wins, debounced by one frame.
import Foundation

extension World {
    // MARK: keys (keys.swift mapping): held motions are evaluated every tick, edge actions are queued

    public func setPlayerInput(forward: Int = 0, turn: Int = 0, run: Bool = false, attack: Bool = false) {
        recorder?.enter("setPlayerInput", frames, [forward, turn, run ? 1 : 0, attack ? 1 : 0]); defer { recorder?.leave() }
        playerInput = PlayerInput(forward: max(-1, min(1, forward)), turn: max(-1, min(1, turn)), run: run, attack: attack)
    }

    var inputBlocked: Bool { monitor != nil || isOptionsOpen }

    public var isMonitorRunning: Bool { monitor != nil }
    public var monitorName: String? { monitor?.name }

    public func monitorPointerMove(x: Int, y: Int) { recorder?.enter("monitorPointerMove", frames, [x, y]); defer { recorder?.leave() }; monitor?.pointerMove(x: x, y: y) }
    public func monitorMouseDown() { recorder?.enter("monitorMouseDown", frames); defer { recorder?.leave() }; monitor?.mouseDown() }
    public func monitorMouseUp() { recorder?.enter("monitorMouseUp", frames); defer { recorder?.leave() }; monitor?.mouseUp() }
    public func optionMouseDown() { recorder?.enter("optionMouseDown", frames); defer { recorder?.leave() }; options?.mouseDown() }
    public func optionMouseUp() { recorder?.enter("optionMouseUp", frames); defer { recorder?.leave() }; options?.mouseUp() }
    /// The right mouse button on a running monitor (MonitorScreen.rightClick): ESCAPE_BUTTON, like the Escape key. Nothing in plain play.
    public func monitorRightClick() { recorder?.enter("monitorRightClick", frames); defer { recorder?.leave() }; monitor?.rightClick() }
    @discardableResult public func optionRightClick() -> String? {
        recorder?.enter("optionRightClick", frames); defer { recorder?.leave() }
        return options.flatMap { recordOptionAction($0.rightClick()) }
    }
    public func monitorKey(_ name: String) { recorder?.enter("monitorKey", frames, [], name); defer { recorder?.leave() }; monitor?.key(name) }
    /// The release turned pointer input back on and put the DOS mouse on the pointer (FUN_1250_0415): where, in 320x200 points, once.
    public func takeMouseWarp() -> (x: Int, y: Int)? {
        if let options, !options.closed { return options.takeMouseWarp() }
        guard let monitor else { return nil }
        defer { monitor.mouseWarp = nil }
        return monitor.mouseWarp
    }

    public var isOptionsOpen: Bool { options.map { !$0.closed } ?? false }
    @discardableResult public func optionActivate(_ button: String) -> String? {
        recorder?.enter("optionActivate", frames, [], button); defer { recorder?.leave() }
        return options.flatMap { recordOptionAction($0.activate(button)) }
    }
    @discardableResult public func optionKey(_ name: String) -> String? {
        recorder?.enter("optionKey", frames, [], name); defer { recorder?.leave() }
        return options.flatMap { recordOptionAction($0.key(name)) }
    }
    @discardableResult public func optionClick(x: Int, y: Int) -> String? {
        recorder?.enter("optionClick", frames, [x, y]); defer { recorder?.leave() }
        return options.flatMap { recordOptionAction($0.click(x: x, y: y)) }
    }
    /// -> the asset name of the control under the pointer (the app clicks only if press and release agree).
    @discardableResult public func optionPointerMove(x: Int, y: Int) -> String? {
        recorder?.enter("optionPointerMove", frames, [x, y]); defer { recorder?.leave() }
        return options?.pointerMove(x: x, y: y)
    }

    /// The keys a running monitor or the options dialog takes (FUN_10e8_11e3 hands them to FUN_1250_0cf9): Tab, Shift+Tab, Return, Space, the arrows and
    /// Home / End / Page keys, keypad 5, L and the letter shortcuts glide the pointer or press; Escape is the dialog's own (optionKey). Key up ends a
    /// held press (monitor.py screen_key).
    private func screenKey(_ scan: Int, mods: Int, down: Bool = true) {
        let dialog = isOptionsOpen
        guard let screen = dialog ? options?.monitor : monitor else { return }
        if !down { screen.keyRelease(scan); return }
        guard let code = MonitorScreen.keyCode(scan: scan, shift: mods & Keys.shift != 0), !(dialog && code == MonitorScreen.keyEscape) else { return }
        screen.keyEvent(code, scan: scan)
    }

    /// A PC scan code went down with modifier flags `mods`. Ignored while a dialog or monitor is up, except the global L / Alt+X hook.
    public func keyDown(_ scan: Int, mods: Int = 0) {
        recorder?.enter("keyDown", frames, [scan, mods]); defer { recorder?.leave() }
        keyMods = mods
        let fig = player
        if keysHeld.contains(scan) { return }
        screenKey(scan, mods: mods)
        let act = Keys.action(scan: scan, mods: mods, combat: fig?.combat ?? false, playing: fig?.motion)
        if act == .load || act == .exit {                          // FUN_1128_0f7f: also reachable while a monitor is open
            keysHeld.append(scan)
            globalHotkey(act!, mods: mods)
            return
        }
        if inputBlocked { return }
        keysHeld.append(scan)
        guard let act else { return }
        if let fig, fig.falling || fig.vz != 0 || fig.hold != 0 {
            // FUN_10a8_0541 (10a8:0548-058a): while +0x229 (AI OFF, a fall) or the z velocity is set (the test of the motion keys) the handler only answers S,
            // with CANNOT_SAVE. Without it a second I while PIMM_INVENTORY raises the wrist starts a second block whose AI OFF is never undone.
            if act == .save && !saveBusy { runAsPlayer("CANNOT_SAVE") }
            return
        }
        switch act {
        case .motion: return
        case .oneshot, .use, .combatToggle, .pickup: keyPending.append(act)
        case .pimm(let screen):
            if let fig, let item = heldItem(fig, "LTHAND") {
                stowItem(fig, item)
            } else if let fig {
                spawnFor(fig, "PIMM" + (screen.isEmpty ? "" : "_" + screen))
            }
            keyLog.append((tick, act.name, .str(screen)))
        case .options, .credits, .save:                              // FUN_10a8_0541: O, R, S
            if !keyboardCaptured {
                openOptions(act == .options ? Options.defaultFlag : act == .credits ? Options.credits : Options.save)
            } else if act == .save && !saveBusy {                    // a captured keyboard: the handler only answers S, with CANNOT_SAVE
                runAsPlayer("CANNOT_SAVE")
            }
        default:      // gamma, version: logged; gamma also steps the setting, version shows the build caption
            var detail = act.detail.map { LogValue.str($0) } ?? .none
            if case .gamma(let g) = act { detail = .int(g) }
            keyLog.append((tick, act.name, detail))
            if case .gamma(let g) = act { adjustGamma(g) }
            if act == .version { showVersion() }
        }
    }

    /// FUN_1128_0f7f: L opens the load screen when a game runs, nothing is loading or saving, the player is alive and no monitor is up
    /// (Alt overrides the monitor); Alt+X opens "EXIT TO DOS?".
    func globalHotkey(_ act: KeyAction, mods: Int) {
        if saveBusy { return }
        if act == .exit {
            if mods & Keys.alt != 0 { openOptions(Options.exit) }
            return
        }
        let alive = player.map { hitPoints($0) > 0 } ?? true
        let monitorUp = monitor != nil || isOptionsOpen
        if vm != nil && alive && (!monitorUp || mods & Keys.alt != 0) { openOptions(Options.load) }      // ASSUMPTION: [50b8] = a game is running
    }

    /// Hit points of a figure: object local ~0 (ASSUMPTION, as for DAMAGE).
    func hitPoints(_ fig: Figure) -> Int {
        guard let vm else { return 0 }
        if case .int(let hp) = vm.objectRecord(objectKey(fig.name))[0] { return hp }
        return 0
    }

    /// FUN_1128_0858: saving is unsafe while a script holds the keyboard, while a visible living figure is invulnerable or while a
    /// GRENADE exists.
    var saveSafe: Bool {
        if keyboardCaptured { return false }
        if figures.values.contains(where: { $0.invulnerable && !$0.hidden && hitPoints($0) > 0 }) { return false }
        return !items.values.contains { $0.type == "GRENADE" }
    }

    /// True once per level change, as soon as the in-game S would be accepted (openOptions' conditions): the level is new to the autosave, a
    /// player figure stands free of a fall, no flic, dialog or monitor is up and saving is not unsafe or disabled. Reads state only; the app
    /// saves and then sets `autosavedLevel`.
    public var levelAutosaveDue: Bool {
        guard level != autosavedLevel, let fig = player, show.flic == nil, !paused, !saveBusy, saveSafe, !forcingReloadOn else { return false }
        if case .int(let n)? = vm?.globals["_isexitmonrunning"], n != 0 { return false }
        return !(fig.falling || fig.vz != 0 || fig.hold != 0)
    }

    /// FUN_1100_06d4 is the negation: the script variable _forcing_reload (or the world's flag) is nonzero.
    var forcingReloadOn: Bool {
        if forcingReload { return true }
        if case .int(let n)? = vm?.globals["_forcing_reload"] { return n != 0 }
        return false
    }

    /// FUN_1120_0000(block, player): start a script block with the player figure as its object.
    @discardableResult func runAsPlayer(_ block: String) -> Bool {
        guard let vm, vm.blocks[block] != nil else { return false }
        vm.spawn(block, ctx: spawnContext(player))
        return true
    }

    /// FUN_10a8_02cc (O / R / S / L / Alt+X keys and MON_CODE): open the options dialog with `_OPTS_*` flags unless a dialog already
    /// pauses the game (except _OPTS_MUST_RELOAD) or _IsExitMonRunning is set. When saving is unsafe or a reload is forced, S fires
    /// CANNOT_SAVE instead, and O fires it and opens the main panel with Save disabled.
    /// NOT PORTED: the [4e3d] / [a36a] == 0x200 dialog states and FUN_1100_0f02, which can also stop the call.
    func openOptions(_ flagsIn: Int) {
        var flags = flagsIn
        if case .int(let n)? = vm?.globals["_isexitmonrunning"], n != 0 { return }
        if paused && flags & Options.mustReload == 0 { return }
        if !saveSafe || forcingReloadOn {
            if flags & Options.save != 0 {
                if !saveBusy { runAsPlayer("CANNOT_SAVE") }
                return
            }
            if flags & Options.defaultFlag != 0 && !saveBusy { runAsPlayer("CANNOT_SAVE") }
            flags |= Options.noSave
        }
        if let o = options, o.closed, o.language != settings.language { options = nil }      // the language changed: read the texts again
        if options == nil {
            do {
                options = try Options(game: game, settings: settings, applyAudio: { [unowned self] in applyAudio(sfx: $0, music: $1) },
                                      applyGamma: { [unowned self] in applyGamma($0) },
                                      slotUsed: { [unowned self] n in
                                          savesDir.map { FileManager.default.fileExists(atPath: $0.appendingPathComponent("GAME\(n).IM1").path) } ?? false })
            } catch { warn("options dialog unavailable: \(error)"); return }
        }
        keysHeld.removeAll()                                 // the dialog owns the keyboard: the key that opened it gets no keyUp here
        if let o = options {
            if flags & Options.credits == 0 { dialogSong = currentSong }      // FUN_1100_09cb: [4e30] = the song playing now (not for the credits mode)
            o.onCreditsPage = { [unowned self] in creditsPageOpened() }
            recordOptionAction(o.open(flags))
        }
    }

    /// FUN_1280_221e's tail, for the flag and the main panel's Credits button alike: unless _forcing_reload, FUN_1100_0716 (clear [50be] / [50bf]:
    /// FREEZE's world stop too) then FUN_1100_0740. Nothing in 1280.c / 1280_callbacks.c pauses again (only FUN_10a8_02cc sets [50be]), so leaving
    /// the page for the main panel leaves that panel over a running game.
    func creditsPageOpened() {
        guard !forcingReloadOn, let o = options else { return }
        o.resumed = true
        resumeWorld()
        restartDialogSong()
    }

    /// FUN_1198_0029: the song playing (the last MUSIC argument), -1 when none.
    var currentSong: Int { if case .int(let n)? = currentMusic, n >= 0 { return n }; return -1 }

    /// FUN_1100_0740: when a different song plays than [4e30], stop the music and restart [4e30] if it is 0 or more.
    func restartDialogSong() {
        guard currentSong != dialogSong else { return }
        musicLog.append((tick, .int(-1))); currentMusic = .int(-1)
        if dialogSong >= 0 { musicLog.append((tick, .int(dialogSong))); currentMusic = .int(dialogSong) }
    }

    /// FUN_1100_0716: [50be] cleared, which ends FREEZE's stop of the world update, camera selection and the game clock. The processes FREEZE
    /// suspended stay so until THAW, and nothing freezes the world again when the dialog closes.
    func resumeWorld() {
        guard show.frozen else { return }
        if let since = show.frozenSince { show.frozenTicks += (vm?.tick ?? 0) - since; show.frozenSince = nil }
        show.frozen = false
    }

    public func keyUp(_ scan: Int, mods: Int? = nil) {
        recorder?.enter("keyUp", frames, mods.map { [scan, $0] } ?? [scan]); defer { recorder?.leave() }
        screenKey(scan, mods: 0, down: false)
        if let mods { keyMods = mods }
        keysHeld.removeAll { $0 == scan }
        keysCaptured.removeAll { $0 == scan }
    }

    /// Tester aid: the player takes no damage while `on` (recorded, so a replay does the same).
    public func setGodMode(_ on: Bool) { recorder?.enter("setGodMode", frames, [on ? 1 : 0]); defer { recorder?.leave() }; godMode = on }

    /// Tester aid: the player's hit points back to the maximum (MAX HPS in ~5, else 100; recorded).
    public func refillHealth() {
        recorder?.enter("refillHealth", frames); defer { recorder?.leave() }
        guard let player, let vm else { return }
        var rec = vm.objectRecord(objectKey(player.name))
        if case .int(let maxHP) = rec[5], maxHP > 0 { rec[0] = .int(maxHP) } else { rec[0] = .int(100) }
        vm.setObject(objectKey(player.name), rec)
    }

    /// Modifier flags changed while keys are held (Shift turns a held walk into a run).
    public func setKeyMods(_ mods: Int) { recorder?.enter("setKeyMods", frames, [mods]); defer { recorder?.leave() }; keyMods = mods }

    /// Forget every held key (the window lost focus: no key-up will arrive).
    public func releaseKeys() { recorder?.enter("releaseKeys", frames); defer { recorder?.leave() }; keysHeld.removeAll(); keysCaptured.removeAll() }

    /// Motion (upper case) of the most recently pressed held key that asks for one.
    /// A turn request yields to a key that moves: 10a8:0541 tests Up and Down before Left and Right, and turn keys only ask for a motion
    /// from stand or atk_stand (1098:13e1).
    func heldMotion(_ fig: Figure) -> String? {
        var turn: String?
        for scan in keysHeld.reversed() {
            if case .motion(let m)? = Keys.action(scan: scan, mods: keyMods, combat: fig.combat, playing: fig.motion) {
                let name = m.uppercased()
                if !Self.turnMotions.contains(name) && name != "ATK_M4" && name != "ATK_M6" { return name }
                turn = turn ?? name
            }
        }
        return turn
    }

    /// The IMAGs Space tries, in level order: FUN_10a8_0541 walks the figure's area list (+0x35) and tests its hull against each box
    /// (1070:0aba -> 1058:173c, inclusive). There is no distance, and figures are not in the list. Live, CRYO_BTN (box edge x -13939, Lex's
    /// hull 368 out): nothing with the hull edge at -13935, the button works with it at -13943.
    func usableObjects(_ fig: Figure) -> [String] {
        guard let area = fig.area else { return [] }
        let h = queryHull(fig)
        return areaTriggers(area).map { data.triggers[$0] }.filter { Self.boxesTouch(h.lo, h.hi, $0.lo, $0.hi) }.map(\.name)
    }

    /// Space: try held items left then right with every nearby object, the object alone,
    /// then each held item alone. -> the block started or nil. The blocks are named after the item instance (+0xf7), not its
    /// type: "%s_%s_USE" (DS:0x2bf9) with the object and the item (10a8:16d0-16f1) and "%s_USE" (DS:0x2bfc) with the item alone
    /// (10a8:17f0-1803), so DANELOG (a LOGBOOK) runs DANELOG_USE. The type is tried next: CREATEITEM names a duplicate FORK_2 in
    /// the ports, where the engine's instance is the creation name (ASSUMPTION).
    @discardableResult func playerUse(_ fig: Figure) -> String? {
        func uniqued(_ names: [String]) -> [String] { names.enumerated().filter { !names[..<$0.offset].contains($0.element) }.map(\.element) }
        guard vm != nil else { return nil }
        let held = [heldItem(fig, "LTHAND"), heldItem(fig, "RTHAND")]
        for obj in usableObjects(fig) {
            for item in held.compactMap({ $0 }) {
                for blk in uniqued(["\(obj)_\(item.name)_USE", "\(obj)_\(item.type)_USE", "\(item.type)_\(obj)_USE"]) where spawnFor(fig, blk, item: item) {
                    keyLog.append((tick, "use", .str(blk)))
                    return blk
                }
            }
            let blk = obj + "_USE"
            if spawnFor(fig, blk) {
                keyLog.append((tick, "use", .str(blk)))
                return blk
            }
        }
        for item in held.compactMap({ $0 }) {
            for blk in uniqued([item.name + "_USE", item.type + "_USE"]) where spawnFor(fig, blk, item: item) {
                keyLog.append((tick, "use", .str(blk)))
                return blk
            }
        }
        return nil
    }

    @discardableResult func toggleCombat(_ fig: Figure) -> Bool {
        fig.combat.toggle()
        let blk = "\(fig.name)_\(fig.combat ? "ENTER" : "LEAVE")_COMBAT"
        var alt = blk
        if let r = blk.range(of: fig.name) { alt.replaceSubrange(r, with: fig.type) }
        let started = spawnFor(fig, blk) || spawnFor(fig, alt)
        keyLog.append((tick, "combat", .bool(fig.combat)))
        return started
    }

    /// Apply the held input without taking ownership away from scripts or AI.
    func applyPlayerInput() {
        let fig = player
        var pending = keyPending
        keyPending = []
        if inputBlocked { keysHeld.removeAll() }
        let raw = playerInput.forward != 0 || playerInput.turn != 0 || playerInput.attack || !pending.isEmpty || !keysHeld.isEmpty
        let fresh = raw && !inputWasActive                   // the original's motion requests are key-down events
        inputWasActive = raw
        guard let fig, fig.pos != nil, fig.go == nil, !aiActive(fig) else { return }
        if fig.falling || fig.vz != 0 || fig.hold != 0 { return }          // FUN_10a8_0541: no player keys while +0x229 or the z velocity is set
        pending.removeAll { act in                                        // the key handler toggles whatever Lex is doing; LEX_ENTER_COMBAT's first slice takes him
            if case .combatToggle = act {
                // then FUN_1098_0745 (10a8:1065): the idle of the new mode, so leaving combat lowers the fists (LEX_LEAVE_COMBAT only
                // restores the hand textures). A block's own MOTION (LEX_ENTER_COMBAT's ENTER_COMBAT) still follows. ASSUMPTION: only from an idle.
                toggleCombat(fig)
                if fig.motion == "STAND" || fig.motion == "ATK_STAND", fig.assets.motion(idleMotion(fig)) != nil {
                    fig.setMotion(idleMotion(fig), loop: true, engine: true)
                }
                return true
            }
            return false
        }
        let inp = playerInput
        if inp.attack { pending.append(.oneshot("shoot")) }
        let want = heldMotion(fig)
        let active = inp.forward != 0 || inp.turn != 0 || !pending.isEmpty || want != nil
        let motion = fig.motion ?? ""
        // A held pose (SNAPTOPOSE ... FREEZE) or a FREEZE'd motion (MOTION LOOK_AT_MON FREEZE at a monitor: it plays out, then its last
        // pose stays, noIdle) yields to fresh input like a finished one, and so does a script's looping MOTION ... CONTINUE nobody
        // waits on (CRYO_BTN_USE's PUSH_BUTTON): the key handler's motion gate (vtable +0x8c = 1098:12bd) refuses only during RECOIL /
        // DIE / SUPER_REC and stops any other current motion (FUN_1098_0789) for the key's motion; it tests neither the freeze flag
        // (task +0x4c, 10e0:0000) nor the end of the motion.
        // The request is made on a key-down event (FUN_10a8_0541), so only a fresh press breaks such a motion, not a key still held
        // from before (the opening's held Up through BLOCK_DRIP's DRIPPED_ON). Walk and run keys test only that gate, so they break any other
        // scripted motion too; turn and sidestep keys ask for a motion only from stand or atk_stand (1098:13e1).
        let moveKey = want.map { Self.turnWhileMoving.contains($0) && !fig.motionGateRefuses($0) } ?? false
        let held = fig.finished || (fresh && (((fig.frozen && !fig.stopped) || fig.noIdle)
                                              || (fig.unwaited && fig.loop && !["RECOIL", "DIE", "SUPER_REC"].contains(motion))
                                              || moveKey))
        if fig.frozen && !fig.stopped && !active { return }
        // ASSUMPTION: otherwise a script-set motion keeps the keys out until it finishes, except STAND and a loop of a player key
        // move (AIRMECHO's death leaves Lex in `MOTION ATK_M2 CONTINUE`); see world.py `apply_player_input`
        if !fig.manualControl && motion != "STAND" && motion != "ATK_STAND" && !Self.manualMoves.contains(motion) && !(active && held) { return }
        if active { fig.manualControl = true }
        if active && held { fig.setMotion("STAND", loop: true) }
        if !fig.manualControl { return }
        let current = fig.motion ?? ""                                    // after the STAND above
        let playingOneshot = (current.hasPrefix("ATK_") && !Self.manualMoves.contains(current) && current != "ATK_STAND") || ItemRules.itemMotions.contains(current)
        if playingOneshot && !fig.finished { return }
        if playingOneshot && fig.finished { fig.setMotion(idleMotion(fig), loop: true) }
        let m = fig.motion ?? ""
        if !(Self.manualMoves.contains(m) || m == "STAND" || m == "ATK_STAND" || m == "ATK_SHOOT" || Self.turnMotions.contains(m)) { return }
        if Self.turnWhileMoving.contains(m) {
            let turn = inp.turn + keysHeld.reduce(0) { $0 + (Self.turnKeys[$1] ?? 0) }
            fig.heading += Self.playerTurnPerTick * Double(max(-1, min(1, turn)))
        }
        for act in pending {
            switch act {
            case .use:
                let was = fig.motId
                playerUse(fig)
                if fig.go != nil || aiActive(fig) || fig.motId != was { return }      // the use block's first slice took Lex (BIKE_USE: GO HOOD WALK; TO_TMPL_GRENADE_USE: MOTION GRENADE_TOSS)
            case .pickup:
                playerPickup(fig)
                return
            case .oneshot(let name), .motion(let name):
                let up = name.uppercased()
                if up == "SHOOT" || up == "ATK_SHOOT" {            // script-gated: LEX_ATK_SHOOT decides (unarmed = no-op)
                    // FUN_1098_0e49 runs `<instance>_<motion>` (+0xf7), not the form's: a HARD Lex shoots through LEX_ATK_SHOOT
                    spawnFor(fig, fig.name + "_ATK_SHOOT")
                    return
                } else if fig.assets.motion(up) != nil {
                    fig.setMotion(name, loop: false, engine: true)
                    return
                }
                warn("\(fig.type) has no motion \(up)")
            default: break
            }
        }
        let next: String
        if let want { next = want }
        else if inp.forward > 0 { next = inp.run ? "RUN" : "WALK" }
        else if inp.forward < 0 { next = "WALK_BACK" }
        else { next = idleMotion(fig) }
        if fig.assets.motion(next) != nil && fig.motion != next { fig.setMotion(next, loop: true, engine: true) }   // the player's keys request lower-case names ("walk") in the original
        else if fig.assets.motion(next) == nil && want != nil { warn("\(fig.type) has no motion \(next)") }
    }

    /// FUN_1098_0745: `atk_stand` in combat mode, else `stand`.
    func idleMotion(_ fig: Figure) -> String {
        fig.combat && fig.assets.motion("ATK_STAND") != nil ? "ATK_STAND" : "STAND"
    }

    // MARK: collision

    func physState(_ p: Phys) -> Int {
        if let vm, case .int(let v)? = vm.globals["_" + p.name.lowercased() + "_space"] { return v & 0xff }
        return p.state
    }

    /// FUN_1058_192f / FUN_1058_1a1b: whether a candidate hull's signed fixed-point score is positive. FUN_10a0_21b2 first
    /// raises a hull bottom lying below its support by no more than -R onto the support; FUN_10a0_22e1 then also blocks
    /// while the support is above the hull bottom (a step too high).
    func figureBlocked(_ fig: Figure, _ pos: V3) -> Bool {
        let area = updateArea(fig, at: pos)
        let h = queryHull(fig, at: pos)
        if collisionScore((lo: h.lo, hi: h.hi), members: area?.members ?? Array(physBoxes().indices)) > 0 { return true }
        return h.sup > h.lo.z
    }

    /// The hull FUN_10a0_21b2 stores at fig+0x65 -> (lo, hi, support): the figure hull, its bottom raised onto the support when it
    /// lies below it by no more than -R. `p` defaults to the figure's position.
    func queryHull(_ fig: Figure, at p: V3? = nil) -> (lo: SIMD3<Int>, hi: SIMD3<Int>, sup: Int) {
        var h = hull(fig, at: p ?? fig.pos!)
        let sup = support(h.lo, h.hi, area: area(of: fig))        // FUN_10a0_21b2 passes fig+0x35 (10a0:221c..2235)
        if sup + rootZ(fig) <= h.lo.z && h.lo.z < sup && sup < h.hi.z { h.lo.z = sup }
        return (h.lo, h.hi, sup)
    }

    /// R (model+0xa6): the current motion frame's root z, kept in the pose rather than in fig.pos.
    /// R as the engine holds it: a motion's frame 0 only reaches model+0xa6 at its first update, until then the previous motion's root z stays.
    func modelRootZ(_ fig: Figure) -> Int { fig.rootStart ? fig.appliedRootZ : rootZ(fig) }

    func rootZ(_ fig: Figure) -> Int {
        guard let f = fig.frames, !f.isEmpty else { return 0 }
        return f[min(fig.idx, f.count - 1)].pos.z
    }

    /// The engine's figure hull (fig+0x65) as integer (lo, hi): FUN_10a0_0000 -> FUN_1070_08df builds x, y = +-EXTENT and z from
    /// -s to +EXTENT z around the engine position (origin + root z), where s = (F * 100 + 128) / 2048 cm.
    func hull(_ fig: Figure, at p: V3, z: Double? = nil) -> (lo: SIMD3<Int>, hi: SIMD3<Int>) {
        let e = resources.extents[fig.type] ?? Self.defaultExtentCM
        let s = floorDiv(foot(fig) * 100 + 128, 2048)
        let x = Int(p.x.rounded(.toNearestOrEven)), y = Int(p.y.rounded(.toNearestOrEven))
        let zz = Int((z ?? p.z).rounded(.toNearestOrEven)) + rootZ(fig)
        let hx = hullUnits(Int(e.x)), hy = hullUnits(Int(e.y))
        return (SIMD3(x - hx, y - hy, zz - hullUnits(s)), SIMD3(x + hx, y + hy, zz + hullUnits(Int(e.z))))
    }

    func hull(_ fig: Figure, z: Double? = nil) -> (lo: SIMD3<Int>, hi: SIMD3<Int>) {
        hull(fig, at: fig.pos!, z: z)
    }

    func physBoxes() -> [PhysBox] {
        if let b = boxes { return b }            // cached while step() runs the figures
        return data.phys.map { PhysBox(name: $0.name, state: physState($0), lo: SIMD3<Int>($0.lo, rounding: .towardZero), hi: SIMD3<Int>($0.hi, rounding: .towardZero)) }
    }

    /// Floor under a hull box (FUN_1060_03f2, stored at fig+0xee); see world.py `support`. `area` is the figure's area (nil: a null
    /// area or a global caller): only its members are ranked, the result is seeded with the anchor's floor slot and the Q pass fit
    /// test is scoped to the members (1060:0405-045c).
    func support(_ lo: SIMD3<Int>, _ hi: SIMD3<Int>, area: PhysArea? = nil) -> Int {
        var best = Self.noFloor, inside = false, pit = false
        let every = physBoxes()
        let boxes = area.map { a in a.members.map { every[$0] } } ?? every
        if let a = area { best = areaSeed(a) }
        func xy(_ b: PhysBox) -> Bool { b.lo.x <= hi.x && lo.x <= b.hi.x && b.lo.y <= hi.y && lo.y <= b.hi.y }
        for b in boxes {
            if b.state == 1 && xy(b) {
                if b.hi.z > best && hi.z > b.lo.z { best = b.hi.z }
                inside = b.lo.z <= hi.z && lo.z <= b.hi.z
            } else if b.state == 0 && xy(b) {
                best = max(best, b.lo.z)
                pit = pit || b.name.hasPrefix("Q")
            }
        }
        if pit && !inside {
            for b in boxes where b.state == 0 && b.name.hasPrefix("Q") && b.hi.z >= lo.z && b.lo.z < best && xy(b) {
                let d = b.lo.z - lo.z
                if collisionScore((lo: SIMD3(lo.x, lo.y, lo.z + d), hi: SIMD3(hi.x, hi.y, hi.z + d)), members: area?.members ?? Array(every.indices)) <= 0 { best = b.lo.z }   // FUN_1058_1a1b over the same list
            }
        }
        return best
    }

    /// The anchor's floor slot (anchor+0x4b+4*state, 1060:040d-045c): lo.z for a space, hi.z for a solid, noFloor for state 2.
    func areaSeed(_ area: PhysArea) -> Int {
        let b = physBoxes()[area.anchor]
        return b.state == 0 ? b.lo.z : b.state == 1 ? b.hi.z : Self.noFloor
    }

    /// The figure's area (fig+0x35 as passed to FUN_1060_03f2 / 0871), nil for a null area.
    func area(of fig: Figure) -> PhysArea? {
        fig.area.flatMap { a in physAreas().first { $0.anchor == a } }
    }

    /// FUN_1060_0871: the same query for a point (x, y), solids counted when zq is above their bottom; the Q pass takes any Q
    /// space whose top reaches z (no fit test). `area` scopes and seeds it as in `support`.
    func pointFloor(_ x: Int, _ y: Int, _ z: Int, _ zq: Int, area: PhysArea? = nil) -> Int {
        var best = Self.noFloor, inside = false, pit = false
        let every = physBoxes()
        let boxes = area.map { a in a.members.map { every[$0] } } ?? every
        if let a = area { best = areaSeed(a) }
        func xy(_ b: PhysBox) -> Bool { b.lo.x <= x && x <= b.hi.x && b.lo.y <= y && y <= b.hi.y }
        for b in boxes {
            if b.state == 1 && xy(b) {
                if b.hi.z > best && zq > b.lo.z { best = b.hi.z }
                inside = b.lo.z <= zq && z <= b.hi.z
            } else if b.state == 0 && xy(b) {
                best = max(best, b.lo.z)
                pit = pit || b.name.hasPrefix("Q")
            }
        }
        if pit && !inside {
            for b in boxes where b.state == 0 && b.name.hasPrefix("Q") && b.hi.z >= z && b.lo.z < best && xy(b) { best = b.lo.z }
        }
        return best
    }

    func hasSpaceBinding(_ p: Phys) -> Bool {
        vm?.globals["_" + p.name.lowercased() + "_space"] != nil
    }

    /// FUN_1138_1853: state-0 PHYS entries and script-controlled PHYS entries each anchor an ordered area. An area's
    /// physical_objs (FUN_1138_131c) holds every PHYS of the level, solids included, whose closed box touches the anchor's
    /// closed box grown by 0x1000 on each side.
    /// The engine builds the lists once at level load (1138:1853 / 131c); the port recomputes them live (in CONTROL they stay identical
    /// at every elevator step) and caches them with the step's `boxes`.
    func physAreas() -> [PhysArea] {
        if boxes != nil, let cached = areaCache { return cached }
        let bx = physBoxes()
        let eligible = bx.indices.filter { bx[$0].state == 0 || hasSpaceBinding(data.phys[$0]) }
        let areas = eligible.map { i in
            let lo = bx[i].lo &- Self.areaGrow, hi = bx[i].hi &+ Self.areaGrow
            return PhysArea(anchor: i, members: bx.indices.filter { j in
                let other = bx[j]
                return all(lo .<= other.hi) && all(other.lo .<= hi)
            })
        }
        if boxes != nil { areaCache = areas }
        return areas
    }

    /// FUN_1138_1a93: retain the current area while its origin contains the figure, otherwise choose the first area
    /// containing the origin, then the first area overlapping the hull. If none matches, retain the prior area.
    @discardableResult func updateArea(_ fig: Figure, at p: V3, hull h: (lo: SIMD3<Int>, hi: SIMD3<Int>)? = nil) -> PhysArea? {
        let areas = physAreas()
        let q = SIMD3(Int(p.x.rounded(.toNearestOrEven)), Int(p.y.rounded(.toNearestOrEven)), Int(p.z.rounded(.toNearestOrEven)) + rootZ(fig))
        func contains(_ a: PhysArea) -> Bool {
            let b = physBoxes()[a.anchor]
            return all(b.lo .<= q) && all(q .<= b.hi)
        }
        if let old = fig.area, let area = areas.first(where: { $0.anchor == old }), contains(area) { return area }
        if let area = areas.first(where: contains) { assignArea(fig, area.anchor); return area }
        let h = h ?? hull(fig, at: p)
        if let area = areas.first(where: {
            let b = physBoxes()[$0.anchor]
            return all(b.lo .<= h.hi) && all(h.lo .<= b.hi)
        }) { assignArea(fig, area.anchor); return area }
        return fig.area.flatMap { old in areas.first { $0.anchor == old } }
    }

    /// FUN_1138_1b8a: a new area clears the InTrig bytes of triggers missing from its trigger list.
    private func assignArea(_ fig: Figure, _ anchor: Int) {
        if anchor != fig.area, var t = fig.inTrig {
            let keep = Set(areaTriggers(anchor))
            for i in t.indices where !keep.contains(i) { t[i] = 0 }
            fig.inTrig = t
        }
        fig.area = anchor
    }

    // MARK: IMAG triggers (LIVING.C FUN_1088_51c3 / 50c1, PHYSICAL.C IMAG class 1290:2077)

    /// Inclusive box overlap (FUN_1068_0934, FUN_1058_173c).
    static func boxesTouch(_ lo: SIMD3<Int>, _ hi: SIMD3<Int>, _ plo: SIMD3<Int>, _ phi: SIMD3<Int>) -> Bool {
        all(lo .<= phi) && all(plo .<= hi)
    }

    /// RoomType->triggers of the area anchored at PHYS `index` (FUN_1138_131c): the level's IMAG objects whose boxes touch
    /// (FUN_1068_0934, inclusive) the anchor's box, as InTrig indices in level order.
    func areaTriggers(_ index: Int) -> [Int] {
        if let c = areaTriggerCache[index] { return c }
        let p = data.phys[index]
        let lo = SIMD3<Int>(p.lo, rounding: .towardZero), hi = SIMD3<Int>(p.hi, rounding: .towardZero)
        let found = data.triggers.indices.filter { Self.boxesTouch(lo, hi, data.triggers[$0].lo, data.triggers[$0].hi) }
        areaTriggerCache[index] = found
        return found
    }

    /// The block a trigger runs for a figure (FUN_1068_0d45): `<trigger>` for the player, else `<trigger>_<figure>` (DR_ZAP3_FIRSTBOT,
    /// DR_ZAP1_CAYNAN; "%s_%s" at DGROUP 0x2071).
    func triggerBlock(_ trig: Trigger, _ fig: Figure) -> String {
        fig === player ? trig.name : "\(trig.name)_\(fig.name)"
    }

    /// IMAG +0x4a (FUN_1068_0e7a): the trigger has a block for the player or for some other figure.
    func triggerHasBlock(_ trig: Trigger) -> Bool {
        guard let vm else { return false }
        return vm.blocks[trig.name] != nil || figures.values.contains { $0 !== player && vm.blocks["\(trig.name)_\($0.name)"] != nil }
    }

    /// IMAG vtable +0x5c (FUN_1068_0d45): a camera trigger entered by the followed figure forces its camera (FUN_1130_0f85; a name
    /// with no camera forces nothing), then the trigger's block starts with the figure current and runs its first slice at once
    /// (FUN_1120_0000).
    func fireTrigger(_ trig: Trigger, _ fig: Figure) {
        if data.cameras[trig.camera] != nil && fig.name == resolve(follow) { forcedCamera = trig.camera }
        let block = triggerBlock(trig, fig)
        if let vm, vm.blocks[block] != nil {
            events.append((vm.tick, block))
            spawnFor(fig, block)
        }
    }

    /// FUN_1088_51c3, at the end of each figure's frame after FUN_1138_1b8a re-selected its area: for each trigger of the area, a
    /// hull (+0x65) outside clears the InTrig byte; inside, the trigger fires every frame, or only on entry when its flag bit 0x01
    /// is set. Skipped for a dead player and for figures with collisions off; stops if a block moved the figure to another area
    /// (or level).
    func updateTriggers(_ fig: Figure) {
        guard let fp = fig.pos else { return }
        _ = updateArea(fig, at: fp)
        if vm == nil || (fig === player && hitPoints(fig) <= 0) { return }
        if fig.inTrig == nil { fig.inTrig = [UInt8](repeating: 0, count: data.triggers.count) }
        guard let area = fig.area, !fig.noCollide else { return }
        let level = self.level
        let h = queryHull(fig)
        for i in areaTriggers(area) {
            let t = data.triggers[i]
            if !Self.boxesTouch(h.lo, h.hi, t.lo, t.hi) {
                fig.inTrig?[i] = 0
            } else if !t.once || fig.inTrig?[i] == 0 {
                fig.inTrig?[i] = 1
                fireTrigger(t, fig)
            }
            if fig.area != area || self.level != level || fig.inTrig == nil { return }
        }
    }

    /// FUN_1088_50c1, after each passing step of the mover's loop: stop the move (the figure stays at the step) when the hull
    /// enters a trigger of its area that has a block (+0x4a) and whose InTrig byte is clear, so the frame's trigger pass fires it
    /// with the figure just inside.
    func triggerStop(_ fig: Figure, _ pos: V3) -> Bool {
        if vm == nil { return false }
        if fig.inTrig == nil { fig.inTrig = [UInt8](repeating: 0, count: data.triggers.count) }
        guard let area = fig.area, !fig.noCollide else { return false }
        let h = queryHull(fig, at: pos)
        for i in areaTriggers(area) {
            let t = data.triggers[i]
            if Self.boxesTouch(h.lo, h.hi, t.lo, t.hi) && fig.inTrig![i] == 0 && triggerHasBlock(t) { return true }
        }
        return false
    }

    /// The object's +0xb position: a figure's own, an item's `itemEnginePos` (floor position, hand pose or holder). nil if unplaced.
    func objectPos(_ o: (fig: Figure?, item: Item?)) -> V3? {
        if let item = o.item { return itemEnginePos(item) }
        return o.fig?.pos
    }

    /// The object's hull (+0x65). A figure: `queryHull`. An item (1078:08f6 -> FUN_1058_0f95): its `itemEnginePos` (whole units) +- the
    /// EXTENT box (1070:08df, `hullUnits`, no rotation; no EXTENT property = a zero box, a point).
    func objectHull(_ o: (fig: Figure?, item: Item?)) -> (lo: SIMD3<Int>, hi: SIMD3<Int>)? {
        if let item = o.item {
            guard let pos = itemEnginePos(item) else { return nil }
            loadItemPhysics(item)
            let p = SIMD3(Int(pos.x.rounded(.toNearestOrEven)), Int(pos.y.rounded(.toNearestOrEven)), Int(pos.z.rounded(.toNearestOrEven)))
            let e = SIMD3(item.extent[0], item.extent[1], item.extent[2])
            return (p &- e, p &+ e)
        }
        guard let f = o.fig, f.pos != nil, f.frames != nil else { return nil }
        let h = queryHull(f)
        return (h.lo, h.hi)
    }

    /// AMINTRIGGER <object> <trigger> (FUN_10d8_07fa -> 1070:0aba): whether the object's hull (+0x65) touches the first IMAG of that name
    /// (FUN_1058_173c, inclusive). The object is CURFIG, CURITEM or a figure / item-type name (`scriptObject`); an item's hull is
    /// `objectHull` (a held item's box follows the hand, an inventory item's the holder's origin).
    func amInTrigger(_ proc: ScriptProcess, _ obj: ScriptValue, _ trig: ScriptValue) -> Int {
        let name = pyStr(trig).uppercased()
        let o = scriptObject(proc, obj)
        guard let h = objectHull(o), let t = data.triggers.first(where: { $0.name == name }) else { return 0 }
        return Self.boxesTouch(h.lo, h.hi, t.lo, t.hi) ? 1 : 0
    }

    /// COMPASS (FUN_10d8_0f68 -> FUN_1208_39a8 -> 1208:0574): the current figure's facing in whole degrees, the integer part (>> 8,
    /// floor) of the 8.8 angle atan2(m[1][0], m[1][1]) of the orientation matrix row 1 (vtable +0x20; z is zeroed and the vector
    /// normalised first). 0 along +y, positive toward +x; equal to Figure.heading wrapped to -180..180 (see `orientation`). No current
    /// figure: the original reports an error and returns 0; the port returns 0 silently (a script process may still name a figure the
    /// port has retired, e.g. FIRSTBOT in DR_ZAP3_FIRSTBOT). ASSUMPTION: exact atan2 instead of the engine's sine-table inverse (1210:0e6b / 0f2f), which may differ by a
    /// degree near the cut points; a row with x = y = 0 would give 720 (0x2d000), unreachable for a yaw matrix.
    func compass(_ fig: Figure?) -> Int {
        guard let fig else { return 0 }
        let m = orientation(fig)[1]
        if m[0] == 0 && m[1] == 0 { return 720 }
        return Int((atan2(Double(m[0]), Double(m[1])) * 180 / .pi * 256).rounded(.toNearestOrEven)) >> 8
    }

    /// HEADING <object> (FUN_10d8_26f2): the direction the object moved in its last frame, in the COMPASS convention. d = frame start
    /// position (+0xba, `prevPos`) minus the position (+0xb), x and y as 32-bit differences. When the 16-bit sum of the absolute low
    /// words is 0 or negative (the original tests only the low words) it returns 666 (0x29a). Else a = atan(dy / dx) in whole degrees
    /// (FUN_1200_097a: the 24.8 divide dy / dx through the atan table 1210:0f2f, or -90 / 90 by the sign of dy when dx = 0) and the
    /// result is -(a + 90) for dx < 0, 90 - a otherwise: 0 = moving toward -y, 90 = toward -x, -90 = toward +x, 180 = toward +y, so a
    /// forward-walking figure's HEADING equals its COMPASS. Unknown object: error, 0. Items keep no frame start position in the ports
    /// (-> 0). ASSUMPTION: exact atan instead of the table (floor of the 8.8 angle).
    func motionHeading(_ proc: ScriptProcess, _ ref: ScriptValue) -> Int {
        let sel = pyStr(ref).uppercased()
        guard let obj = figure(sel == "CURFIG" ? proc.curFig : sel) else {
            if sel != "CURITEM" && itemByType(sel) == nil { warn("HEADING \(pyStr(ref)): no such object") }
            return 0
        }
        guard let pos = obj.pos else { return 0 }
        let prev = obj.prevPos ?? pos
        let dx = wrap32(Int(prev.x.rounded(.toNearestOrEven)) - Int(pos.x.rounded(.toNearestOrEven)))
        let dy = wrap32(Int(prev.y.rounded(.toNearestOrEven)) - Int(pos.y.rounded(.toNearestOrEven)))
        func lowAbs(_ v: Int) -> Int { abs(Int(Int16(truncatingIfNeeded: v))) }      // |int16(low word)|, the CWD / XOR / SUB idiom
        let total = (lowAbs(dx) + lowAbs(dy)) & 0xffff
        if total == 0 || total & 0x8000 != 0 { return 0x29a }
        let deg: Int
        if dx != 0 {
            deg = Int((atan(Double(fixDiv(dy, dx)) / 256) * 180 / .pi * 256).rounded(.toNearestOrEven)) >> 8
        } else {
            deg = dy < 0 ? -90 : 90
        }
        return dx < 0 ? -(deg + 90) : 90 - deg
    }

    /// AMINEXTENT <object> <extent> (FUN_10d8_06ef): AMINWAYPOINT's twin against the first PHYS (DGROUP list 1cf5/1cfd, FUN_1050_0996) of
    /// that name: whether the object's hull (+0x65) touches the PHYS box (FUN_1070_0aba -> FUN_1058_173c, inclusive). A missing argument,
    /// object or PHYS reports an error and returns 0. An item's hull is `objectHull`.
    func amInExtent(_ proc: ScriptProcess, _ obj: ScriptValue, _ extent: ScriptValue) -> Int {
        let name = pyStr(extent).uppercased()
        let o = scriptObject(proc, obj)
        guard o.fig != nil || o.item != nil, !name.isEmpty else {
            warn("AMINEXTENT \(pyStr(obj)) \(pyStr(extent)): no such object")
            return 0
        }
        guard let p = data.phys.first(where: { $0.name.uppercased() == name }) else {
            warn("AMINEXTENT \(pyStr(obj)) \(pyStr(extent)): no such extent")
            return 0
        }
        guard let h = objectHull(o) else { return 0 }
        let lo = SIMD3(Int(p.lo.x), Int(p.lo.y), Int(p.lo.z)), hi = SIMD3(Int(p.hi.x), Int(p.hi.y), Int(p.hi.z))
        return Self.boxesTouch(h.lo, h.hi, lo, hi) ? 1 : 0
    }

    /// FLOATATHEIGHT <waypoint> [MAXIMUM] (FUN_10d0_2f91). No current figure: nothing. A missing waypoint name or an unknown waypoint
    /// (WAYP list 1cdd): error. With MAXIMUM (any other second word is an error; the figure needs an area, +0x35): +0x14e := waypoint z
    /// - the area anchor's base z (PHYS +0x13), a z limit `mover` applies. Without it the original sets the figure's F (model +0x88 and
    /// +0x225) to waypoint z - the support under the waypoint (FUN_1060_0d9a), zeroes model +0xa6 and re-places the figure at
    /// support + F with vtable +0x2c (`floatAtHeight`; R lives in the pose).
    func cmdFloatAtHeight(_ fig: Figure, _ args: [ScriptValue]) {
        guard let wp = data.waypoints[pyStr(args[0]).uppercased()] else { warn("FLOATATHEIGHT \(pyStr(args[0])): no such waypoint"); return }
        if args.count < 2 || pyStr(args[1]).isEmpty {
            floatAtHeight(fig, wp)
        } else if pyStr(args[1]).uppercased() != "MAXIMUM" {
            warn("FLOATATHEIGHT \(pyStr(args[0])) \(pyStr(args[1])): expected MAXIMUM")
        } else if let area = fig.area ?? (fig.pos.flatMap { updateArea(fig, at: $0) }?.anchor) {   // ASSUMPTION: a placed figure has its area (the port selects it lazily)
            fig.zCap = wrap32(Int(wp.z) - Int(data.phys[area].lo.z))
        } else {
            warn("FLOATATHEIGHT \(pyStr(args[0])) MAXIMUM: \(fig.name) has no area")
        }
    }

    /// SETCURRENTFIGURE's fallback (FUN_10c0_3e14): it walks the figure list comparing the name with the instance name (+0xf7), then
    /// +0x178 (an upper-cased copy of the creation name at +2, written by FUN_1088_2608) and +2 itself, i.e. the figure's type name. So
    /// `SETCURRENTFIGURE (GRDCELL)` still finds GUARD1 after `INDIVIDUALIZE CURFIG GUARD1`. ASSUMPTION: +2 is the FIGR record's name
    /// field (the BODY type); the first figure in list order wins.
    func figureByType(_ rawName: String) -> Figure? {
        let name = rawName.uppercased()
        if let fig = figures.values.first(where: { $0.type.uppercased() == name }) { return fig }
        for inst in data.figDefOrder where data.figDefs[inst]!.type.uppercased() == name && !killedFigures.contains(inst) {
            return figure(inst)
        }
        return nil
    }

    /// DISTFROMWAYPOINT (10d8:16a6), 2DDISTFROMWAYPOINT (0534), ANGLEFROMWAYPOINT (0d10) and AMINWAYPOINT (0905) for
    /// `<object> <waypoint>`. The object is CURFIG, CURITEM or a figure / floor item name (FUN_10c0_16a8); the waypoint comes from the
    /// WAYP list (1290:1cdd). Distances are `cmFromUnits` of the object's position against the waypoint: DISTFROMWAYPOINT the 3D
    /// length (FUN_1208_13e3 = approxLength of the three differences), 2DDISTFROMWAYPOINT the exact 2D length (FUN_1210_000d, the
    /// DISTFROMENEMY pair); ANGLEFROMWAYPOINT is the figure's bearing of the point (the same value as ANGLEFROMENEMY); AMINWAYPOINT is
    /// FUN_1070_0aba, the hull box against the point (inclusive, the AMINTRIGGER test). Unknown object or waypoint: the original
    /// reports an error and returns 0.
    func waypointQuery(_ proc: ScriptProcess, _ name: String, _ ref: ScriptValue, _ waypoint: ScriptValue) -> Int {
        let wp = pyStr(waypoint).uppercased()
        let obj = scriptObject(proc, ref)
        let point = data.waypoints[wp]
        guard (obj.fig != nil || obj.item != nil), let point else {
            warn("\(name) \(pyStr(ref)) \(pyStr(waypoint)): no such \((obj.fig != nil || obj.item != nil) ? "waypoint" : "object")")
            return 0
        }
        guard let objPos = objectPos(obj) else { return 0 }
        let d = objPos - point
        let dx = Int(d.x.rounded(.toNearestOrEven)), dy = Int(d.y.rounded(.toNearestOrEven)), dz = Int(d.z.rounded(.toNearestOrEven))
        if name == "DISTFROMWAYPOINT" { return cmFromUnits(approxLength(dx, dy, dz)) }
        if name == "2DDISTFROMWAYPOINT" { return cmFromUnits(length2d(dx, dy)) }
        if name == "ANGLEFROMWAYPOINT" {
            guard let fig = obj.fig else { return 0 }          // items have no facing in the ports
            return Int(relAngle(fig, point).rounded(.toNearestOrEven))
        }
        guard let h = objectHull(obj) else { return 0 }
        let p = SIMD3(Int(point.x), Int(point.y), Int(point.z))
        return Self.boxesTouch(h.lo, h.hi, p, p) ? 1 : 0
    }

    /// The `<object>` argument of the position functions (FUN_10c0_16a8): CURFIG, CURITEM or a figure / floor item name.
    func scriptObjectPos(_ proc: ScriptProcess, _ ref: ScriptValue) -> (found: Bool, pos: V3?) {
        let o = scriptObject(proc, ref)
        return (o.fig != nil || o.item != nil, objectPos(o))
    }

    /// DISTFROMEXTENT (10d8:136a) and DISTFROMTRIGGER (10d8:1566) for `<object> <name>`: the 3D length (FUN_1208_13e3 = approxLength) in
    /// `cmFromUnits` from the object's +0xb position to the centre of the first PHYS / IMAG of that name (the lists AMINEXTENT /
    /// AMINTRIGGER search). The centre is vtable +0x50 (FUN_1068_02cb for a PHYS, FUN_1068_0f4c for an IMAG): per axis (lo + hi) << 8 /
    /// 0x200 = trunc((lo + hi) / 2). Unknown object or name: error, 0.
    func boxDistance(_ proc: ScriptProcess, _ name: String, _ ref: ScriptValue, _ boxName: ScriptValue) -> Int {
        let bn = pyStr(boxName).uppercased()
        let obj = scriptObjectPos(proc, ref)
        var box: (lo: SIMD3<Int>, hi: SIMD3<Int>)?
        if name == "DISTFROMEXTENT" {
            if let p = data.phys.first(where: { $0.name.uppercased() == bn }) {
                box = (SIMD3(Int(p.lo.x), Int(p.lo.y), Int(p.lo.z)), SIMD3(Int(p.hi.x), Int(p.hi.y), Int(p.hi.z)))
            }
        } else if let t = data.triggers.first(where: { $0.name == bn }) {
            box = (t.lo, t.hi)
        }
        guard obj.found, let box else {
            warn("\(name) \(pyStr(ref)) \(pyStr(boxName)): no such \(!obj.found ? "object" : name == "DISTFROMEXTENT" ? "extent" : "trigger")")
            return 0
        }
        guard let pos = obj.pos else { return 0 }
        let c = (0..<3).map { fixDiv(box.lo[$0] + box.hi[$0], 0x200) }
        let d = (0..<3).map { Int(pos[$0].rounded(.toNearestOrEven)) - c[$0] }
        return cmFromUnits(approxLength(d[0], d[1], d[2]))
    }

    /// DISTFROMITEM (10d8:14aa, 3D: approxLength) and 2DDISTFROMITEM (10d8:02d0, exact length2d of x, y): the process's current item
    /// against its current figure, in `cmFromUnits` of item position - figure position. No current item or figure: error, 0.
    func itemDistance(_ proc: ScriptProcess, _ name: String) -> Int {
        let item = items[proc.curItem ?? ""], fig = figure(proc.curFig)
        guard let item, let fig else {
            warn("\(name): no current \(item == nil ? "item" : "figure")")
            return 0
        }
        guard let ip = itemEnginePos(item), let fp = fig.pos else { return 0 }       // floor position, hand pose or the holder's origin
        let d = (0..<3).map { Int(ip[$0].rounded(.toNearestOrEven)) - Int(fp[$0].rounded(.toNearestOrEven)) }
        return cmFromUnits(name == "DISTFROMITEM" ? approxLength(d[0], d[1], d[2]) : length2d(d[0], d[1]))
    }

    /// 2DDISTFROMCOORDS <object> <x> <y> (10d8:0000): x and y are script integers in COORDX units (<< 8 gives world units); the exact
    /// 2D length from the object to that point in `cmFromUnits`. Unknown object: error, 0.
    func distanceFromCoords(_ proc: ScriptProcess, _ ref: ScriptValue, _ x: Int, _ y: Int) -> Int {
        let obj = scriptObjectPos(proc, ref)
        guard obj.found else { warn("2DDISTFROMCOORDS \(pyStr(ref)): no such object"); return 0 }
        guard let pos = obj.pos else { return 0 }
        return cmFromUnits(length2d((x << 8) - Int(pos.x.rounded(.toNearestOrEven)), (y << 8) - Int(pos.y.rounded(.toNearestOrEven))))
    }

    /// FINDFIRSTFIGURE (statement, 10d0:2f1a): the process's current figure := entry 0 of the engine figure list and its index (+0x42)
    /// := 0. FINDNEXTFIGURE (10d8:181c): while index < count - 1, index += 1, current figure := that entry and return 1; otherwise
    /// return 0 and leave the current figure. ASSUMPTION: the list is `figures` in insertion order. The original (DGROUP 0x1d19 /
    /// 0x1d21) is the level's FIGR records then the created figures with the player last (live CHAOS: USE_BOT, FIRSTBOT, FIDO,
    /// HALMECHO, CAYNAN, GUARD1, LEX), so the order differs; the only users (COMMON.scr quake loops) act on every figure, so the
    /// outcome does not. An empty list leaves the current figure unchanged.
    func findFigure(_ proc: ScriptProcess, first: Bool) -> Int {
        let names = figures.keys
        if first {
            proc.figIndex = 0
            if let n = names.first { proc.curFig = n }
            return 0
        }
        guard proc.figIndex < names.count - 1 else { return 0 }
        proc.figIndex += 1
        proc.curFig = names[proc.figIndex]
        return 1
    }

    /// APPLY <object> <mode> <texture> [PICTURE <frame> [<flic prefix>]] (FUN_10d0_0843 -> SCANNER.C FUN_10f8_08a9): the texture decal
    /// system. The scanner walks the object's model textures (the name or ALL) and FUN_10f8_0712 switches on the mode name (table at
    /// 1290:4ce8): DRAW and DRAWONLY restore the texture from its backup copy (made on first use, FUN_1168_027c) and then draw a frame
    /// of the picture FLIC over it; RESTORE only restores; CLEAR backs the texture up, fills it with 0xff (transparent) and draws the
    /// frame. The picture is `<prefix>0PIC.FLC` ("CAY0PIC.FLC", "GRD0PIC.FLC" in the script comments). Those FLICs are not in the
    /// shipped data, so a draw is recorded but cannot be rendered; the port keeps the state in `Figure.decals` ({texture: (mode, frame,
    /// prefix)}; absent = original texture) and the renderer does not use it. Warns for an unknown mode or texture.
    func applyDecal(_ fig: Figure?, _ args: [ScriptValue]) {
        guard let fig else { return }
        let rest = args.dropFirst()
        let words = rest.compactMap { v -> String? in if case .str(let s) = v { return s }; return nil }
        let nums = rest.compactMap { v -> Int? in if case .int(let i) = v { return i }; return nil }
        let mode = words.first?.uppercased() ?? ""
        let texture = words.count > 1 ? words[1].uppercased() : ""
        guard ["DRAW", "DRAWONLY", "RESTORE", "CLEAR"].contains(mode) else { warn("APPLY \(mode): unknown mode"); return }
        let names = fig.assets.assets.mesh.textures.map { $0.name.uppercased() }
        let targets = texture == "ALL" ? names : names.contains(texture) ? [texture] : []
        if targets.isEmpty { warn("APPLY \(fig.name) \(texture): no such texture"); return }
        for tex in targets {
            if mode == "RESTORE" {
                fig.decals[tex] = nil
            } else if words.count > 2 {                       // a PICTURE argument follows: draw its frame
                // ASSUMPTION: the default prefix is the figure's first three letters (CAY, GRD)
                let prefix = words.count > 3 ? words[3].uppercased() : String(fig.type.prefix(3)).uppercased()
                fig.decals[tex] = (mode, nums.first ?? 0, prefix)
            } else if mode == "CLEAR" {
                fig.decals[tex] = (mode, nil, nil)
            } else {
                fig.decals[tex] = nil                         // DRAW without a picture: restored, nothing to draw
            }
        }
    }

    /// 1000:252d followed by 1000:2727 with CL = 8: retain the low signed 32 bits of a product, then arithmetic-shift it.
    func fixedMul8(_ a: Int32, _ b: Int32) -> Int32 {
        Int32(truncatingIfNeeded: Int64(a) * Int64(b)) >> 8
    }

    func abs32(_ value: Int32) -> Int32 { value < 0 ? 0 &- value : value }

    /// FUN_1058_12c7 / 142d: x*y then z, shifting eight bits after each multiply. The overlap is zero when boxes only touch.
    func fixedVolume(_ lo: SIMD3<Int>, _ hi: SIMD3<Int>) -> Int32 {
        let x = Int32(truncatingIfNeeded: hi.x) &- Int32(truncatingIfNeeded: lo.x)
        let y = Int32(truncatingIfNeeded: hi.y) &- Int32(truncatingIfNeeded: lo.y)
        let z = Int32(truncatingIfNeeded: hi.z) &- Int32(truncatingIfNeeded: lo.z)
        return abs32(fixedMul8(fixedMul8(x, y), z))
    }

    func overlapVolume(_ h: (lo: SIMD3<Int>, hi: SIMD3<Int>), _ b: PhysBox) -> Int32 {
        let lo = SIMD3(max(h.lo.x, b.lo.x), max(h.lo.y, b.lo.y), max(h.lo.z, b.lo.z))
        let hi = SIMD3(min(h.hi.x, b.hi.x), min(h.hi.y, b.hi.y), min(h.hi.z, b.hi.z))
        guard all(lo .< hi) else { return 0 }
        return fixedVolume(lo, hi)
    }

    /// The shared 1058 collision score starts with the hull volume, adds state-1 overlaps, subtracts state-0 overlaps,
    /// and ignores state 2. ADD/ADC and SUB/SBB make this signed 32-bit wrapping arithmetic in both area and no-area paths.
    func collisionScore(_ h: (lo: SIMD3<Int>, hi: SIMD3<Int>), members: [Int]) -> Int32 {
        let boxes = physBoxes()
        var score = fixedVolume(h.lo, h.hi)
        for i in members {
            let b = boxes[i], overlap = overlapVolume(h, b)
            if b.state == 1 { score &+= overlap }
            else if b.state == 0 { score &-= overlap }
        }
        return score
    }

    /// One figure's physics for a 30 fps frame (FUN_1088_39ef after the animation): gravity, then the frame move; see world.py `settle`.
    ///
    /// Gravity, for figures with the gravity flag inside an area: the hull's floor (support) more than half the hull height
    /// (2 * (dz / 4), fig+0x14a) below the hull bottom starts a fall (FUN_10a0_0072); otherwise the whoah edge probes run
    /// (FUN_10a0_009b). A falling figure gains -[83a0]/5 of z velocity per frame while vz > -0x500 (so down to -1326). A figure at
    /// rest (vz == 0) stands on its support: origin z = support + F (the root z stays in the pose). Then frameMove moves every
    /// figure, gravity flag or not. A rising motion (header flag 2, `rises`) skips the fall start, the whoah probes and the stand on the
    /// support: its root z is committed at its wraps and end instead (advance, Figure.setMotion). ASSUMPTIONS: one tick is one engine
    /// frame at 30 fps; the fall does not suspend scripts.
    func settle(_ fig: Figure) {
        guard fig.pos != nil, fig.frames != nil else { return }
        if fig.gravity && !fig.rises {
            let (lo, hi) = hull(fig)
            if let area = updateArea(fig, at: fig.pos!, hull: (lo: lo, hi: hi)) {
                let sup = support(lo, hi, area: area)
                let thr = lo.z - 2 * floorDiv(hi.z - lo.z, 4)
                if sup < thr {
                    if fig.vz == 0 && !fig.falling {
                        fig.falling = true
                        fallStart(fig)
                    }
                } else if fig.vz == 0 && !fig.falling && !fig.invulnerable {
                    whoah(fig, lo, hi, thr, area)
                }
                if fig.falling && fig.vz > Self.fallVMin { fig.vz -= Self.fallDV }
                if fig.vz == 0 && !fig.noCollide { fig.pos!.z = Double(sup + foot(fig)) }
            }
        }
        frameMove(fig)
    }

    /// FUN_1088_39ef's single mover call per frame: target = the root-motion position (rootDelta, accumulated by advance) plus the
    /// velocity step, pushed (FUN_1088_3629), then moveAndRespond. The step is velocityStep of the persistent velocity: it moves
    /// figures without the gravity flag too, there is no friction, and every non-bouncy collision zeroes the velocity. A figure with
    /// nothing to move only moves when the push displaces it. A GO stride that reached its target (`arriving`) ends the GO once this
    /// move completes: the figure stays where it is, there is no snap to the target. See world.py `frame_move`.
    func frameMove(_ fig: Figure) {
        guard let pos = fig.pos else { return }
        let delta = fig.rootDelta, moved = fig.rootMoved
        fig.rootDelta = V2(0, 0); fig.rootMoved = false
        fig.step = velocityStep([fig.vx, fig.vy, fig.vz])
        var target = pos
        target.x += delta.x; target.y += delta.y
        target += V3(Double(fig.step[0]), Double(fig.step[1]), Double(fig.step[2]))
        target = pushTarget(fig, target)
        if !(moved || fig.step.contains { $0 != 0 }) && target.x == pos.x && target.y == pos.y {
            fig.arriving = false
            return
        }
        let completed = moveAndRespond(fig, target)
        if fig.arriving {
            fig.arriving = false
            if completed, fig.go != nil {
                fig.go = nil
                let after = fig.afterGo ?? ("STAND", true, nil)
                fig.afterGo = nil
                if !fig.setMotion(after.0, loop: after.1) { fig.idx = 0 }
                after.2?.id = fig.motId
            }
        }
    }

    /// FUN_10a0_009b with FUN_1060_006e: edge probes around the hull; see world.py `whoah`.
    func whoah(_ fig: Figure, _ lo: SIMD3<Int>, _ hi: SIMD3<Int>, _ thr: Int, _ area: PhysArea? = nil) {
        let cx = floorDiv(lo.x + hi.x, 2), cy = floorDiv(lo.y + hi.y, 2), h = floorDiv(hi.x - lo.x, 2)
        let hd = fig.heading * Self.radPerDeg, hf = Double(h)
        let dx = Int(sin(hd) * hf), dy = Int(cos(hd) * hf)         // row1 (local +Y) * h; forward is -row1
        let sx = Int(cos(hd) * hf), sy = Int(-sin(hd) * hf)        // row0 (local +X) * h
        let probes = [("WHOAH_FORWARD", cx - dx, cy - dy), ("WHOAH_BACKWARD", cx + dx, cy + dy),
                      ("WHOAH_LEFT", cx + sx, cy + sy), ("WHOAH_RIGHT", cx - sx, cy - sy)]
        for (name, x, y) in probes {
            let f = pointFloor(x, y, lo.z, hi.z, area: area)
            if Self.noFloor < f && f < thr {
                if !fig.teeter {
                    fig.teeter = true
                    fig.setMotion(name, loop: false)
                }
                return
            }
        }
        fig.teeter = false
    }

    /// Move a figure by `delta` through the engine mover and its collision response, returning whether the move completed (false:
    /// blocked or stopped by a trigger); see world.py `figure_move`.
    func figureMove(_ fig: Figure, _ delta: V3, push: Bool = true) -> Bool {
        guard var target = fig.pos else { return false }
        target += delta
        if push { target = pushTarget(fig, target) }      // FUN_1088_3629 runs whatever the collisions flag
        return moveAndRespond(fig, target)
    }

    func figureMove(_ fig: Figure, _ delta: V2, push: Bool = true) -> Bool { figureMove(fig, V3(delta.x, delta.y, 0), push: push) }

    /// FUN_1088_39ef's mover call and what follows it: FUN_10a0_22e1 to `target`, then FUN_10a0_0ead (vtable +0x5c) when the hull
    /// collides or the support is above its bottom where the mover left the figure. A bouncy figure rebounds (bounce), any other takes
    /// collisionResponse (which zeroes the velocity).
    func moveAndRespond(_ fig: Figure, _ target: V3) -> Bool {
        let start = fig.pos!
        let completed = mover(fig, target)
        if fig.collisions && figureBlocked(fig, fig.pos!) {
            if fig.bouncy { bounceCollision(fig, start: start) }
            else { collisionResponse(fig, start: start, blocked: fig.pos!, good: fig.lastGood!) }      // sets fig.pos itself
            return false
        }
        return completed
    }

    /// FUN_10a0_22e1: move to `target` (x, y, z) in steps, true when the whole move completed unobstructed. +0xe2 (last good) := the
    /// position at entry, before the delta is read. A delta with any axis at or over the local hull span is cut into
    /// n = |d| / smallest span steps (3D length, z included); each step rebuilds the hull, and a blocked one leaves the figure on that
    /// step (and rescales the step by trunc(step * i / n)); a trigger stop at a passing step leaves it there too. Otherwise the figure
    /// goes to the target and the final check may fail there (it stays AT the target, last good unchanged). Collisions off skip every
    /// check. First the +0x14e z cap (FLOATATHEIGHT ... MAXIMUM): with an area (+0x35) and a non-zero cap the target z is limited to the
    /// area anchor's base z (PHYS +0x13, the box bottom) + cap. NOT PORTED: the attached branch (+0x2c). See world.py `mover`.
    func mover(_ fig: Figure, _ target: V3) -> Bool {
        var target = target
        if fig.zCap != 0, let area = fig.area { target.z = min(target.z, Double(wrap32(Int(data.phys[area].lo.z) + fig.zCap))) }
        let start = fig.pos!
        fig.lastGood = start
        if fig.collisions {
            let d = [Int(target.x - start.x), Int(target.y - start.y), Int(target.z - start.z)]
            let h = hull(fig, at: start)
            let spans = h.hi &- h.lo                      // the local hull spans +0x51/55/59
            if !(abs(d[0]) < spans.x && abs(d[1]) < spans.y && abs(d[2]) < spans.z), min(spans.x, spans.y, spans.z) > 0 {     // a zero span: no divide (as the twins)
                let n = moveSteps(d[0], d[1], d[2], min(spans.x, spans.y, spans.z))
                if n > 0 {
                    let inc = V3(Double(fixDiv(d[0], n << 8)), Double(fixDiv(d[1], n << 8)), Double(fixDiv(d[2], n << 8)))
                    for i in 1...n {
                        let candidate = start + inc * Double(i)
                        if figureBlocked(fig, candidate) {
                            fig.pos = candidate
                            fig.step = scaleStep(fig.step, i, n)
                            return false
                        }
                        fig.lastGood = candidate
                        if triggerStop(fig, candidate) {
                            fig.pos = candidate
                            fig.step = scaleStep(fig.step, i, n)
                            return false
                        }
                    }
                }
            }
        }
        fig.pos = target
        if fig.collisions && figureBlocked(fig, target) { return false }
        _ = updateArea(fig, at: target)
        fig.lastGood = fig.pos
        return true
    }

    /// FUN_10a0_0ead's bouncy branch: step := position - frame start (+0xba; the move's start without a frame), a falling figure
    /// stops falling (fall-end method), then the rebound.
    func bounceCollision(_ fig: Figure, start: V3) {
        let prev = fig.prevPos ?? start
        fig.step = [Int(fig.pos!.x - prev.x), Int(fig.pos!.y - prev.y), Int(fig.pos!.z - prev.z)]
        if fig.falling {
            fig.falling = false
            fallEnd(fig)
        }
        bounce(fig)
    }

    /// FUN_1070_0fa7, generic 3D. P = the blocked position. Six candidates in order X, Y, Z, XY, XZ, YZ, each P minus the step on those
    /// axes (the step is re-read for every candidate: a mover call can rescale it) and each moved to by the mover from wherever the
    /// previous attempt left the figure. The first whose hull bottom is strictly above the support with a zero PHYS score, where the
    /// figure ends up, is accepted and the velocity components of its axes are negated. If none is, the mover is called with the
    /// pointer to last good (+0xe2), which the mover overwrites with the current position before it reads the target, so the figure
    /// stays where the YZ attempt left it and all three components are negated. Always after: v -= (v * ELASTICITY) >> 8 for the
    /// velocity and the step, and `_<TYPE>_BOUNCE` plays when the sound exists. See world.py `bounce`.
    func bounce(_ fig: Figure) {
        let p = fig.pos!
        var axes = [0, 1, 2]
        var accepted = false
        for cand in [[0], [1], [2], [0, 1], [0, 2], [1, 2]] {
            var target = p
            for a in cand { target[a] = p[a] - Double(fig.step[a]) }
            _ = mover(fig, target)
            let q = queryHull(fig)
            if q.lo.z > q.sup && !hullCollides(fig) { axes = cand; accepted = true; break }
        }
        if !accepted { _ = mover(fig, fig.pos!) }
        var v = [fig.vx, fig.vy, fig.vz]
        for a in axes { v[a] = -v[a] }
        let e = fig.elasticity
        fig.vx = v[0] - fixMul(v[0], e); fig.vy = v[1] - fixMul(v[1], e); fig.vz = v[2] - fixMul(v[2], e)
        fig.step = fig.step.map { $0 - fixMul($0, e) }
        if let idx = soundIndex(.str("_\(fig.type)_BOUNCE")) { playSound(idx, fig: fig) }
    }

    /// The object a velocity statement / function addresses: CURFIG (`cur`), CURITEM (the process's item) or a figure / item name; nil for
    /// an unknown one. Items keep their velocity like figures (WorldEffects.swift moves the free ones).
    func velocityFigure(_ ref: ScriptValue, _ cur: Figure?, _ proc: ScriptProcess) -> VelocityObject? {
        let r = pyStr(ref).uppercased()
        let item: Item
        if r == "CURITEM" {
            guard let i = items[proc.curItem ?? ""] else { return nil }
            item = i
        } else {
            let fig = r == "CURFIG" ? cur : figure(r)
            if let fig { return fig }
            guard let i = itemByType(r) else { return nil }
            item = i
        }
        loadItemPhysics(item)
        return item
    }

    /// The figure's matrix (+0x110) rows in 8.8 (256 = 1.0) for a pure yaw: row 0 = (cos h, -sin h), row 1 = (sin h, cos h) =
    /// -forward(), row 2 = up. ASSUMPTION: the engine's persistent matrix equals the FK table rotation of the heading.
    func orientation(_ fig: Figure) -> [[Int]] {
        var m = [[256, 0, 0], [0, 256, 0], [0, 0, 256]]
        if let T = resources.cosTable { rot8(T, &m, Int((-fig.heading * 256).rounded(.toNearestOrEven)), 0, 1, 1) }
        return m
    }

    /// LEAP <obj> [target] <pitch> <speed> (FUN_10d0_42c4): v += row1 * k, k = (speed << 3 << 8) / 100 (signed, truncating; speed is cm
    /// per frame, 20.48 units per cm) through 0c42, row1 of the matrix after an X rotation by pitch degrees (the pitch tilts row 1
    /// toward row 2, up). Without a target the matrix is the object's own: row 1 is BACKWARD, so a positive speed pushes backward (the
    /// zero-g gun recoil) and a negative one forward (ledge leaps). With a target the matrix is built toward it: row 1 = normalised
    /// (target - object), so a positive speed pulls toward it (LEAP CURFIG GRAVPT 0 2). An unknown target does nothing. ASSUMPTIONS:
    /// row 0 = normalised (dy, -dx, 0) and row 2 = row 0 x row 1 (the cross-product order of 1208:0154 is not decoded; shipped scripts
    /// only use pitch 0 with a target, which it does not affect); the +/-0x38 renormalise after the rotation is not modelled.
    func leap(_ fig: VelocityObject, _ pitch: Int, _ speed: Int, target: ScriptValue? = nil) {
        var m: [[Int]]
        if let target {
            guard let t = self.target(pyStr(target)), let fp = fig.pos else {
                warn("LEAP \(pyStr(target)): no such object")
                return
            }
            let d = [t.xy.x - fp.x, t.xy.y - fp.y, t.z - fp.z]
            func unit(_ v: [Double]) -> [Int] {
                let n = (v[0] * v[0] + v[1] * v[1] + v[2] * v[2]).squareRoot()
                return n == 0 ? [0, 0, 0] : v.map { Int((256 * $0 / n).rounded(.toNearestOrEven)) }
            }
            let r1 = unit(d)
            let r0 = d[0] != 0 || d[1] != 0 ? unit([d[1], -d[0], 0]) : [256, 0, 0]
            let a = r0.map(Double.init), b = r1.map(Double.init)
            let r2 = unit([a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]])
            m = [r0, r1, r2]
        } else if let item = fig as? Item {                // an item has its own matrix
            m = item.matrix.map { $0.r.map { [Int((256 * $0.x).rounded(.toNearestOrEven)), Int((256 * $0.y).rounded(.toNearestOrEven)), Int((256 * $0.z).rounded(.toNearestOrEven))] } }
                ?? [[256, 0, 0], [0, 256, 0], [0, 0, 256]]
        } else {
            m = orientation(fig as! Figure)
        }
        addLeap(fig, &m, pitch, speed)
    }

    /// The tail of LEAP and THROWCURITEM: `m` (8.8 rows, modified) turned about X by `pitch` degrees, then v += row1 * k with
    /// k = trunc((speed << 11) / 100).
    func addLeap(_ obj: VelocityObject, _ m: inout [[Int]], _ pitch: Int, _ speed: Int) {
        if let T = resources.cosTable { rot8(T, &m, pitch << 8, 1, 2, 1) }
        let x = wrap32(speed << 11)
        let k = abs(x) / 100 * (x >= 0 ? 1 : -1)
        obj.vx += fixMul(m[1][0], k)
        obj.vy += fixMul(m[1][1], k)
        obj.vz += fixMul(m[1][2], k)
    }

    /// FUN_1088_3629: before a living figure (~0 > 0) moves, every other figure that is visible, alive and colliding pushes a colliding
    /// target out of the circle of their summed PERSONAL_RADIUS; then each ADDAVOIDANCEPOINT object pushes it out of (r << 11) / 100
    /// (r in cm), whatever its collisions flag.
    func pushTarget(_ fig: Figure, _ target: V3) -> V3 {
        guard hitPoints(fig) > 0 else { return target }
        var target = target
        if fig.collisions {
            for other in figures.values {
                guard other !== fig, let op = other.pos, !other.hidden, other.collisions, hitPoints(other) > 0 else { continue }
                target = pushOut(target: target, other: op, r: personalRadius(fig) + personalRadius(other))
            }
        }
        for (name, r) in fig.avoid {
            guard !name.isEmpty, let point = self.target(name) else { continue }   // a saved entry whose object is gone stays listed
            target = pushOut(target: target, other: V3(point.xy.x, point.xy.y, point.z), r: (r << 11) / 100)
        }
        return target
    }

    /// ADDAVOIDANCEPOINT <object> <radius cm> (10d0:0178 -> FUN_1098_0b88): the radius must be > 0 and the object must exist; a full
    /// list (8) refuses, an object already listed keeps its old radius.
    func addAvoidance(_ fig: Figure, _ name: String, _ radius: ScriptValue) {
        let name = resolve(name)
        guard case .int(let r) = radius, r > 0, target(name) != nil, fig.avoid.count < Self.maxAvoid else {
            warn("ADDAVOIDANCEPOINT \(name) \(pyStr(radius)): refused")
            return
        }
        if !fig.avoid.contains(where: { $0.name == name }) { fig.avoid.append((name, r)) }
    }

    /// REMOVEAVOIDANCEPOINT <object> (FUN_1098_0c52): later entries shift down; the scan covers slots 0..6 only.
    func removeAvoidance(_ fig: Figure, _ name: String) {
        let name = resolve(name)
        if let i = fig.avoid.prefix(Self.maxAvoid - 1).firstIndex(where: { $0.name == name }) { fig.avoid.remove(at: i) }
    }

    /// FUN_1088_2a87: PERSONAL_RADIUS (default 45 cm) in world units at the hull scale, fig+0x1e3.
    func personalRadius(_ fig: Figure) -> Int {
        hullUnits(prop(fig, "PERSONAL_RADIUS", 45))
    }

    /// FUN_1098_0088, once per motion start: MY_SPEED x frame time, then for any figure but the player - (level << 6) at
    /// difficulty level 1..2 ([a36e] = _difficulty_level) or + 0x80 at level 0; for the player, repeating the same ATK_H*/ATK_F*
    /// attack (not ATK_F2*, ATK_SHO*, ATK_F9*) adds count * 64 * level * 16 per repeat, ATK_F9* starts a reset timer and any
    /// other motion clears the count; the count also clears 0x2d clock ticks after the timer starts. See world.py.
    func motionDuration(_ fig: Figure) -> Int {
        if let d = fig.duration, fig.durId == fig.motId { return d }
        var dur = fig.speed * (fig.motionInfo?.frameTime ?? 0)
        var level = 0
        if let vm, case .int(let v)? = vm.globals["_difficulty_level"] { level = v }
        if fig === player {
            let clock = gameTick * 2                                  // [8330]
            if comboTimer != 0 && clock - comboTimer > 0x2d { fig.comboName = ""; fig.comboCount = 0; comboTimer = 0 }
            let name = (fig.motion ?? "").uppercased()
            if (name.hasPrefix("ATK_H") || name.hasPrefix("ATK_F"))
                && !(name.hasPrefix("ATK_F2") || name.hasPrefix("ATK_SHO") || name.hasPrefix("ATK_F9")) {
                if name == fig.comboName {
                    fig.comboCount = (fig.comboCount + 1) & 0xff
                    dur += Int(Int16(truncatingIfNeeded: (fig.comboCount << 6) * (level << 4)))   // 16-bit IMUL, low word
                } else {
                    fig.comboCount = 0
                }
                fig.comboName = name; comboTimer = 0
            } else if name.hasPrefix("ATK_F9") {
                if comboTimer == 0 { comboTimer = clock }
            } else {
                fig.comboName = ""; fig.comboCount = 0; comboTimer = 0
            }
        } else {
            dur += level == 0 ? 0x80 : -(level << 6)
        }
        fig.duration = dur; fig.durId = fig.motId
        return dur
    }

    /// vtable +0x58 (FUN_10a0_1ff0 via FUN_10a0_2158 when `raw`): position, last good (+0xe2) and previous (+0xba) all become `pos`; the
    /// hull, area and support are rebuilt and every velocity is zeroed (FUN_1070_1e9d). Unless raw, a gravity figure inside an area is
    /// then stood on its floor: z = support + F (the engine's floor + F + R; the port keeps R in the pose). `raw` sets the +0x1e8 guard
    /// around the call, which skips that snap. See world.py `set_pos`.
    func setPos(_ fig: Figure, _ pos: V3, raw: Bool = false) {
        fig.rawSetPos = raw
        fig.storedHull = nil                    // the engine rebuilds the hull here
        setPosTrace?.append(pos)
        fig.pos = pos
        fig.prevPos = pos; fig.lastGood = pos
        _ = updateArea(fig, at: pos)
        fig.vx = 0; fig.vy = 0; fig.vz = 0
        fig.step = [0, 0, 0]                    // FUN_1070_1e9d zeroes +0xc6..+0xdc
        if !raw && !fig.rises && fig.gravity && fig.area != nil && fig.frames != nil {          // a rising motion keeps +0x1e8 set: no snap
            let h = hull(fig)
            fig.pos!.z = Double(support(h.lo, h.hi) + foot(fig))      // global: SetPos passes a null area (10a0:1ff0)
            fig.prevPos = fig.pos; fig.lastGood = fig.pos
        }
        fig.rawSetPos = false
    }

    /// FUN_1070_0f68: the PHYS (index) of the largest state-1 overlap with the hull (what FUN_1058_1a1b leaves at +0x8d), else the area's
    /// anchor PHYS, else nil.
    func collider(_ fig: Figure) -> (index: Int, lo: SIMD3<Int>, hi: SIMD3<Int>)? {
        let h = queryHull(fig), boxes = physBoxes()
        let members = physAreas().first { $0.anchor == fig.area }?.members ?? Array(boxes.indices)
        var best: Int?, vol: Int32 = 0
        for i in members {
            let b = boxes[i]
            let lo = SIMD3(max(h.lo.x, b.lo.x), max(h.lo.y, b.lo.y), max(h.lo.z, b.lo.z))
            let hi = SIMD3(min(h.hi.x, b.hi.x), min(h.hi.y, b.hi.y), min(h.hi.z, b.hi.z))
            if b.state == 1 && all(lo .< hi) && fixedVolume(lo, hi) > vol { best = i; vol = fixedVolume(lo, hi) }
        }
        if best == nil, let a = fig.area { best = a }
        return best.map { ($0, boxes[$0].lo, boxes[$0].hi) }
    }

    /// FUN_1058_1a1b != 0 for the figure's rebuilt hull in its selected area (FUN_1058_192f without one).
    func hullCollides(_ fig: Figure, at pos: V3? = nil) -> Bool {
        let area = updateArea(fig, at: pos ?? fig.pos!)
        let h = queryHull(fig, at: pos)
        return collisionScore((lo: h.lo, hi: h.hi), members: area?.members ?? Array(physBoxes().indices)) > 0
    }

    /// FUN_10a0_0ead for a non-bouncy figure at its blocked position (the bouncy path is bounceCollision). Sets fig.pos. z velocity
    /// non-zero: verticalResponse. Otherwise: step-up (support above the hull bottom and below bottom + k - R, where k = fig+0x14a =
    /// hull dz / 4 and R = model+0xa6 = the frame's root z, lifts z onto the support and returns); then, unless the +0x1e8 guard is set
    /// or the last good position is the zero vector, the slide (keep the blocked y with the start x, else the blocked x with the start
    /// y, else the last good position); then the tail: velocity zeroed, the mantle and the BONK sound. See world.py `collision_response`.
    func collisionResponse(_ fig: Figure, start: V3, blocked: V3, good: V3) {
        fig.pos = blocked
        let q = queryHull(fig)
        let bottom0 = q.lo.z
        let c = collider(fig)                  // FUN_1070_0f68 at the blocked hull (ASSUMPTION: not the slide's last candidate)
        if fig.vz != 0 { verticalResponse(fig, start: start, good: good, bottom0: bottom0); return }
        if q.sup > bottom0 && q.sup < bottom0 + floorDiv(q.hi.z - q.lo.z, 4) - rootZ(fig) {
            fig.pos!.z += Double(q.sup - bottom0)
            setPos(fig, fig.pos!, raw: true)
            return
        }
        // +0x1e8 is also the running motion's header flag 2 (1098.c:274), so a rising motion (mantle, ladder, iris entry) takes the same
        // guard: the blocked position stands, no slide, no restore, no new mantle (INFERRED from the shared field); see world.py
        let guarded = fig.rawSetPos || fig.rises
        if !guarded && (good.x != 0 || good.y != 0 || good.z != 0) {      // B3: the engine's zero-vector compare skips the slide
            var keepY = start; keepY.y = blocked.y
            var keepX = start; keepX.x = blocked.x
            if !figureBlocked(fig, keepY) { fig.pos = keepY }
            else if !figureBlocked(fig, keepX) { fig.pos = keepX }
            else { setPos(fig, good, raw: true) }
        }
        fig.vx = 0; fig.vy = 0; fig.vz = 0
        if guarded || fig.area == nil { return }
        guard let c, fig.frames != nil else { return }
        let phys = data.phys[c.index]
        if phys.raw.count > 21 && phys.raw[21] & 2 != 0 && c.index != fig.area && fig.motion == "WALK" && fig.engineRequest
            && c.hi.z > queryHull(fig).lo.z && mantleFits(fig, c.lo, c.hi) {
            mantle(fig, abs(c.hi.z - queryHull(fig).sup))
        }
        let tail = phys.raw.count > 45 ? Array(phys.raw[45..<min(54, phys.raw.count)]) : []
        let material = String(decoding: tail.prefix { $0 != 0 }, as: UTF8.self)
        hitSound("_\(fig.type)_BONK_\(fig.motion ?? "")_\(material)", fig: fig)     // FUN_1100_1ce4; silent in the shipped data
    }

    /// FUN_10a0_0ead with a z velocity (fig.pos is the new position, `bottom0` the hull bottom there). Not falling: back to the last good
    /// position, velocity zeroed. The player tries the previous x, y at the new z: if that hull is free it drops its horizontal velocity
    /// and keeps falling. Otherwise it lands: falling cleared, the fall-end method, the previous position when the support is over
    /// 0x1000 above the entry hull bottom (else the hull bottom goes onto the support), FUN_1130_1a2d's unstick, a raw SetPos and the
    /// landing motion for the (by then zero) velocity.
    func verticalResponse(_ fig: Figure, start: V3, good: V3, bottom0: Int) {
        if !fig.falling { setPos(fig, good, raw: true); return }
        if fig === player {
            fig.pos!.x = start.x; fig.pos!.y = start.y
            if !hullCollides(fig) { fig.vx = 0; fig.vy = 0; return }
        }
        let sup = queryHull(fig).sup
        fig.falling = false
        fallEnd(fig)
        if sup > bottom0 + Self.landRevert { fig.pos = start } else { fig.pos!.z += Double(sup - bottom0) }
        unstick(fig)
        setPos(fig, fig.pos!, raw: true)
        requestMotion(fig, Self.landingMotion(fig.vz), loop: false)
    }

    /// FUN_10a0_0e24: land_hard at vz <= -0x280, land_medium at <= -0x140, else land_soft.
    static func landingMotion(_ vz: Int) -> String { vz <= -0x280 ? "LAND_HARD" : vz <= -0x140 ? "LAND_MEDIUM" : "LAND_SOFT" }

    /// FUN_1130_1a2d: SetPos (floor snap) at the position, then up to 40 nudges (i << 8 units, x + for i & 3 in (0, 2), y - for 1 and 3 as
    /// the bytes read) from the original position, each followed by a snapping SetPos, until the hull is clear of the global PHYS list
    /// (FUN_1058_192f) with z equal to the original z; after 40 it returns to the original position.
    func unstick(_ fig: Figure) {
        let p0 = fig.pos!
        setPos(fig, p0)
        var i = 0
        func blocked() -> Bool {
            let h = queryHull(fig)
            return collisionScore((lo: h.lo, hi: h.hi), members: Array(physBoxes().indices)) > 0
        }
        while i < 40 && (blocked() || fig.pos!.z != p0.z) {
            var q = p0
            if i & 3 == 0 || i & 3 == 2 { q.x += Double(i << 8) } else { q.y -= Double(i << 8) }
            setPos(fig, q)
            i += 1
        }
        if i >= 40 { setPos(fig, p0) }
    }

    /// FUN_1098_0e49(fig, name, 1, 1, ...): run the script block `<TYPE>_<NAME>` if the level defines it, else play the motion (an engine
    /// request, so the name is lower case in the original).
    func requestMotion(_ fig: Figure, _ name: String, loop: Bool) {
        if !spawnFor(fig, "\(fig.type.uppercased())_\(name)") && fig.assets.motion(name) != nil {
            fig.manualControl = false
            fig.setMotion(name, loop: loop, engine: true)
        }
    }

    /// FUN_10a0_0ae5: the support within 0x1000 of the collider's top and the facing within 15 degrees of an axis with the hull inside the
    /// collider box shrunk by 0x266 (strict for the 0-degree case); then the facing snaps onto that axis (matrix identity / rotZ).
    /// ASSUMPTION: the engine's yaw is the port's heading, so rounding it to a multiple of 90 is the snap.
    func mantleFits(_ fig: Figure, _ plo: SIMD3<Int>, _ phi: SIMD3<Int>) -> Bool {
        let q = queryHull(fig)
        if abs(phi.z - q.sup) > 0x1000 { return false }
        let ax0 = plo.x + 0x266, ax1 = phi.x - 0x266, ay0 = plo.y + 0x266, ay1 = phi.y - 0x266
        var h = (fig.heading + 180).truncatingRemainder(dividingBy: 360)
        if h < 0 { h += 360 }
        h -= 180
        let ok: Bool
        if -15 < h && h < 15 { ok = q.lo.x > ax0 && q.hi.x < ax1 }
        else if (75 < h && h < 105) || (-105 < h && h < -75) { ok = q.lo.y >= ay0 && q.hi.y <= ay1 }
        else if h > 165 || h < -165 { ok = q.lo.x >= ax0 && q.hi.x <= ax1 }
        else { return false }
        if ok { fig.heading = (h / 90).rounded(.toNearestOrEven) * 90 }
        return ok
    }

    /// FUN_10a0_0d93: request mantle_3 under 0x800, mantle_6 under 0x1000, else mantle_9.
    func mantle(_ fig: Figure, _ height: Int) {
        requestMotion(fig, height < 0x800 ? "MANTLE_3" : height < 0x1000 ? "MANTLE_6" : "MANTLE_9", loop: false)
    }

    /// FUN_10a0_0072's call of the fall-start method (vtable +0x9c, FUN_1088_3196): +0x229 raised, script process suspended.
    func fallStart(_ fig: Figure) { dieMethod(fig, endTask: false) }

    /// vtable +0xa0 (FUN_1088_31fb): +0x229 lowered and, whatever its value, the script process resumed.
    func fallEnd(_ fig: Figure) {
        fig.hold = max(0, fig.hold - 1)
        if let p = fig.aiProc, !p.done { p.suspended = false }
    }

    // MARK: combat / AI

    func enemyFig(_ fig: Figure?) -> Figure? { fig.flatMap { f in f.enemy.flatMap { figure($0) } } }

    /// Signed bearing of `pos` relative to the figure's facing in degrees: positive = to the figure's LEFT.
    func relAngle(_ fig: Figure, _ pos: V3) -> Double {
        let p = fig.pos!
        let d = V2(pos.x - p.x, pos.y - p.y), f = fig.forward()
        return atan2(f.x * d.y - f.y * d.x, f.x * d.x + f.y * d.y) * Self.degPerRad
    }

    func combatQuery(_ fig: Figure?, _ name: String) -> Int {
        let e = name != "ATTACKRADIUS" ? enemyFig(fig) : fig
        guard let fig, let e, let fp = fig.pos, let ep = e.pos else { return 0 }
        switch name {
        case "ATTACKRADIUS": return cmFromUnits(personalRadius(fig))        // FUN_10d8:0e28: the figure's PERSONAL_RADIUS
        case "DISTFROMENEMY":                                                // FUN_10a0_1e61: 2D fixed-point length, then cmFromUnits
            return cmFromUnits(length2d(Int((ep.x - fp.x).rounded(.toNearestOrEven)), Int((ep.y - fp.y).rounded(.toNearestOrEven))))
        default: return Int(relAngle(fig, ep).rounded(.toNearestOrEven))
        }
    }

    /// CONFRONTENEMY (10d0:1c9b): a turn_to_enemy task (FUN_10e8_0000), and the caller waits for it (FUN_1238_0f48). No enemy: an error, nothing happens. ASSUMPTION: a figure
    /// without its turning motions (the error path of vtable +0x7c is not read) faces the enemy at once.
    func startConfront(_ fig: Figure, _ proc: ScriptProcess) {
        guard enemyFig(fig) != nil, fig.pos != nil else { return }
        let wanted = fig.combat ? ["ATK_M4", "ATK_M6"] : ["TURN_LEFT", "TURN_RIGHT"]
        guard fig.frames != nil, wanted.allSatisfy({ fig.assets.motion($0) != nil }) else { turnToEnemy(fig, nil); return }
        let task = ConfrontTask()
        fig.confront = task
        proc.waitPred = { [weak self, weak fig] in fig.map { $0.confront !== task || self?.figures[$0.name] !== $0 } ?? true }
    }

    /// FUN_10e8_0079, once per update: a bearing under 8/256 of a turn ends the motion (FUN_1098_0789(fig, 0, 0)) and turns the rest at once; two updates later the task ends.
    /// Otherwise it asks for atk_m4 / atk_m6 (turn_left / turn_right out of combat, flag 0x40) through vtable +0x7c unless that already plays; the motion gate holds it off during
    /// a recoil. The bearing counts the turning motion's yaw so far, as the task reads it from the model (+0x25).
    func updateConfront(_ fig: Figure) {
        guard let task = fig.confront else { return }
        if task.settled {
            task.count += 1
            if task.count == 2 { fig.confront = nil }
            return
        }
        guard let enemy = enemyFig(fig), let enemyPos = enemy.pos, let f = fig.frames else { fig.confront = nil; return }
        let yaw = fig.turning ? Double(f[fig.idx].limbs[0].z - f[0].limbs[0].z) * 45 / 32 : 0
        let angle = relAngle(fig, enemyPos) - yaw
        if abs(angle) < Self.confrontDone {
            stopFigure(fig, tasks: false)
            turnToEnemy(fig, nil)
            task.settled = true
            return
        }
        let want = fig.combat ? (angle > 0 ? "ATK_M4" : "ATK_M6") : (angle > 0 ? "TURN_LEFT" : "TURN_RIGHT")
        if fig.motion != want, !fig.motionGateRefuses(want) { fig.setMotion(want, loop: true, engine: true) }
    }

    /// TURNTOENEMY TEN_DEGREES turns up to `step` degrees per call toward the enemy; without a step the figure faces it at once.
    func turnToEnemy(_ fig: Figure, _ step: Double?) {
        guard let e = enemyFig(fig), fig.pos != nil, let ep = e.pos else { return }
        let a = relAngle(fig, ep)
        fig.heading -= step.map { max(-$0, min($0, a)) } ?? a       // +heading turns clockwise (right), a > 0 is to the left
    }

    /// AI ON / OFF (10d0:04b3). The counter +0x229 is what counts: ON is vtable +0xa0 (FUN_1088_31fb; refused without hit points, 0xea),
    /// OFF is vtable +0x9c (FUN_1088_3196), which pauses the AI process rather than ending it, and at the first OFF stops the figure as
    /// STOPMOTION does (FUN_1098_0789(fig, 1, 1)) unless NO_STOP_MOTION. A process that turned off its own figure's AI yields at once.
    /// FUN_1098_0745 from a script command: vtable +0x7c = 1098:0e49(fig, "atk_stand" / "stand", 1, 0) creates the motion task without
    /// running it (param 5 is 0), and only its run (10e0:0055) starts the motion on the model. Made during a walk, the task first runs in
    /// the next walk (1238:024c -> 1230:177a), so the figure update in between keeps the old motion and its R (live: LEAVETUBEROOM's AI ON
    /// before TO_0G_USE's STOPMOTION and GO, re/NOTES.md "Lex's height in the zero-g room"). Outside a walk it starts at once.
    func requestIdle(_ fig: Figure) {
        let name = fig.combat ? "ATK_STAND" : "STAND"
        if let vm, vm.walking {
            fig.pendingIdle = (name, vm.tick)
        } else {
            fig.setMotion(name, loop: true, engine: true)
        }
    }

    func cmdAI(_ fig: Figure, _ on: Bool, stop: Bool = true, proc: ScriptProcess? = nil) {
        if on {
            if let vm, let rec = vm.objects[objectKey(fig.name)], case .int(let hp) = rec[0], hp <= 0 {
                // ASSUMPTION: a figure with no object record at all (the lazily made PLAYER of a scenario that never CREATEFIGUREd Lex: the
                // original always has its MAX HPS) counts as alive
                warn("AI ON: \(fig.name) is dead")
                return
            }
            fallEnd(fig)
            if fig === player && fig.hold == 0 {              // the player's +0xa0 (10a8:1f2e) then requests its idle (FUN_1098_0745)
                requestIdle(fig)
            }
            return
        }
        dieMethod(fig, endTask: stop)
        if fig.hold == 1 && stop { stopFigure(fig) }
        if let proc, proc === fig.aiProc { proc.yieldNow = true }
    }

    /// FUN_1098_0789 as AI OFF and the hide pass use it: does nothing while DIE is the current, unfinished motion, else ends the motion
    /// and GO. Unlike STOPMOTION it keeps the idle-fallback bit 0x80 (Figure.noIdle), so a living figure with a motion goes to its idle
    /// at its update's end (1088:4167, FUN_1098_0745: atk_stand in combat mode, else stand); READY_MONSTER_TAUNT waits for that.
    func stopFigure(_ fig: Figure, tasks: Bool = true) {
        if (fig.motion == "DIE" && !fig.finished) || fig.frames == nil { return }
        if tasks { fig.confront = nil }                 // the first argument, 1: FUN_1088_3229 also ends the class 0x109 tasks; turn_to_enemy's own stop passes 0
        fig.idleRequest = !fig.noIdle
        fig.stopMotion()
    }

    /// FUN_1088_3371, the figure update's AI start: visible, alive, counter 0 and no process yet runs "<+0x178>_AI"; a name without a
    /// block starts nothing, silently (FUN_1120_0000), and is tried again next frame. An ended process clears +0x152 (10c0:4098).
    func startEnabledAI(_ fig: Figure) {
        guard let vm, fig.hold == 0, let type = fig.aiType, !type.isEmpty, vm.blocks[type + "_AI"] != nil, !fig.hidden, fig.pos != nil,
              hitPoints(fig) > 0, (fig.aiProc == nil || fig.aiProc!.done) else { return }
        fig.aiProc = vm.spawn(type + "_AI", ctx: spawnContext(fig), run: false)
    }

    /// 1130:050d-..., the camera switch's show / hide pass over the figures but the followed one and the player: not viewed by the camera
    /// (FUN_1088_54e0, so an empty list hides) stops the motion (FUN_1098_0789(fig, 1, 0)), hides and pauses the AI process; viewed again
    /// shows and, with the counter at 0, resumes it. ASSUMPTION kept from "STOPMOTION and hidden figures": evaluated per frame.
    func updateHidden(_ fig: Figure, _ cam: String?) {
        let hidden = fig.exploded || (fig.viewCams != nil && cam != nil && !fig.viewCams!.contains(cam!))
        if fig.exploded { fig.hidden = true }
        if fig.name == resolve(follow) && !fig.exploded { fig.hidden = false }   // CAMERAFOLLOW shows the figure it follows (1130:00c1, vtable +0x68)
        if hidden == fig.hidden || fig.name == resolve(follow) || fig.name == playerName || (camera == nil && fig.viewCams != nil) {
            return                                         // (no camera switched to yet: currentCamera's fallbacks are the port's)
        }
        fig.hidden = hidden
        let p = fig.aiProc.flatMap { $0.done ? nil : $0 }
        if hidden {
            stopFigure(fig)
            p?.suspended = true
        } else if let p, fig.hold == 0 {
            p.suspended = false
        }
        if let p, !p.cameras.isEmpty {                     // 1130:0549 runs the camera links after this pass (the bot AIs link themselves): the list decides
            p.suspended = cam.map { !p.cameras.contains($0) } ?? true
        }
    }

    func aiActive(_ fig: Figure) -> Bool { fig.aiProc.map { !$0.done } ?? false }

    func renameFigure(_ fig: Figure, _ new: String, _ proc: ScriptProcess) {
        let old = fig.name
        if new == old { return }
        figures = figures.renaming(old, to: new)
        fig.name = new
        if playerName == old { playerName = new }
        proc.curFig = new
        vm?.renameObject(old, to: new)
    }

    // MARK: scripted movement

    /// -> (xy, floor z) of a WAYP, else of any other named object (ASSUMPTION: a volume arrives at the centre of its box in x/y,
    /// on its lowest z), else nil.
    func arrivalPoint(_ name: String) -> (xy: V2, z: Double)? {
        let objs = data.objs.filter { $0.name.uppercased() == name }
        guard let o = objs.first(where: { $0.tag == "WAYP" }) ?? objs.first else { return nil }
        guard let p2 = o.pos2 else { return (V2(Double(o.pos[0]), Double(o.pos[1])), Double(o.pos[2])) }
        let lo = pointwiseMin(v3(o.pos), v3(p2)), hi = pointwiseMax(v3(o.pos), v3(p2))
        return ((V2(lo.x, lo.y) + V2(hi.x, hi.y)) / 2, lo.z)
    }

    /// The volume word 2 of an elevator LOADLEVEL names (FUN_10d0_4d46, 10d0.c:4336): the IMAG of that name, else the PHYS. See world.py `level_volume`.
    func levelVolume(_ name: String) -> (lo: V3, hi: V3)? {
        for tag in ["IMAG", "PHYS"] {
            if let o = data.objs.first(where: { $0.tag == tag && $0.name.uppercased() == name && $0.pos2 != nil }) {
                return (pointwiseMin(v3(o.pos), v3(o.pos2!)), pointwiseMax(v3(o.pos), v3(o.pos2!)))
            }
        }
        return nil
    }

    /// FUN_1088_2dfc after the attach (1070:0755): unless collisions are off, up to 21 tries of SetPos (FUN_10a0_1ff0, GO's floor rule: gravity
    /// on = the floor under the point + F, else z as is) and, while the hull is blocked by the PHYS (FUN_1058_1a1b), a step of 204 units in x and
    /// in y toward the destination point (x <= Dx steps +, else -). `zq` is the z the floor is looked up from; `firstDone`: the position already
    /// is the first SetPos's result. See world.py `place_after_level_change`.
    func placeAfterLevelChange(_ fig: Figure, _ p: V3, zq zq0: Double, dest: V2, firstDone: Bool = false) {
        fig.pos = p
        fig.go = nil; fig.manualControl = false
        fig.vx = 0; fig.vy = 0; fig.vz = 0; fig.step = [0, 0, 0]
        if fig.noCollide { return }
        var zq = zq0
        for i in 0..<21 {
            if fig.gravity && !(i == 0 && firstDone) {
                let floor = pointFloor(Int(fig.pos!.x), Int(fig.pos!.y), Int(zq), Int(zq))
                fig.pos!.z = (floor > Self.noFloor ? Double(floor) : zq) + Double(foot(fig))
            }
            if !hullCollides(fig) { break }
            fig.pos!.x += fig.pos!.x <= dest.x ? 204 : -204
            fig.pos!.y += fig.pos!.y <= dest.y ? 204 : -204
            zq = fig.pos!.z
        }
    }

    /// LOADLEVEL <level> [<arrival> | <volume> <destination>] (handler FUN_10d0_4d46): first destroys every missile (endMissilesForLevelChange).
    /// The elevator form looks the volume up (IMAG, then PHYS; neither: error 0x8b, the caller ends and nothing loads), and every non-player
    /// figure and every floor item whose hull / EXTENT box overlaps it, and the player (whether or not he is inside), keep their offset from the
    /// volume (x, y from its centre, z from its floor): they arrive at the destination point + that offset (1060:0df8 detach, 1070:0755 attach).
    /// Stops every sound handle but the one the first numeric argument names (FUN_1028_12d2, 10d0.c:4401: ELEVATOR.scr's `_sfx_5` hum keeps
    /// playing across the ride; the original runs it after the load and before the kill walk, the port before the walk: no script runs in
    /// between), then kills every script process but the caller's CALL chain (FUN_10b0_13fb: no exemption for the boot chain; the caller
    /// continues only if its script file is part of the new level: ScriptVM.endUnloaded), swaps in the new level's scripts and objects, places PLAYER at the arrival point
    /// (floor point + foot offset) or at his offset, then fires <LEVEL>_LOAD. See world.py `cmd_loadlevel`.
    func cmdLoadLevel(_ args: [ScriptValue], _ proc: ScriptProcess) {
        guard let vm else { return }
        endMissilesForLevelChange()
        let level = pyStr(args[0]).uppercased()
        if levelFile(level) == nil { warn("LOADLEVEL \(level): no such level"); return }
        var arrival: String?
        if args.count > 1, case .str(let s) = args[1] { arrival = s.uppercased() }
        var carried: [(fig: Figure, rel: V3)] = [], carriedItems: [(item: Item, rel: V3)] = []
        var relPlayer: V3?
        if args.count > 2, case .str = args[2], let volName = arrival {       // LOADLEVEL <level> <volume> <x>: the volume's figures and items travel at their offsets
            guard let vol = levelVolume(volName) else {
                warn("LOADLEVEL \(level) \(pyStr(args[1])) \(pyStr(args[2])): no volume \(volName) (error 0x8b): the caller ends, no level change")
                vm.finish(proc)
                return
            }
            let ref = V3(Double(Int((vol.lo.x + vol.hi.x) / 2)), Double(Int((vol.lo.y + vol.hi.y) / 2)), Double(Int(vol.lo.z)))     // the vt+0x50 point, its floor
            func touches(_ lo: [Double], _ hi: [Double]) -> Bool {      // FUN_1058_173c, inclusive
                lo[0] <= vol.hi.x && hi[0] >= vol.lo.x && lo[1] <= vol.hi.y && hi[1] >= vol.lo.y && lo[2] <= vol.hi.z && hi[2] >= vol.lo.z
            }
            for k in figures.keys {
                guard k != playerName, let f = figures[k], let p = f.pos else { continue }
                let h = queryHull(f)
                if touches([h.lo.x, h.lo.y, h.lo.z].map(Double.init), [h.hi.x, h.hi.y, h.hi.z].map(Double.init)) { carried.append((f, p - ref)) }
            }
            for it in items.values where it.owner == nil && !(it is Missile) {
                guard let p = it.pos else { continue }
                loadItemPhysics(it)
                if touches([p.x - Double(it.extent[0]), p.y - Double(it.extent[1]), p.z - Double(it.extent[2])],
                           [p.x + Double(it.extent[0]), p.y + Double(it.extent[1]), p.z + Double(it.extent[2])]) { carriedItems.append((it, p - ref)) }
            }
            if let p = player?.pos { relPlayer = p - ref }
            // 10d0:4d46 hands the third word (+700), not the volume, to 1148:15c7 as the destination (1050:0c65)
            if case .str(let s) = args[2] { arrival = s.uppercased() }
        }
        presentation.installed = [Int](repeating: 0, count: 768)     // 1148:1a76 -> 1130:147c -> 10e8:1a9e(0, 0): an all-black palette is pending until the camera's (paletteCut)
        if arrival == nil { warn("LOADLEVEL \(level): no arrival point (engine requires one); PLAYER keeps its position") }
        var keepVoice: Int?                                          // 10d0:4d46's first numeric argument (ctx+0xe2b): the voice to keep
        for a in args { if case .int(let v) = a { keepVoice = v; break } }
        for (h, _) in soundHandles where h != keepVoice { stopSound(h) }     // FUN_1028_12d2: every other voice stops; the mixer ends it (soundStops)
        vm.killLevelOwned(caller: proc, keep: keepVoice.flatMap { k in soundHandles.contains { $0.handle == k } ? k : nil })
        vm.unloadScripts()
        _ = try? vm.loadLevel(level, library: resources.library)
        vm.endUnloaded(proc)
        do { try loadObjects(level, travelling: carried.map(\.fig.name), carryItems: Set(carriedItems.map(\.item.key))) } catch { warn("LOADLEVEL \(level): \(error)"); return }
        for c in carried { figures[c.fig.name] = c.fig }
        var pos: V3?
        let t = arrival.flatMap { arrivalPoint($0) }
        if let arrival, t == nil { warn("LOADLEVEL \(level): arrival \(arrival) not found (error 0x136); PLAYER keeps its position") }
        let dest = t.map { V3($0.xy.x, $0.xy.y, $0.z) } ?? V3(0, 0, 0)         // no destination: a dummy at the origin (1148:1061)
        for c in carried { placeAfterLevelChange(c.fig, dest + c.rel, zq: (dest + c.rel).z, dest: V2(dest.x, dest.y)) }
        for c in carriedItems {                                                // 1078:07c3 -> 1070:1e9d: a plain SetPos, the velocity zeroed
            c.item.pos = dest + c.rel; c.item.vel = [0, 0, 0]; c.item.step = [0, 0, 0]
        }
        if let t, let player {
            if let relPlayer {
                let p = dest + relPlayer
                placeAfterLevelChange(player, p, zq: p.z, dest: V2(dest.x, dest.y))
            } else {
                // As GO (FUN_10a0_1ff0). Live: gravity off, ENTR_TNK's low z as is (-3584); gravity on, the floor under BTM_LDR + F (-13996 + 2312)
                // Collisions off (CRYTOTNK FALL): no floor. Live (re/out/tank_fall_live), the original left Lex far below every floor
                // there and he fell on into the acid; the port stood him on the TANKS walkway and FALL's COORDZ loop never ended.
                let snap = player.gravity && !player.noCollide
                let floor = snap ? pointFloor(Int(t.xy.x), Int(t.xy.y), Int(t.z), Int(t.z)) : Self.noFloor
                let z = !snap ? t.z - Double(modelRootZ(player)) : (floor > Self.noFloor ? Double(floor) : t.z) + Double(foot(player))
                placeAfterLevelChange(player, V3(t.xy.x, t.xy.y, z), zq: z, dest: t.xy, firstDone: true)
            }
            pos = player.pos
        }
        shownPicture = nil
        levelLoads.append((vm.tick, level, arrival, pos))
        fireEvent(level + "_LOAD")
    }

    /// A GO that places at once: SetPos (FUN_10a0_1ff0) zeroes every velocity (FUN_1070_1e9d). Live (re/out/tank_fall_live): TANKDETH's
    /// GO DROWN leaves the falling Lex with z velocity 0. See world.py `_go_snap`.
    func goSnap(_ fig: Figure, _ pos: V3) {
        fig.pos = pos
        fig.vx = 0; fig.vy = 0; fig.vz = 0
        fig.step = [0, 0, 0]
        fig.go = nil
    }

    /// The GO task's walking state (FUN_10e0_1a4c case 4) calls FUN_10a0_1f0a every update while the figure walks or runs: it turns
    /// toward the target, by the whole angle within 10 degrees and by 10 degrees (0xa00 in 8.8) otherwise. Without it a figure pushed
    /// off its line could miss the arrival circle and run on for ever (Drogg 1 after GO DCENTER RUN). See world.py `steer_go`.
    func steerGo(_ fig: Figure) {
        guard let go = fig.go, !fig.arriving, let pos = fig.pos, ["WALK", "RUN", "ATK_M8"].contains(fig.motion?.uppercased() ?? "") else { return }
        let dx = go.target.x - pos.x, dy = go.target.y - pos.y
        guard dx != 0 || dy != 0 else { return }
        let want = atan2(-dx, -dy) * Self.degPerRad                 // as cmdGo aims: the inverse of forward()
        var diff = (want - fig.heading + 180).truncatingRemainder(dividingBy: 360)
        if diff < 0 { diff += 360 }
        diff -= 180
        guard diff != 0 else { return }
        fig.heading = abs(diff) < 11 ? want : fig.heading + (diff > 0 ? 10 : -10)
    }

    func cmdGo(_ fig: Figure, _ args: [ScriptValue], _ proc: ScriptProcess) {
        fig.manualControl = false
        let nums = args.compactMap { v -> Int? in if case .int(let i) = v { return i }; return nil }
        var numeric = false
        if case .int? = args.first, nums.count >= 3 { numeric = true }
        let t: (xy: V2, z: Double, isFigure: Bool)
        if numeric {
            // FUN_10d0_33c8 numeric form: (x, y, z) = the first three numbers << 8 (COORDX units); a 4th number is the arrival radius
            // in cm (below; 0 or absent = the default); any word other than WALK / RUN is error 0x120. See world.py `cmd_go`.
            if let bad = args.compactMap({ v -> String? in if case .str(let s) = v { return s }; return nil }).first(where: { !["WALK", "RUN"].contains($0.uppercased()) }) {
                warn("GO \(bad): unknown modifier (error 0x120)"); return
            }
            t = (V2(Double(nums[0] << 8), Double(nums[1] << 8)), Double(nums[2] << 8), false)
        } else if let found = goTarget(pyStr(args[0])) { t = found }
        else { warn("GO \(pyStr(args[0])): unknown target"); return }
        let mode = args.dropFirst().map { pyStr($0).uppercased() }.first { $0 == "WALK" || $0 == "RUN" }
        // SetPos (FUN_10a0_1ff0): with gravity the origin goes to the floor under the target point (FUN_1060_0d9a -> FUN_1060_0871) + F
        // (+ the root z, kept in the pose); without gravity z is the engine's, origin + R (live: Lex at PLAYLOC reads -5754 with R -40, then -5714
        // once WAKE_UP's R 0 applies); the port's origin leaves R out
        var zt = t.isFigure ? t.z : !fig.gravity ? t.z - Double(modelRootZ(fig))
            : Double(pointFloor(Int(t.xy.x), Int(t.xy.y), Int(t.z), Int(t.z)) + foot(fig))
        if numeric && fig.gravity && zt <= Double(Self.noFloor + foot(fig)) { zt = t.z }     // ASSUMPTION: no floor under a numeric point (the 6666 park): keep z
        guard let mode, let fp = fig.pos, fig.assets.motion(mode) != nil else {
            if let mode, fig.pos != nil { warn("\(fig.type) has no \(mode) motion; snapping") }
            goSnap(fig, V3(t.xy.x, t.xy.y, zt))
            return
        }
        let d = t.xy - V2(fp.x, fp.y)
        if hypot(d.x, d.y) <= 1e-6 {
            goSnap(fig, V3(t.xy.x, t.xy.y, zt))
            return
        }
        fig.heading = atan2(-d.x, -d.y) * Self.degPerRad            // inverse of forward()
        // Arrival radius (1098:11c0): the default 0x266 = 614 units; the numeric form's 4th number N, when nonzero, is N cm
        // (N * 2048 / 100). INFERRED: the named forms never read that slot, so they always use the default.
        let radius = numeric && nums.count > 3 && nums[3] != 0 ? nums[3] * 2048 / 100 : Self.goRadius
        let go = Go(target: t.xy, z: zt, motion: mode, radius: radius)
        fig.go = go
        fig.dropDeferred()
        fig.setMotion(mode, loop: true)
        // FUN_10d0_33c8 returns the mover's handle to the script scheduler: the process continues after this walk arrives, or if
        // another GO / motion replaces it.
        proc.waitPred = { [weak fig] in fig.map { $0.go !== go } ?? true }
    }

    func cmdFace(_ fig: Figure, _ a: ScriptValue) {
        if case .int(let n) = a { fig.heading = Double(n); return }        // FACE <number> = absolute heading in degrees
        guard let t = target(pyStr(a)) else { warn("FACE \(pyStr(a)): unknown object"); return }
        let p = fig.pos.map { V2($0.x, $0.y) } ?? .zero
        let d = t.xy - p
        if hypot(d.x, d.y) > 1e-6 { fig.heading = atan2(-d.x, -d.y) * Self.degPerRad }
    }

    /// Whether a CONTINUE motion loops: its header's frame event list holds the 0xfe end marker (1088:1854), else the `isCycle` rule.
    static func motionLoops(_ assets: WorldAssets, _ name: String) -> Bool {
        guard let m = assets.motion(name) else { return false }
        return m.loops ?? isCycle(m.frames, turning: m.flags & 1 != 0)
    }

    /// True if a motion's last pose is close to its first (limb angle difference <= CYCLE_TOLERANCE), i.e. it can loop.
    static func isCycle(_ frames: [MotionFrame], turning: Bool) -> Bool {
        guard frames.count >= 2 else { return true }
        var worst = 0
        for (i, (a, b)) in zip(frames[0].limbs, frames[frames.count - 1].limbs).enumerated() {
            worst = max(worst, abs(a.x - b.x), abs(a.y - b.y), i == 0 && turning ? 0 : abs(a.z - b.z))
        }
        return worst <= cycleTolerance
    }

    /// MOTION name [CONTINUE|FREEZE|SNAP_TO|NO_SCRIPT] [start frame] (handler FUN_10d0_5e8b): plain = start now, play once and BLOCK
    /// the calling process until it finishes or the figure gets another motion; CONTINUE = start now, no wait, loops if the motion's header
    /// event list holds the 0xfe marker (1088:1854; `isCycle` when it has none); FREEZE = clears only the idle-fallback bit (10d0:5e8b):
    /// the motion plays to its end, blocking like a plain MOTION unless CONTINUE is also given, and its last pose is held with no STAND
    /// fallback (noIdle) until the next MOTION/SNAPTOPOSE. During a GO walk motions are deferred to arrival.
    func cmdMotion(_ fig: Figure, _ rawName: String, _ flags: [String], _ proc: ScriptProcess) {
        let name = rawName.uppercased()
        fig.manualControl = false
        guard let m = fig.assets.motion(name) else { warn("\(fig.type) has no motion \(name)"); return }
        let scripted = !flags.contains("NO_SCRIPT")
        if scripted && fig.motionGateRefuses(name) { return }       // 1098:12bd refused: no change, no wait
        let freeze = flags.contains("FREEZE")
        let continuing = flags.contains("CONTINUE")
        let loop = continuing && Self.motionLoops(fig.assets, name) && !Self.gestures.contains { name.hasSuffix($0) }
        let start = flags.lazy.compactMap { f -> Int? in
            let d = f.hasPrefix("-") ? f.dropFirst() : Substring(f)
            return !d.isEmpty && d.allSatisfy({ $0.isASCII && $0.isNumber }) ? Int(f) : nil
        }.first ?? 0
        let block = !continuing                                 // only CONTINUE skips the wait (10d0:6083), FREEZE alone blocks
        var tok: MotionToken? = block ? MotionToken() : nil
        if fig.go != nil {
            fig.dropDeferred()                                  // a deferred motion replaced by a later one releases its caller
            fig.afterGo = (name, loop, tok)
        } else {
            fig.go = nil
            if fig.setMotion(name, loop: loop, noIdle: freeze) {
                fig.taskName = scripted ? name : nil
                fig.unwaited = !block
                fig.idx = max(0, min(start, (fig.frames?.count ?? 1) - 1))
                tok?.id = fig.motId
            } else {
                tok = nil           // refused (DIE is current, 1098:0394 returns 0): a zero handle, so 10d0:5e8b does not wait
            }
        }
        if let tok { proc.waitPred = { [weak fig] in fig.map { tok.id != nil && ($0.motId != tok.id! || $0.finished) } ?? true } }
    }

    /// SNAPTOPOSE motion frame [FREEZE]: show that frame now, queue cleared; FREEZE holds it.
    func cmdSnapToPose(_ fig: Figure, _ args: [ScriptValue]) {
        fig.manualControl = false
        let name = pyStr(args[0]).uppercased()
        guard fig.assets.motion(name) != nil else { warn("\(fig.type) has no motion \(name)"); return }
        var frame = 0
        if args.count > 1, case .int(let f) = args[1] { frame = f }
        fig.go = nil
        fig.dropDeferred()
        // 10d0:76xx: 0789(fig, 0, 0) (which returns early on an unfinished DIE), then 1098:1421 -> 06e0 -> 0394, which refuses while DIE is
        // current: no exception for SNAPTOPOSE either (INFERRED: the pose-at-frame step that follows the refusal is not ported)
        if fig.setMotion(name, loop: false, freeze: args.dropFirst(2).contains { pyStr($0).uppercased() == "FREEZE" }) {
            fig.idx = max(0, min(frame, (fig.frames?.count ?? 1) - 1))
        }
    }

    // MARK: automatic cameras

    public var currentCamera: String? { camera ?? defaultCamera ?? data.cameraOrder.first }

    func followedPos() -> V3? { figures[resolve(follow)]?.pos }

    func setCamera(_ cam: String, _ reason: String) {
        let old = camera ?? defaultCamera
        if cam != old { cameraChanges.append((tick, old, cam, reason)) }
        cameraEvents(cam)
        if cam != camera { applyCameraLinks(cam) }           // 1130:0549, after the events: a process their blocks started and linked is included. the first switch of a level always counts: [63ce] is 0 until then (1130:0048)
        if cam != camera { shownPicture = nil }              // a real switch replaces the SHOW picture
        camera = cam                                         // [63ce] is assigned after the events (1130:065d): their blocks still see the old camera
    }

    /// LINKMETOCAMERAS (10d0:4c72): registers the running process with each named camera of the level (10c0:547d, list DS:2f1d). An unknown
    /// name is error 0x1e and more than 10 cameras error 0xe1 (10c0:533a); neither stops the statement. Linking alone pauses nothing, not even
    /// when the current camera is not listed: only the next camera switch looks at the list (10c0:5688).
    func linkToCameras(_ proc: ScriptProcess, _ args: [ScriptValue]) {
        for arg in args.prefix(10) {
            let c = pyStr(arg).uppercased()
            if data.cameras[c] == nil {
                warn("LINKMETOCAMERAS \(c): unknown camera (error 0x1e)")
            } else if proc.cameras.count >= 10 {
                warn("LINKMETOCAMERAS \(c): \(proc.block.name) already has 10 cameras (error 0xe1)")
            } else {
                proc.cameras.append(c)
            }
        }
    }

    /// 10c0:5688 on a camera switch: flag bit 0 (+0xe) of every linked process is set unless `cam` is in its list (10c0:53fe) and cleared if it
    /// is. That bit is `suspended`, shared with SUSPENDPROCESS / RESUMEPROCESS, AI OFF / ON and the show / hide pass, so a switch overrides
    /// them for a linked process. The kernel skips a flagged task (1230:0259). A WAIT or CALL child goes on while it is paused and a timeline's
    /// clock too (10c8:03e1 compares [8330] with origin + stamp): once resumed it runs every line that came due in one slice.
    func applyCameraLinks(_ cam: String?) {
        for p in vm?.processes ?? [] where !p.cameras.isEmpty {
            p.suspended = cam.map { !p.cameras.contains($0) } ?? true
        }
    }

    /// 1130:0307-044f, while the game runs ([50b8]; clear only in the new-game and restore loads, which the ports do not run through
    /// here): a different room (the name's first 3 characters, [63e5] vs [63ed]) runs <new room>_LOAD then <old room>_UNLOAD, a different
    /// camera ([63e1] vs [63e9]) <new cam>_LOAD then <old cam>_UNLOAD. Each block's first slice runs at once with CURFIG = the player
    /// (1120:0000 with run flag 1, no item). The names are copied only afterwards (1130:0459). No shipped script has an _UNLOAD block.
    /// The level's initial camera counts as loaded when first used.
    func cameraEvents(_ cam: String) {
        let room = String(cam.prefix(3)), oldCam = loadedCam, oldRoom = loadedRoom
        if cam == oldCam && room == oldRoom { return }
        switchingTo = cam
        if room != oldRoom {
            fireCameraEvent(room + "_LOAD")
            if let oldRoom, !oldRoom.isEmpty { fireCameraEvent(oldRoom + "_UNLOAD") }
        }
        if cam != oldCam {
            fireCameraEvent(cam + "_LOAD")
            if let oldCam, !oldCam.isEmpty { fireCameraEvent(oldCam + "_UNLOAD") }
        }
        loadedCam = cam; loadedRoom = room; switchingTo = nil
        cameraSwitched()                                     // 1130:0114 step e, after the events: the ambient loops restart next frame
    }

    func fireCameraEvent(_ block: String) {
        guard let vm, vm.blocks[block] != nil else { return }
        events.append((vm.tick, block))
        vm.spawn(block, ctx: spawnContext(player))
    }

    /// Camera acceptance test (FUN_1110_1a95) for the followed object's position P: d = approxLength(P - eye) (FUN_1210_0f9b, not the Euclidean length) must lie in [NEARMARK, FARMARK];
    /// rel = bearing(eye -> P) - camera heading (atan2 in the xy plane, degrees, mod 360) must be < half_fov - fovr2 or > 360 -
    /// half_fov + fovr1. -> (accepted, d)
    static func accepts(_ cam: Camera, _ p: V3) -> (Bool, Double) {
        let half = Double(cam.extra[0]), far = Double(cam.extra[2]), near = Double(cam.extra[3])
        let fovr1 = Double(cam.extra[4]), fovr2 = Double(cam.extra[5])
        let v = p - cam.pos
        let d = Double(approxLength(Int(v.x), Int(v.y), Int(v.z)))
        if !(near <= d && d <= far) { return (false, d) }
        let fwd = cam.rows[1]
        let heading = atan2(fwd.y, fwd.x) * degPerRad
        let bearing = atan2(v.y, v.x) * degPerRad
        let rel = (bearing - heading + 1080).truncatingRemainder(dividingBy: 360)
        return (rel < half - fovr2 || rel > 360 - half + fovr1, d)
    }

    /// One frame of the camera manager: see the header.
    func updateCamera() {
        let pos = followedPos()
        if let cam = forcedCamera, pos != nil {
            // a trigger forced a camera: switch to it unless it is current, skipping acceptance and debounce; while the script
            // holds the camera the request is dropped (CAMERA UNLOCK resets the pending camera to the current one)
            forcedCamera = nil; candidate = nil
            if autoCamera && scriptAuto && cam != camera ?? defaultCamera {
                selected = true
                setCamera(cam, "trigger forces \(cam)")
            }
            return
        }
        guard autoCamera, scriptAuto, let p = pos else { return }
        let cur = camera ?? defaultCamera                    // a level load leaves no camera ([63ce] 0, 1130:0048), so its first frame takes the nearest accepting one; defaultCamera is the World(camera:) argument
        if let cur, let cam = data.cameras[cur], Self.accepts(cam, p).0 {
            candidate = nil
            cameraEvents(cur)
            return
        }
        var best: (name: String, d: Double)?
        for name in data.cameraOrder where !disabled.contains(name) && name != cur {
            let (ok, d) = Self.accepts(data.cameras[name]!, p)
            if ok && (best == nil || d < best!.d) { best = (name, d) }
        }
        guard let best else { candidate = nil; return }
        if best.name == candidate || !selected {
            selected = true; candidate = nil
            setCamera(best.name, "\(cur ?? "None") rejects \(follow); \(best.name) nearest accepting (d=\(String(format: "%.0f", best.d)))")
        } else {
            candidate = best.name
        }
    }

    // MARK: time

    /// The credits page is open (the roll runs; it does not pause or hold the world).
    var creditsRolling: Bool { if let o = options, !o.closed, o.screen == "credits" { return true }; return false }

    /// CREDITSSTATE [9ce5]: 0 none (or the page closed), 1 scrolling, 2 done.
    var creditsState: Int { creditsRolling ? options?.creditsState ?? 0 : 0 }

    /// Once per tick: the script monitor's and the options dialog's pointer (FUN_1270_02ef); a release that activates an option control takes
    /// effect here.
    func stepPointers() {
        monitor?.update()
        if let options { for action in options.update() { recordOptionAction(action) } }
    }

    /// Advance every placed figure by one VM tick, then update the automatic camera. Stands still while the options dialog is open.
    public func step() {
        frames += 1
        stepPointers()                                       // the pointers' press animations run on, also while the options dialog pauses the game
        if paused { return }
        stepShow()                                           // the flic clock and ADDKEY run while FREEZE has stopped the world
        if show.frozen { return }
        stepPresentation()
        applyPlayerInput()
        boxes = nil
        boxes = physBoxes()
        moveMissiles()                                       // 1110:08bf updates the item list (missiles) before the figures
        moveFreeItems()                                      // ... and its other items (thrown ones)
        let cam = currentCamera
        for fig in figures.values {
            if figures[fig.name] !== fig { continue }        // a trigger's LOADLEVEL dropped it with its level this frame
            updateHidden(fig, cam)
            startEnabledAI(fig)                              // FUN_1088_3371, before this figure's update
            fig.heldPose = nil                               // this update samples the current motion's pose (World.posed)
            updateConfront(fig)
            guard fig.pos != nil, let frames = fig.frames, !frames.isEmpty else { continue }   // frames nil: figure type without STAND
            if fig.hidden {
                // FUN_1088_39ef returns at once for a hidden figure (flag 0x04, +0xf6 clear): neither animated, moved
                // nor pushed, and excluded from other figures' PERSONAL_RADIUS pushes (pushTarget already checks
                // other.hidden). NOT PORTED: the HIDE/UNHIDE block event (FUN_1128_0569; no script in this game defines
                // one) and stopping the figure's ambient sound (FUN_1058_0c81 on +0x135; see NOTES "STOPMOTION and
                // hidden figures").
                continue
            }
            fig.prevPos = fig.pos; fig.lastGood = fig.pos      // +0xba / +0xe2 at the frame start
            // FUN_1088_1854: frame = (clock << 8 - start) / (MY_SPEED x frame time); the clock runs at 60 Hz
            if fig.rootStart { applyFirstRoot(fig) }
            steerGo(fig)
            fig.phase += Self.clockPerTick
            while fig.phase >= motionDuration(fig) {
                fig.phase -= motionDuration(fig)
                advance(fig)
            }
            if let c = fig.carrier, items[c] == nil { fig.carrier = nil }       // its missile is gone (e.g. a level change)
            if fig.carrier == nil && fig.limbHolder == nil {
                settle(fig)                               // gravity, then the one mover call: root motion + velocity step
            } else {
                // FUN_1088_39ef does nothing while attached (+0x2c): no velocity move, gravity, grounding or push; the motion still
                // plays, but its root travel is dropped (the missile or the holder's limb places the figure)
                fig.rootDelta = V2(0, 0); fig.rootMoved = false; fig.step = [0, 0, 0]; fig.arriving = false
            }
            updateHit(fig)
            autoTurn(fig)
            motionEvents(fig)
            if let r = fig.recoilId, fig.motId != r || fig.finished {
                // ASSUMPTION: ~3 (_ATK_STATUS_RECOIL = 1) returns to _ATK_STATUS_OK when the recoil motion ends or is replaced; the
                // clearing site is not recovered, but NURSEBOT_AI idles while ~3 != 0, so without it a hit nurse never acts again
                fig.recoilId = nil
                if let vm, case .int(1) = vm.objectRecord(objectKey(fig.name))[3] {
                    var rec = vm.objectRecord(objectKey(fig.name))
                    rec[3] = .int(0)
                    vm.setObject(objectKey(fig.name), rec)
                }
            }
            if fig.idleRequest && hitPoints(fig) > 0 {
                fig.idleRequest = false                      // 1088:4167: no motion and no task left, at the end of the figure's update
                fig.heldPose = poseState(fig)
                let z = fig.pos!.z
                fig.setMotion(fig.combat ? "ATK_STAND" : "STAND", loop: true, engine: true)
                fig.pos!.z = z                               // the stopped pose's root z is the idle's own: nothing to commit
            }
            if fig.finished && !fig.frozen && !fig.noIdle && fig.go == nil && fig.motion != "DIE"
                && hitPoints(fig) > 0 && fig.assets.motion(idleMotion(fig)) != nil {
                // 1088:4155: at the end of its update a living figure, the player too, with no motion task left requests its idle
                // (FUN_1098_0745), lower case in the original. HALMECHO's TURN_WHILE_FIRING loops on ISMYMOTION(FIRE_GUN) until this ends its FIRE_GUN.
                fig.heldPose = poseState(fig)
                fig.setMotion(idleMotion(fig), loop: true, engine: true)
            }
            if fig.finished, !fig.noIdle, let m = fig.motion, Self.engineOneshots.contains(m), vm == nil || hitPoints(fig) > 0 {      // 1088:508d: a dead figure never idles
                // ASSUMPTION: an engine-requested landing / whoah motion returns to STAND, or to the walk of a running GO
                fig.setMotion(fig.go?.motion ?? "STAND", loop: true)
            }
            updateTriggers(fig)
        }
        stepTextures()                                       // ANIMATE: every animated texture with a mode steps (ASSUMPTION, WorldMechanics.swift)
        placeLimbHeld()                                      // GRABCRITTER: figures held by a limb follow its current pose (ASSUMPTION, WorldMechanics.swift)
        tickMissiles()                                       // the scheduler's missile tasks (1230:0259), after the world update
        tickFlatObjects()
        tickFragments()
        boxes = nil
        updateCamera()
        refreshSoundVolumes()
        updateAmbients()                                     // 1130:0e6b
    }

    /// A motion's first update moves the figure by frame 0's whole root x, y. FUN_1098_0000 clears the root base +0xd1..+0xd9 when a motion
    /// ends, FUN_1088_0581 moves by root minus base, and FUN_1098_0394 copies frame 0's root into the blend's start pose, so the blend
    /// (FUN_1088_0d63) holds the root at frame 0. Live, DOSBox-X: WALK_BACK (7, 241) moved Lex (7, 241) at its first update.
    func applyFirstRoot(_ fig: Figure) {
        fig.rootStart = false
        if fig.frozen || fig.arriving { return }
        guard let f0 = fig.frames?.first else { return }
        if f0.pos.x != 0 || f0.pos.y != 0 {
            fig.rootDelta += rootStep(fig, f0.pos.x, f0.pos.y); fig.rootMoved = true
        }
    }

    /// The world move of a root change (x, y) spread over `updates` engine updates. FUN_1088_0581 multiplies each update's change by the
    /// figure's matrix in 8.8 and shifts each axis down (FUN_1210_15b4), so every update rounds toward -x, -y. Live, DOSBox-X at the GOG
    /// settings: this reproduces all 88 MANTLE_6 and 175 of 177 CLIMB_UP moves exactly (the other two are the loop wrap, which does not
    /// move). The drift grows with the update count, which is not fixed in the original: about 1 clock tick per update in the ladder
    /// shaft, 2 in a busier room, 3.7 at 8000 cycles. ASSUMPTION: one update per 30 Hz tick.
    func rootStep(_ fig: Figure, _ x: Int, _ y: Int, _ updates: Int = 1) -> V2 {
        let m = orientation(fig)
        var out = V2(0, 0)
        for i in 0..<updates {
            let dx = floorDiv(x * (i + 1), updates) - floorDiv(x * i, updates), dy = floorDiv(y * (i + 1), updates) - floorDiv(y * i, updates)
            out += V2(Double((m[0][0] * dx + m[1][0] * dy) >> 8), Double((m[0][1] * dx + m[1][1] * dy) >> 8))
        }
        return out
    }

    /// One motion frame. Its root motion is not moved here: it accumulates in fig.rootDelta and World.frameMove performs the frame's
    /// single mover call (FUN_1088_39ef: root motion and velocity step in one move, one collision response).
    func advance(_ fig: Figure) {
        if fig.frozen || fig.arriving { return }
        guard let frames = fig.frames else { return }
        var nxt = fig.idx + 1
        if nxt >= frames.count {
            if !fig.loop && (fig.go == nil || Self.engineOneshots.contains(fig.motion ?? "")) {
                fig.finished = true
                return                                          // play once: hold the last frame
            }
            nxt = 0
            fig.hitDone = false                                 // a new cycle may hit again
            fig.bakeTurn()                                      // FUN_1088_1854 -> FUN_10a0_1c83 at a turning motion's wrap
            if fig.rises, let p = fig.pos, let last = frames.last {
                fig.pos = V3(p.x, p.y, p.z + Double(last.pos.z))     // 1088:1286: a flag-2 motion adds R (C+0xa6) to the root limb's z at the wrap
            }
            fig.idx = 0
        }
        let d = motionDuration(fig)
        let updates = max(1, (((fig.idx + 1) * d) >> 9) - ((fig.idx * d) >> 9))     // 30 Hz ticks this frame lasts: one engine update per tick, see rootStep
        let moving = fig.go != nil || (aiActive(fig) && fig.pos != nil)
            || (fig === player && fig.manualControl && Self.manualMoves.contains(fig.motion ?? ""))
        if moving, let fp = fig.pos {
            let rp = frames.map(\.pos)
            let prev = nxt != 0 ? rp[fig.idx] : SIMD3<Int>(0, 0, 0)       // a cycle restarts at displacement 0
            let delta = rootStep(fig, rp[nxt].x - prev.x, rp[nxt].y - prev.y, updates)
            // without a GO target (AI-driven figure) the motion's root travel just moves it (ASSUMPTION)
            if let go = fig.go {
                let rem = go.target - (V2(fp.x, fp.y) + fig.rootDelta)
                if hypot(rem.x, rem.y) < Double(go.radius) {                // 10e0:1a4c: length2d(target - pos) < radius ends the GO
                    fig.rootMoved = true
                    fig.arriving = true     // frameMove ends the GO (no snap) and starts the after-GO motion once the move completes
                } else {
                    fig.rootDelta += delta; fig.rootMoved = true
                }
            } else {
                fig.rootDelta += delta; fig.rootMoved = true
            }
        } else if nxt != 0 || fig.turning {
            // every motion frame moves the figure by the change of its root x,y (FUN_1088_0581); a turning motion's wrap re-bases
            // the root at 0 (FUN_1088_1854), other restarting loops add none (ASSUMPTION)
            let rp = frames.map(\.pos)
            let prev = nxt != 0 ? rp[fig.idx] : SIMD3<Int>(0, 0, 0)
            fig.rootDelta += rootStep(fig, rp[nxt].x - prev.x, rp[nxt].y - prev.y, updates); fig.rootMoved = true
        }
        fig.idx = nxt
    }
}
