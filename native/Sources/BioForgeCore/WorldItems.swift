// Items on the floor and in the hands, and the Enter key (pick up / put down). Port of re/interp/items.py (the oracle, which also holds
// the decoded rules with their function citations: FUN_1088_5729, FUN_1138_0000 / 0453 / 040c / 088d / 05ff / 099b, FUN_1088_5923 /
// 5b43 / 5c19, FUN_1038_035b); everything the executable does not tell us is an ASSUMPTION, as there.
//
// Enter (scan 0x1c) picks by what the hands hold and the nearest floor item within 0x900 units and 60 degrees in front (0x1000 and any
// direction near a corpse); the pick-up / put-down motion starts through the script block `<TYPE>_<MOTION>` if one exists. The item
// moves at the motion's event byte (0xef grab, 0xf3 / 0xf4 / 0xee drop; frame list in the motion header: u16 count at +28, list at +32),
// then `<holder>_<item>_TAKE` / `_DROP` runs. A held item is a child limb of the hand limb (end position + ON_<HAND> offset, matrix
// rotated by its angles); a dropped one lands at the hand's x, y with its lowest vertex on the floor, rotated by ON_GROUND.
import Foundation

/// Per-world item state kept out of World's stored properties: Enter targets, motion-event bookkeeping and loaded files.
final class ItemState {
    var pickTargets: [String: String] = [:]                    // figure name -> item key stored by Enter for the grab event (+0x199)
    var events: [String: [String: [(after: Int, code: Int)]]] = [:]   // figure type -> MOTION -> events
    var eventLists: [String: [String: [UInt8]]] = [:]          // figure type -> MOTION -> the raw frame event list (eventWalk)
    var cueSeen: [String: (id: Int, pos: Int, last: Int)] = [:]   // figure name -> (motion id, list position, frame) of the frame event walk; not saved
    var meshes: [String: EORMesh?] = [:]
}

enum ItemRules {
    static let pickupReach = 0x900, pickupCone = 60.0
    static let lootNear = 0x800, lootReach = 0x1000, lootCone = 1000.0
    static let grabReach = 0x1000, grabRetry = (reach: 0xb00, cone: 180.0)
    static let evGrab = 0xef, evDropAny = 0xee, evDropRight = 0xf3, evDropLeft = 0xf4, evFire = 0xf0
    static let eventMin = 0xe0
    static let hands = ["LTHAND", "RTHAND"]
    static let itemMotions: Set<String> = ["PICK_UP_LTHAND", "PICK_UP_RTHAND", "PUT_DOWN_LTHAND", "PUT_DOWN_RTHAND"]

    /// C integer division (truncates toward zero; Swift's `/` does the same).
    static func cDiv(_ a: Int, _ b: Int) -> Int { a / b }
    /// FUN_1138_05ff: a script length in cm as game units, ((cm * 80) / 10 << 8) / 100 in long arithmetic.
    static func attachUnits(_ cm: Int) -> Int { cDiv(cDiv(cm * 80, 10) * 256, 100) }

    /// `(180I,90J,0K) 0LENGTH (0X,0Y,0Z)` tokens -> ["I": 180, ...]; a bare number is I, J or K by its position (`(90I,0,0)`).
    static func parseNumbers(_ vals: [String]) -> [String: Int] {
        var out: [String: Int] = [:]
        let plain = ["I", "J", "K"]
        for (index, v) in vals.enumerated() {
            let u = v.uppercased()
            var digits = "", i = u.startIndex
            if i < u.endIndex, u[i] == "-" { digits.append("-"); i = u.index(after: i) }
            let numStart = i
            while i < u.endIndex, u[i].isASCII, u[i].isNumber { digits.append(u[i]); i = u.index(after: i) }
            let suffix = String(u[i...])
            guard i > numStart, let n = Int(digits), suffix.allSatisfy({ $0.isASCII && $0.isUppercase }), !suffix.isEmpty || index < 3 else { continue }
            out[suffix.isEmpty ? plain[index] : suffix] = n
        }
        return out
    }

    /// Rotate about a local axis (0 = x, 1 = y, 2 = z) by `a` units (256 per turn, not necessarily whole): salsa._rot.
    static func rot(_ m: Mat3, _ a: Double, axis: Int) -> Mat3 {
        if a == 0 { return m }
        let t = a * 2 * Double.pi / 256, c = cos(t), s = sin(t) * (axis == 1 ? -1 : 1)
        let (i, j) = axis == 0 ? (1, 2) : axis == 1 ? (0, 2) : (0, 1)
        var out = m
        out.r[i] = c * m.r[i] + s * m.r[j]
        out.r[j] = c * m.r[j] - s * m.r[i]
        return out
    }
}

extension World {
    // MARK: script properties of an item type (`< NAME = ... >` tables of its ITEMS.scr block)

    func itemProp(_ type: String, _ name: String) -> [String]? {
        guard let block = vm?.blocks[type] else { return nil }
        for t in block.tables where t.name?.uppercased() == name { return t.values.map(pyStr) }
        return nil
    }

    /// FUN_1138_0453 / 088d: the item's `HANDEDNESS`, default lthand (DGROUP 6446).
    func itemHand(_ item: Item) -> String { itemProp(item.type, "HANDEDNESS")?.first.map { $0.uppercased() } ?? "LTHAND" }

    func itemMesh(_ type: String) -> EORMesh? {
        if let m = itemState.meshes[type] { return m }
        let m = game.resolve("ITEMS/\(type).IFF").flatMap { _ in (try? game.read("ITEMS/\(type).IFF")).flatMap { try? EORMesh(data: $0) } }
        itemState.meshes[type] = .some(m)
        return m
    }

    // MARK: floor items

    /// A level change keeps the old level's items with that level (FUN_1148_14a3 -> 1404): the player, and every object it holds
    /// (recursively, FUN_1088_2da1 -> FUN_1070_06ba -> FUN_1060_0df8), is detached into the carry list first, then the level's other
    /// objects are written to its GAMEDAT IFF (FUN_1148_1232) and read back from there on a return (FUN_1148_1386). Here the items that
    /// stay are kept in `levelItems[level]` (in list order, each with its script locals); items held by the player or by a `travelling`
    /// figure (an elevator's volume carries them, FUN_1060_0df8 again) stay in World.items. Missiles are dropped, as before (ASSUMPTION:
    /// a level change ends a flying shot).
    func stashLevelItems(_ travelling: [String] = [], carryItems: Set<String> = []) {
        if level.isEmpty { return }
        let keep = Set([playerName ?? "", "PLAYER"] + travelling.map { $0.uppercased() })
        var stay: [(item: Item, locals: [ScriptValue])] = []
        var kept = OrderedMap<Item>()
        for key in items.keys {
            guard let item = items[key] else { continue }
            if (item.owner.map { keep.contains($0.uppercased()) } ?? false) || carryItems.contains(key) {
                kept[key] = item
            } else {
                if let vm {
                    stay.append((item, vm.objectRecord(key)))
                    vm.removeObject(key)
                } else {
                    stay.append((item, data.recordLocals[key] ?? Array(repeating: .int(0), count: 10)))
                }
            }
        }
        items = kept
        levelItems[level] = stay
    }

    /// The level's items: those kept when the player last left it (`levelItems`, stashLevelItems), else its ITEM records with no holder
    /// (floor items) or held by one of its FIGR figures (carried by the player: Resume.swift). A kept item gets a fresh key if an item
    /// that travelled took its name meanwhile, and its script locals come back with it.
    func loadFloorItems() {
        if let kept = levelItems.removeValue(forKey: level) {
            for (item, locals) in kept {
                addItem(item)
                if let vm { vm.setObject(item.key, locals) } else { data.recordLocals[item.key] = locals }
            }
            return
        }
        for o in data.objs where o.tag == "ITEM" && o.raw.count == 191 {
            guard let r = try? ObjRec(tag: "ITEM", raw: o.raw) else { continue }
            let name = (r.inst.isEmpty ? r.name : r.inst).uppercased()
            let holder = r.holder > 0 && r.holder <= data.objs.count ? data.objs[r.holder - 1] : nil
            if r.holder != 0 && holder?.tag != "FIGR" { continue }       // the player's (Resume.swift), or a holder that is not a figure
            var owner: String?
            if let holder {
                let inst = holder.raw.cString(33, 58)
                owner = (inst.isEmpty ? holder.name : inst).uppercased()
            }
            let item = Item(name: name, type: r.name.uppercased(), owner: owner)
            if owner != nil {
                item.slot = r.hand.isEmpty ? "INVENTORY" : r.hand.uppercased()
            } else {
                item.pos = v3(r.pos)
                let m = r.matrix.map { V3(Double($0[0]) / 256, Double($0[1]) / 256, Double($0[2]) / 256) }
                item.matrix = Mat3(r: m)
            }
            item.hidden = r.flags & ObjRec.flagHidden != 0
            addItem(item)
            data.recordLocals[item.key] = (0..<10).map { .int((try? o.raw.s32(106 + 4 * $0)) ?? 0) }   // the script locals ~0..~9, as a FIGR's: MEDICAID's 5 charges, a battery's energy
        }
    }

    // MARK: the item list (DS:1d0d count / 1d15 pointers; append 1050:10bf, remove 1050:0ff4)

    /// Append an item to the list. The engine never makes instance names unique (CREATEITEM names the item after its type, so two ABAT_500
    /// coexist), so World.items is keyed separately: `item.key` is the name when it is free, else `NAME#2`, `NAME#3`... CURITEM, the
    /// object locals, pick targets and the monitor's inventory entries hold the key; script block names and texts use `name` / `type`.
    @discardableResult func addItem(_ item: Item) -> Item {
        var key = item.name, n = 2
        while items.contains(key) { key = "\(item.name)#\(n)"; n += 1 }
        item.key = key
        items[key] = item
        return item
    }

    /// INDIVIDUALIZE CURITEM (10d0:3e87 -> vtable +0x6c) overwrites only the instance name (+0xf7): the item keeps its list position and
    /// its locals. The port re-keys it: the ordered map keeps the position; the object locals, every process's CURITEM, the pending
    /// pick-up target and the monitor's inventory entries follow the new key.
    func renameItem(_ item: Item, _ name: String) {
        let old = item.key
        item.name = name
        var key = name, n = 2
        while let other = items[key], other !== item { key = "\(name)#\(n)"; n += 1 }
        if key == old { return }
        item.key = key
        items = items.renaming(old, to: key)
        if let vm {
            vm.renameObject(old, to: key)
            for p in vm.allProcesses where p.curItem == old { p.curItem = key }
        }
        for (fig, target) in itemState.pickTargets where target == old { itemState.pickTargets[fig] = key }
        monitor?.renameItemKey(old, to: key)
    }

    /// The generic object argument by name (10c0:16a8 -> 1050:0f34): after the figures, the first item in list order whose TYPE (+2,
    /// exact) equals the name.
    func itemByType(_ name: String) -> Item? {
        let n = name.uppercased()
        return items.values.first { $0.type == n }
    }

    /// SETCURRENTITEM's search (10c0:3fd9; only the first argument counts): RTHAND / LTHAND -> the first item CURFIG holds in that hand
    /// (FUN_1088_5669; needs CURFIG), else the whole list with no holder test (missiles included): a candidate is an item whose type or
    /// instance name equals the argument; the nearest to the player (exact 2D distance, FUN_10a0_1e61, between the player's +0xb and the
    /// item's +0xb = `itemEnginePos`; a never-placed item's +0xb is still zero) wins, the first on ties.
    func findItem(_ fig: Figure?, _ argIn: String) -> Item? {
        let arg = argIn.uppercased()
        if ItemRules.hands.contains(arg) { return fig.flatMap { heldItem($0, arg) } }
        let pp = player?.pos
        var best: Item?, bestD = 0
        for item in items.values where arg == item.type || arg == item.name {
            let pos = itemEnginePos(item) ?? .zero
            let d = pp.map { Int(hypot(pos.x - $0.x, pos.y - $0.y)) } ?? 0
            if best == nil || d < bestD { best = item; bestD = d }
        }
        return best
    }

    /// SETCURRENTITEM: CURITEM := the found item (1) or left unchanged (0).
    func setCurrentItem(_ proc: ScriptProcess, _ fig: Figure?, _ arg: String) -> Int {
        guard let item = findItem(fig, arg) else { return 0 }
        proc.curItem = item.key
        return 1
    }

    /// ISCARRYING <hand> <type> (10d8:2845; both words and CURFIG needed). INVENTORY / ANYWHERE run SETCURRENTITEM's search with the second
    /// word (CURITEM is restored): the found item's holder must be CURFIG, and for INVENTORY it must have no limb (+0x30 null = slot
    /// INVENTORY). Any other word is a hand: FUN_1088_5669(CURFIG, hand, type) = an item held in that hand whose TYPE equals the second word.
    func isCarryingItem(_ fig: Figure?, _ handIn: String, _ arg: String?) -> Bool {
        guard let fig, let arg else { return false }
        let hand = handIn.uppercased()
        if hand == "INVENTORY" || hand == "ANYWHERE" {
            guard let item = findItem(fig, arg) else { return false }
            return item.owner == fig.name && (hand == "ANYWHERE" || item.slot == "INVENTORY")
        }
        return items.values.contains { $0.owner == fig.name && $0.slot == hand && $0.type == arg.uppercased() }
    }

    /// The holder type's `MY_HAND` property (FUN_1138_036e / 088d; FIGURES.scr NURSEBOT: UP_ARM), upper case, or nil.
    func myHand(_ fig: Figure) -> String? {
        for block in [fig.name.uppercased(), fig.type.uppercased()] {
            if let v = resources.figureProps[block]?["MY_HAND"]?.first { return pyStr(v).uppercased() }
        }
        return nil
    }

    /// FUN_1138_088d: the hand string an attached item gets = the item's HANDEDNESS when the holder has a limb of that name (FUN_1040_17d6),
    /// else the holder type's MY_HAND; a holder with neither keeps the HANDEDNESS (no skeleton to check).
    func attachHand(_ fig: Figure, _ item: Item) -> String {
        let hand = itemHand(item)
        let limbs = fig.assets.assets.skeleton.limbs.map { $0.name.uppercased() }
        if limbs.isEmpty || limbs.contains(hand) { return hand }
        return myHand(fig) ?? hand
    }

    /// FUN_1138_036e: the first item held in lthand, rthand or MY_HAND.
    func heldAny(_ fig: Figure) -> Item? {
        for hand in ItemRules.hands + [myHand(fig)].compactMap({ $0 }) { if let i = heldItem(fig, hand) { return i } }
        return nil
    }

    func heldItem(_ fig: Figure, _ hand: String) -> Item? { items.values.first { $0.owner == fig.name && $0.slot == hand } }
    func floorItems() -> [Item] { items.values.filter { $0.owner == nil && $0.pos != nil && !($0 is Missile) } }

    /// FUN_1138_1274: put a held item in its holder's inventory.
    @discardableResult func stowItem(_ fig: Figure, _ item: Item) -> Bool {
        guard item.owner == fig.name, let slot = item.slot, ItemRules.hands.contains(slot) else { return false }
        item.slot = "INVENTORY"
        item.pos = nil
        return true
    }

    /// Script and PIMM item placement. `CARRY` uses the item's declared hand and
    /// leaves it where it is when that hand is occupied.
    @discardableResult func placeItem(_ fig: Figure?, _ item: Item, _ slotIn: String, where place: [ScriptValue] = []) -> Bool {
        let slot = slotIn.uppercased()
        if slot == "CARRY" {
            guard let fig else { return false }
            let hand = attachHand(fig, item)
            guard heldItem(fig, hand) == nil else { return false }
            item.owner = fig.name
            item.slot = hand
            item.pos = nil
            return true
        }
        if slot == "GROUND" {
            guard let fig else { return false }
            dropItem(fig, item)
            return true
        }
        if slot == "COORDS" || slot == "WAYPT" {                          // 10d0:5510-5640: off its holder (FUN_1138_099b), then to x, y, z << 8 or the object's centre
            let pos: V3
            if slot == "COORDS" {
                pos = V3(Double(num(place[0]) << 8), Double(num(place[1]) << 8), Double(num(place[2]) << 8))
            } else {
                guard let a = arrivalPoint(pyStr(place[0]).uppercased()) else { return false }
                pos = V3(a.xy.x, a.xy.y, a.z)
            }
            item.owner = nil; item.slot = nil
            item.pos = pos
            item.matrix = groundMatrix(item)
            return true
        }
        item.owner = fig?.name ?? item.owner
        item.slot = slot
        if ItemRules.hands.contains(slot) || slot == "INVENTORY" || fig?.assets.assets.skeleton.limbs.contains(where: { $0.name.uppercased() == slot }) == true {
            item.pos = nil          // an item attached to any limb (PLACEITEM RFINGER2) takes its pose from the holder, not a level position
        }
        return true
    }

    /// FUN_1138_0000: the nearest floor item in front of the figure, or nil.
    func pickupCandidate(_ fig: Figure, reach reachIn: Int = ItemRules.pickupReach, cone coneIn: Double = ItemRules.pickupCone) -> Item? {
        var reach = reachIn, cone = coneIn
        guard let p = fig.pos else { return nil }
        for other in figures.values {
            guard let q = other.pos, other !== fig, !other.hidden, let vm, let rec = vm.objects[objectKey(other.name)], rec.count > 5,
                  case .int(let hp) = rec[0], case .int(let maxHP) = rec[5] else { continue }
            // ASSUMPTION: a figure is a corpse when its hit points are <= 0 although its maximum (~5) is set; an unset record is all zero
            if hp <= 0 && 0 < maxHP && Int(hypot(q.x - p.x, q.y - p.y)) < ItemRules.lootNear {
                reach = ItemRules.lootReach; cone = ItemRules.lootCone
                break
            }
        }
        var best: Item?, bestQ = reach >> 8
        for item in floorItems() {
            let ip = item.pos!
            let d = Int(hypot(ip.x - p.x, ip.y - p.y))
            if d < reach && abs(relAngle(fig, ip)) < cone && (bestQ << 8) > d { best = item; bestQ = d >> 8 }
        }
        return best
    }

    // MARK: Enter

    /// Vtable +0x7c: the script block `<TYPE>_<MOTION>` if there is one (it decides), else the motion; refused while it is current.
    @discardableResult func startItemMotion(_ fig: Figure, _ name: String) -> Bool {
        let blk = "\(fig.type)_\(name)"
        if let vm, vm.blocks[blk] != nil { return spawnFor(fig, blk) }
        if fig.motion == name && !fig.finished { return false }
        return fig.setMotion(name, loop: false)
    }

    /// FUN_1088_5729: pick up or put down, by what the hands hold and what lies in front.
    @discardableResult func playerPickup(_ fig: Figure) -> Bool {
        let left = heldItem(fig, "LTHAND"), right = heldItem(fig, "RTHAND")
        let cand = pickupCandidate(fig)
        if left != nil {
            if right == nil, let cand, itemHand(cand) == "RTHAND" { return startItemMotion(fig, "PICK_UP_RTHAND") }
            return startItemMotion(fig, "PUT_DOWN_LTHAND")
        }
        guard let cand else { return right != nil && startItemMotion(fig, "PUT_DOWN_RTHAND") }
        if itemHand(cand) == "LTHAND" {
            itemState.pickTargets[fig.name] = cand.key
            return startItemMotion(fig, "PICK_UP_LTHAND")
        }
        if right != nil { return startItemMotion(fig, "PUT_DOWN_RTHAND") }
        itemState.pickTargets[fig.name] = cand.key
        return startItemMotion(fig, "PICK_UP_RTHAND")
    }

    // MARK: motion events

    /// {MOTION: [(frames before the event, event byte)]} of a figure type (frame list of each motion header; first file wins).
    func figureEvents(_ type: String) -> [String: [(after: Int, code: Int)]] {
        if let e = itemState.events[type] { return e }
        var out: [String: [(after: Int, code: Int)]] = [:], lists: [String: [UInt8]] = [:]
        if let bedData = try? game.read("BODY/\(type).BED") {
            let bed = Bed(data: bedData)
            for f in bed.entries["LIST"] ?? bed.entries["MOTN"] ?? [] where game.resolve("BODY/\(f)") != nil {
                guard let d = try? game.read("BODY/\(f)"), let kids = try? IFF.parse(d).first?.children else { continue }
                for k in stride(from: 0, to: kids.count - 1, by: 2) {
                    let h = d.slice(kids[k].offset, kids[k].offset + kids[k].size)
                    let name = h.cString(0, 16).uppercased()
                    guard let n = try? h.u16(28) else { continue }
                    if lists[name] == nil { lists[name] = Array(h.slice(32, min(32 + n, h.count))) }
                    var frames = 0, evs: [(after: Int, code: Int)] = []
                    for byte in h.slice(32, min(32 + n, h.count)).map(Int.init) {
                        if ItemRules.eventMin <= byte && byte < 0xfe { evs.append((frames, byte)) }
                        else if byte < ItemRules.eventMin { frames += 1 }
                    }
                    if out[name] == nil { out[name] = evs }
                }
            }
        }
        itemState.events[type] = out
        itemState.eventLists[type] = lists
        return out
    }

    /// The raw frame event list of a figure type's motion (header u16 count at +28, bytes from +32), empty if none.
    func eventList(_ type: String, _ motion: String?) -> [UInt8] {
        _ = figureEvents(type)
        return itemState.eventLists[type]?[(motion ?? "").uppercased()] ?? []
    }

    /// Walk the figure's frame event list (`eventWalk`), and stand the player up when its pick-up / put-down has played out.
    func motionEvents(_ fig: Figure) {
        guard fig.frames != nil else { return }
        eventWalk(fig)
        if fig.finished, ItemRules.itemMotions.contains(fig.motion ?? ""), fig === player, fig.go == nil {
            fig.setMotion("STAND", loop: true)           // ASSUMPTION: the player stands up when a pick-up / put-down ends, also when a script ran it
        }
    }

    /// FUN_1088_1854's frame event walk (1088:1854, dispatch FUN_1088_13ea). The list (motion header u16 count at +28, bytes from +32)
    /// holds frame numbers with event bytes between them. Each time the frame changes, the walk goes on from where it stopped and
    /// dispatches every event byte until it meets the byte frame + 1 or 0xfe (the loop end, where it waits for the wrap) or the list
    /// ends; a new motion and a loop wrap start it again at the first byte. So the events before frame byte k fire when frame k - 1
    /// shows (PICK_UP_LTHAND's 0xef while frame 15 shows), those before frame byte 0 at the motion's first frame. After a wrap the next
    /// walk happens at the first frame change (1088:1854 restarts the frame at 0 with the previous frame 0). Dispatch: 0xfd..0xf9 sound
    /// cues n = 1, 1, 2, 3, 4 (case -3 and -3 - byte; `motionCue`), 0xef grab, 0xee / 0xf3 / 0xf4 drop both / right / left, 0xf0
    /// fire. NOT PORTED: 0xec (case -0x14: jump to the motion's last frame and commit its root; it only ever follows the last frame
    /// byte) and 0xf8 (the figure's ambient loop; silent in the shipped data). Hidden, frozen and arriving figures do not advance, so
    /// they do not walk. See items.py `event_walk`.
    func eventWalk(_ fig: Figure) {
        let list = eventList(fig.type, fig.motion)
        var (mid, pos, last) = itemState.cueSeen[fig.name].map { ($0.id, $0.pos, $0.last) } ?? (nil, 0, -1)
        if mid != fig.motId { pos = 0; last = -1 }
        else if fig.idx < last { pos = 0; last = 0 }              // the loop wrapped (advance restarted at frame 0)
        if fig.idx > last {
            while pos < list.count {
                let c = Int(list[pos])
                if c == fig.idx + 1 || c == 0xfe { break }
                switch c {
                case 0xf9...0xfd: motionCue(fig, c == 0xfd ? 1 : 0xfd - c)
                case ItemRules.evGrab: grabEvent(fig)
                case ItemRules.evDropAny: dropEvent(fig, -1)
                case ItemRules.evDropRight: dropEvent(fig, 1)
                case ItemRules.evDropLeft: dropEvent(fig, 0)
                case ItemRules.evFire: fireEventItem(fig)
                default: break
                }
                pos += 1
            }
            last = fig.idx
        }
        itemState.cueSeen[fig.name] = (fig.motId, pos, last)
    }

    func spawnItemBlock(_ fig: Figure, _ item: Item, _ suffix: String) {
        let blk = "\(fig.name)_\(item.name)_\(suffix)"
        guard let vm, vm.blocks[blk] != nil else { return }
        vm.spawn(blk, ctx: ScriptContext(curFig: fig.name, curItem: item.key, owner: "level"))
        keyLog.append((vm.tick, "item", .str(blk)))
    }

    /// FUN_1090_15d0 (vtable +0x98, event 0xf0; INFERRED as the +0x98 target): the item in the right hand (FUN_1138_040c) with a non-zero
    /// IS_WEAPON property (FUN_1138_04e4) runs `<item name>_FIRE` with CURITEM = it; otherwise `<figure name>_FIRE` runs with no current
    /// item. CURFIG = the figure, the first slice runs at once, a missing block is skipped silently. See items.py `fire_event_item`.
    func fireEventItem(_ fig: Figure) {
        let item = heldItem(fig, "RTHAND")
        let weapon: Item? = item.flatMap { i in itemProp(i.type, "IS_WEAPON")?.first.map { $0 != "0" && !$0.isEmpty } == true ? i : nil }
        let blk = "\(weapon?.name ?? fig.name)_FIRE"
        guard let vm, vm.blocks[blk] != nil else { return }
        vm.spawn(blk, ctx: ScriptContext(curFig: fig.name, curItem: weapon?.key, owner: "level"))
        keyLog.append((vm.tick, "item", .str(blk)))
    }

    /// FUN_1088_5923 (vtable +0x90).
    func grabEvent(_ fig: Figure) {
        guard let fp = fig.pos else { return }
        var target = itemState.pickTargets.removeValue(forKey: fig.name).flatMap { items[$0] }
        if let t = target, t.owner != nil || t.pos == nil { return }
        if target == nil {
            target = pickupCandidate(fig)
            if target == nil { return }
        }
        let tp = target!.pos!
        if Int(hypot(tp.x - fp.x, tp.y - fp.y)) > ItemRules.grabReach {
            if fig === player { return }
            target = pickupCandidate(fig, reach: ItemRules.grabRetry.reach, cone: ItemRules.grabRetry.cone)
            if target == nil { return }
        }
        if attachItem(fig, target!) { spawnItemBlock(fig, target!, "TAKE") }
    }

    /// FUN_1138_088d + 05a1: the item goes into the hand its type names (`attachHand`) unless something is already there.
    func attachItem(_ fig: Figure, _ item: Item) -> Bool {
        let hand = attachHand(fig, item)
        if heldItem(fig, hand) != nil { return false }
        item.owner = fig.name; item.slot = hand; item.pos = nil
        return true
    }

    /// FUN_1088_5b43 (vtable +0x94): -1 = lthand then rthand, 0 = lthand, 1 = rthand.
    func dropEvent(_ fig: Figure, _ which: Int) {
        guard let item = which < 0 ? heldAny(fig) : heldItem(fig, ItemRules.hands[which]) else { return }      // -1: FUN_1138_036e, which also counts MY_HAND
        dropItem(fig, item)
        spawnItemBlock(fig, item, "DROP")
    }

    /// FUN_1138_099b: identity rotated X by I, Z by K, Y by J (the type's ON_GROUND degrees).
    func groundMatrix(_ item: Item) -> Mat3 {
        let a = ItemRules.parseNumbers(itemProp(item.type, "ON_GROUND") ?? [])
        var m = Mat3.identity
        for (axis, key) in [(0, "I"), (2, "K"), (1, "J")] { m = ItemRules.rot(m, Double((a[key] ?? 0) * 256) / 360, axis: axis) }
        return m
    }

    func dropItem(_ fig: Figure, _ item: Item) {
        guard let fp = fig.pos else { return }
        let m = groundMatrix(item)
        var origin = fp
        if let hand = handPose(fig, item) { origin = Scene.place([hand.origin], at: fp, yaw: -fig.heading)[0] }
        let (lo, hi) = hull(fig)
        let sup = support(lo, hi)
        let floor = sup > Self.noFloor ? Double(sup) : fp.z - Double(foot(fig))
        let low = itemMesh(item.type).map { $0.verts.map { m.apply($0).z }.min() ?? 0 } ?? 0
        item.owner = nil; item.slot = nil
        item.pos = V3(origin.x, origin.y, floor - low)
        item.matrix = m
    }

    /// The item's +0xb position as the engine's per-tick resolver leaves it (10f0:12c3 -> 10f0:1209 -> holder vtable +0x4c = 1088:5c19): a
    /// floor item keeps its own; a held item on a limb of its holder takes the limb pose (`handPose`, 1038:035b); an inventory item
    /// (1138:1274 frees the limb record, +0x30) or one whose limb the holder lacks takes the holder's own +0xb. nil if unplaced.
    /// ASSUMPTION: computed on demand from the current pose, which equals the value 1209 wrote this tick (the holder is updated first).
    func itemEnginePos(_ item: Item) -> V3? {
        guard let owner = item.owner else { return item.pos }
        guard let fig = figures[owner], let fp = fig.pos else { return nil }
        return itemWorldPose(item)?.pos ?? fp
    }

    // MARK: drawing

    /// (origin, matrix) of a held item in the holder's model space, or nil if the figure has no such limb.
    func handPose(_ fig: Figure, _ item: Item) -> (origin: V3, m: Mat3)? {
        guard let frames = fig.frames, !frames.isEmpty, let slot = item.slot,
              let li = fig.assets.assets.skeleton.limbs.firstIndex(where: { $0.name.uppercased() == slot }) else { return nil }
        let skeleton = fig.assets.assets.skeleton
        let (start, rot) = skeleton.solve(frames[min(fig.idx, frames.count - 1)])
        let end = start[li] + rot[li].r[1] * Double(skeleton.limbs[li].length)
        let a = ItemRules.parseNumbers(itemProp(item.type, "ON_" + slot) ?? [])
        let ang = SIMD3<Int>((a["I"] ?? 0) * 32 / 45, (a["J"] ?? 0) * 32 / 45, (a["K"] ?? 0) * 32 / 45)
        let off = V3(Double(ItemRules.attachUnits(a["X"] ?? 0)), Double(ItemRules.attachUnits(a["Y"] ?? 0)), Double(ItemRules.attachUnits(a["Z"] ?? 0)))
        let m = rot[li].rotated(ang)
        let origin = end + rot[li].apply(off) + m.r[1] * Double(ItemRules.attachUnits(a["LENGTH"] ?? 0))
        return (origin, m)
    }

    /// Floor items and items in a hand that are drawn for camera `cam`, in item order.
    func itemCels(_ cam: String, _ camera: Camera) -> [DrawFigure] {
        var out: [DrawFigure] = []
        for item in items.values {
            guard !item.hidden, let mesh = itemMesh(item.type) else { continue }
            var v: [V3]
            if item.owner == nil {
                guard let p = item.pos, let m = item.matrix else { continue }
                v = mesh.verts.map { p + m.apply($0) }
            } else {
                guard let fig = figures[item.owner!], let fp = fig.pos, let slot = item.slot, ItemRules.hands.contains(slot),
                      fig.viewCams == nil || fig.viewCams!.contains(cam), let pose = handPose(fig, item) else { continue }
                v = Scene.place(mesh.verts.map { pose.origin + pose.m.apply($0) }, at: fp, yaw: -fig.heading)
            }
            if !v.isEmpty && v.allSatisfy({ Scene.project($0, camera).z > Self.nearDepth }) {
                out.append(DrawFigure(name: item.name, mesh: mesh, world: v, anim: item.anim.mapValues(\.frame)))
            }
        }
        return out
    }
}
