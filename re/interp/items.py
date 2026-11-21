"""Items on the floor and in the hands: drawing them, and the Enter key (pick up / put down).

World mixes `ItemsMixin` in; world.py calls `load_floor_items`, `player_pickup`, `motion_events` and `item_cels`.

Decoded rules (BIOFORGE.EXE; every function is cited, everything not read from the code is marked ASSUMPTION):

Key.  The player key handler FUN_10a8_0541 maps scan 0x1c (Enter, any modifiers) to FUN_1088_5729 (`player_pickup`).  With L / R
the item in `lthand` / `rthand` (FUN_1138_040c: the first item of the item/physical list whose holder is the figure and whose hand
string equals the name, case-insensitively) and C = the candidate on the floor (FUN_1138_0000 called with reach 0x900 and cone 60):
    L held:  R held -> put_down_lthand;  else C and handedness(C) == rthand (FUN_1138_0453) -> pick_up_rthand; else put_down_lthand
    L empty: no C -> put_down_rthand if R held, else nothing;  C with handedness lthand -> pick_up_lthand;
             else R held -> put_down_rthand;  else pick_up_rthand
The target is stored at figure +0x199 only on the two L-empty pick-ups.  handedness = the item type's `HANDEDNESS` property, default
`lthand` (FUN_1138_0453 / 088d; DGROUP 6446).  The motion goes through vtable +0x7c (FUN_1098_0e49): a script block `<TYPE>_<MOTION>`
(LEX_PUT_DOWN_LTHAND in CHAOS / BEACH / PLATFORM, gated by LEGALTODROPHERE) runs instead when it exists, else the motion plays; the
request is refused (+0x8c, FUN_10a8_1f58) while the same motion is already current.

Selection (FUN_1138_0000(out, figure, reach, cone)): a visible figure whose hit points are <= 0 and lies within 0x800 (2D) raises
reach to 0x1000 and cone to 1000 (loot a corpse).  Then over the item list in order, items with no holder (+0x2c/+0x2e == 0; hidden
ones are NOT skipped): d = 2D distance (FUN_1210_000d; x, y only) < reach, |bearing| < cone degrees where bearing = vtable +0x60 =
FUN_1088_5ee1 (item position against the figure's facing), and (best >> 8) << 8 > d with best starting at reach: the nearest wins,
the earlier item on ties (best is kept as d >> 8).

Transfer (event bytes in the motion header's frame list: u16 count at +28, list at +32; frame numbers with event bytes between them;
FUN_1088_3629 maps 0xef -> vtable +0x90, 0xee / 0xf3 / 0xf4 -> vtable +0x94 with -1 / 1 / 0, 0xf0 -> +0x98 = FUN_1090_15d0):
  PICK_UP_LTHAND  0xef after 16 of 32 frames    PICK_UP_RTHAND  0xef after 15 of 29    (BODY/MAN.MTN, Lex)
  PUT_DOWN_LTHAND 0xf4 after 12 of 21           PUT_DOWN_RTHAND 0xf3 after 16 of 29
  ("after N" frame bytes; the walk, `event_walk`, fires such an event while frame N - 1 shows.)
  0xef = FUN_1088_5923: takes the stored target (+0x199, cleared); if it is still unheld and in the item list it is used, else a new
      FUN_1138_0000(0x900, 60) search; the item must lie within 0x1000 of the figure (a non-player figure may instead search again
      with 0xb00 / 180); then FUN_1138_088d attaches it (hand = the item's handedness, or `my_hand` if the holder has no limb of
      that name; skipped when that hand is occupied): FUN_1138_05ff sets holder, hand string, and the attachment limb's rest angles
      and offsets from the item type's `ON_<HAND>` property; then the script block `<holder>_<item>_TAKE` runs (FUN_1088_5923, format
      1290:261b) with the holder as the current figure and the item as the current item, if it exists.
  0xee / 0xf3 / 0xf4 = FUN_1088_5b43: the item in lthand (0), rthand (1) or lthand-then-rthand (-1) is dropped (FUN_1138_099b), then
      `<holder>_<item>_DROP` runs (format 1290:2626).
Held item.  Its world transform is a child limb of the holder's hand limb (FUN_1088_5c19 -> FUN_1038_035b): origin = hand-limb END
position + X, Y, Z (cm * 20.48, in the limb's own axes) + LENGTH along the rotated Y axis; orientation = the limb matrix rotated by
the ON_<HAND> angles (I, J, K degrees * 32 / 45 = 256-unit angles, applied Z, X, Y as in salsa.rotate; FUN_1030_1054).  The hand
limbs are `RtHand` / `LtHand` (case-insensitive match, FUN_1040_17d6 + FUN_1000_5a06).
Drop (FUN_1138_099b): holder cleared, hand string freed, collision flag (+0x34 bit 0x02) cleared, orientation reset and rotated by
the type's ON_GROUND angles (degrees, as 24.8 fixed): X by I, then Z by K, then Y by J (FUN_1208_2548 / 2b64 / 2858); the item
starts at its hand position and falls (HAS_GRAVITY, bounce).  ASSUMPTION: it lands at once with its lowest vertex on the floor
under the figure's hull (`World.support`, else the figure's feet) at the hand's x, y; no bounce, no collision push-out.
"""
import struct
import math
import os
import re
import sys
import types

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'formats'))
import bed  # noqa: E402
import level as levelmod  # noqa: E402
import salsa  # noqa: E402
from eor import Mesh  # noqa: E402
from iff import parse as iff_parse  # noqa: E402
from scene import place, project  # noqa: E402

PICKUP_REACH, PICKUP_CONE = 0x900, 60                  # FUN_1088_5729 / 5923 -> FUN_1138_0000
LOOT_NEAR, LOOT_REACH, LOOT_CONE = 0x800, 0x1000, 1000  # a corpse within LOOT_NEAR widens the search (FUN_1138_0000)
GRAB_REACH = 0x1000                                    # FUN_1088_5923: the target must still be this close
GRAB_RETRY = (0xb00, 0xb4)                             # non-player figures search again with this reach / cone
EV_GRAB, EV_DROP_ANY, EV_DROP_RIGHT, EV_DROP_LEFT, EV_FIRE = 0xef, 0xee, 0xf3, 0xf4, 0xf0
EVENT_MIN = 0xe0                                       # frame-list bytes from here (below 0xfe) are events
HANDS = ('LTHAND', 'RTHAND')
ITEM_MOTIONS = {'PICK_UP_LTHAND', 'PICK_UP_RTHAND', 'PUT_DOWN_LTHAND', 'PUT_DOWN_RTHAND'}
BODY_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'game', 'app', 'Bioforge', 'BODY')
ITEMS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'game', 'app', 'Bioforge', 'ITEMS')

_EVENTS, _EVENT_LISTS, _MESHES = {}, {}, {}


def c_div(a, b):
    """C integer division (truncates toward zero)."""
    q = abs(int(a)) // abs(int(b))
    return q if (a < 0) == (b < 0) else -q


def attach_units(cm):
    """FUN_1138_05ff: a script length in cm as game units, ((cm * 80) / 10 << 8) / 100 in long arithmetic."""
    return c_div(c_div(int(cm) * 80, 10) * 256, 100)


def figure_events(ftype, body):
    """{MOTION: [(frames before the event, event byte)]} of a figure type (frame list of each motion header; first file wins)."""
    if ftype not in _EVENTS:
        out = {}
        b = bed.read_bed(os.path.join(body, ftype + '.BED'))
        for f in b.get('LIST', b['MOTN']):
            if not os.path.exists(f):
                continue
            d = open(f, 'rb').read()
            kids = iff_parse(d)[0][4]
            for k in range(0, len(kids) - 1, 2):
                _, _, hp, hs, _ = kids[k]
                h = d[hp:hp + hs]
                name = h[:16].split(b'\0')[0].decode('latin1').upper()
                n = int.from_bytes(h[28:30], 'little')
                _EVENT_LISTS.setdefault(ftype, {}).setdefault(name, bytes(h[32:32 + n]))
                frames, evs = 0, []
                for byte in h[32:32 + n]:
                    if EVENT_MIN <= byte < 0xfe:
                        evs.append((frames, byte))
                    elif byte < EVENT_MIN:
                        frames += 1
                out.setdefault(name, evs)
        _EVENTS[ftype] = out
        _EVENT_LISTS.setdefault(ftype, {})
    return _EVENTS[ftype]


def event_list(ftype, motion, body=BODY_DIR):
    """The raw frame event list of a figure type's motion (header u16 count at +28, bytes from +32), b'' if none."""
    figure_events(ftype, body)
    return _EVENT_LISTS[ftype].get(str(motion).upper(), b'')


def item_mesh(item_type):
    if item_type not in _MESHES:
        path = os.path.join(ITEMS_DIR, item_type + '.IFF')
        try:
            _MESHES[item_type] = Mesh(path) if os.path.exists(path) else None
        except (OSError, StopIteration, ValueError, KeyError):
            _MESHES[item_type] = None
    return _MESHES[item_type]


def parse_numbers(vals):
    """`(180I,90J,0K) 0LENGTH (0X,0Y,0Z)` tokens -> {'I': 180, ...}; a bare number is I, J or K by its position (`(90I,0,0)`)."""
    out = {}
    for i, v in enumerate(vals):
        m = re.fullmatch(r'(-?\d+)([A-Z]*)', str(v).upper())
        if m and (m.group(2) or i < 3):
            out[m.group(2) or 'IJK'[i]] = int(m.group(1))
    return out


class ItemsMixin:
    # ---- script properties of an item type (`< NAME = ... >` tables of its ITEMS.scr block)
    def item_prop(self, item_type, name):
        blk = self.vm.blocks.get(item_type) if self.vm is not None else None
        for n, vals, _ in (blk.tables if blk else ()):
            if n and n.upper() == name:
                return vals
        return None

    def item_hand(self, item):
        """FUN_1138_0453 / 088d: the item's `HANDEDNESS`, default lthand (DGROUP 6446)."""
        vals = self.item_prop(item.type, 'HANDEDNESS')
        return str(vals[0]).upper() if vals else 'LTHAND'

    # ---- floor items
    def stash_level_items(self, travelling=(), carry_items=()):
        """A level change keeps the old level's items with that level (FUN_1148_14a3 -> 1404): the player, and every object it holds
        (recursively, FUN_1088_2da1 -> FUN_1070_06ba -> FUN_1060_0df8), is detached into the carry list first, then the level's other
        objects are written to its GAMEDAT IFF (FUN_1148_1232) and read back from there on a return (FUN_1148_1386).  Here the items
        that stay are kept in `level_items[level]` (in list order, each with its script locals); items held by the player or by a
        `travelling` figure (an elevator's volume carries them, FUN_1060_0df8 again) stay in World.items, and so do the
        floor items named in `carry_items` (the volume's, whose hull the volume overlaps; FUN_10d0_4d46).  A level change has already
        destroyed every missile (missiles.py end_missiles_for_level_change, 10d0.c:4280)."""
        if not getattr(self, 'level', None):
            return
        keep = {self.player_name, 'PLAYER'} | {str(n).upper() for n in travelling}
        stay, items = [], {}
        for key, item in self.items.items():
            if (item.owner is not None and str(item.owner).upper() in keep) or key in carry_items:
                items[key] = item
            else:
                locals_ = list(self.vm.objects.pop(key, [0] * 10)) if self.vm is not None else list(self.record_locals.get(key, [0] * 10))
                stay.append((item, locals_))
        self.items = items
        self.level_items[self.level] = stay

    def load_floor_items(self):
        """The level's items: those kept when the player last left it (`level_items`, stash_level_items), else its ITEM records with no
        holder (floor items) or held by one of its FIGR figures (carried by the player: resume.py).  A kept item gets a fresh key if
        an item that travelled took its name meanwhile, and its script locals come back with it."""
        W = sys.modules[type(self).__module__]
        if self.level in self.level_items:
            for item, locals_ in self.level_items.pop(self.level):
                item = self.add_item(item)
                if self.vm is not None:
                    self.vm.objects[item.key] = list(locals_)
                else:
                    self.record_locals[item.key] = list(locals_)
            return
        figs = {i: o for i, o in enumerate(self.objs, 1) if o['tag'] == 'FIGR'}
        for o in self.objs:
            if o['tag'] != 'ITEM' or len(o['raw']) != 191:
                continue
            r = levelmod.ObjRec('ITEM', o['raw'])
            name = (r.inst or r.name).upper()
            holder = figs.get(r.holder)
            if r.holder and holder is None:
                continue                                        # the player's (resume.py), or a holder that is not a figure
            owner = (holder['raw'][33:58].split(b'\0')[0].decode('latin1') or holder['name']).upper() if holder else None
            item = self.add_item(W.Item(name, r.name.upper(), owner, (r.hand.upper() or 'INVENTORY') if owner else None))
            if owner is None:
                item.pos = np.array(r.pos, float)
                item.matrix = np.array(r.matrix, float) / 256
            item.hidden = bool(r.flags & levelmod.F_HIDDEN)
            self.record_locals[item.key] = list(struct.unpack_from('<10i', o['raw'], 106))     # the script locals ~0..~9, as a FIGR's: MEDICAID's 5 charges, a battery's energy

    # ---- the item list (DS:1d0d count / 1d15 pointers; append 1050:10bf, remove 1050:0ff4)
    def add_item(self, item):
        """Append an item to the list.  The engine never makes instance names unique (CREATEITEM names the item after its type, so
        two ABAT_500 coexist), so the port keys World.items separately: `item.key` is the name when it is free, else `NAME#2`, `NAME#3`...
        `proc.cur_item`, `vm.objects`, `pick_targets` and the monitor's inventory entries hold the key; script block names and texts use
        `item.name` / `item.type`.  -> the item"""
        key, n = item.name, 2
        while key in self.items:
            key, n = f'{item.name}#{n}', n + 1
        item.key = key
        self.items[key] = item
        return item

    def rename_item(self, item, name):
        """INDIVIDUALIZE CURITEM (10d0:3e87 -> vtable +0x6c) overwrites only the instance name (+0xf7): the item keeps its list position and
        its locals.  The port re-keys it: the dict keeps the position, `vm.objects`, every process's CURITEM, the pending pick-up target and the
        monitor's inventory entries follow the new key."""
        old, item.name = item.key, name
        key, n = name, 2
        while key in self.items and self.items[key] is not item:
            key, n = f'{name}#{n}', n + 1
        if key == old:
            return
        item.key = key
        self.items = {(key if k == old else k): v for k, v in self.items.items()}
        if self.vm is not None:
            self.vm.rename_object(old, key)
            for p in self.vm.procs.values():
                if p.cur_item == old:
                    p.cur_item = key
        for fig, target in self.pick_targets.items():
            if target == old:
                self.pick_targets[fig] = key
        for e in (self.monitor.elements.values() if getattr(self, 'monitor', None) is not None else ()):
            e.items = [key if k == old else k for k in e.items]

    def item_by_type(self, name):
        """The generic object argument by name (10c0:16a8 -> 1050:0f34): after the figures, the first item in list order whose TYPE
        (+2, exact) equals the name."""
        name = str(name).upper()
        return next((i for i in self.items.values() if i.type == name), None)

    def find_item(self, fig, arg):
        """SETCURRENTITEM's search (10c0:3fd9; only the first argument counts): RTHAND / LTHAND -> the first item CURFIG holds in that
        hand (FUN_1088_5669; needs CURFIG), else the whole list with no holder test (missiles included): a candidate is an item whose type
        or instance name equals the argument; the nearest to the player (exact 2D distance, FUN_10a0_1e61, between the player's +0xb and the
        item's +0xb = `item_engine_pos`) wins, the first on ties.  -> the item or None"""
        arg = str(arg).upper()
        if arg in HANDS:
            return self.held_item(fig, arg) if fig is not None else None
        player = self.player()
        best, best_d = None, None
        for item in self.items.values():
            if arg != item.type and arg != item.name:
                continue
            pos = self.item_engine_pos(item)
            pos = (0, 0) if pos is None else pos                # never placed: +0xb is still zero
            d = 0 if player is None or player.pos is None else int(math.hypot(*(np.asarray(pos, float)[:2] - player.pos[:2])))
            if best is None or d < best_d:
                best, best_d = item, d
        return best

    def set_current_item(self, proc, fig, arg):
        """SETCURRENTITEM: CURITEM := the found item (1) or left unchanged (0)."""
        item = self.find_item(fig, arg)
        if item is None:
            return 0
        proc.cur_item = item.key
        return 1

    def is_carrying_item(self, fig, hand, arg):
        """ISCARRYING <hand> <type> (10d8:2845; both words and CURFIG needed).  INVENTORY / ANYWHERE run SETCURRENTITEM's search with the
        second word (CURITEM is restored): the found item's holder must be CURFIG, and for INVENTORY it must have no limb (+0x30 null =
        slot INVENTORY).  Any other word is a hand: FUN_1088_5669(CURFIG, hand, type) = an item held in that hand whose TYPE equals the
        second word."""
        if fig is None or arg is None:
            return False
        hand = str(hand).upper()
        if hand in ('INVENTORY', 'ANYWHERE'):
            item = self.find_item(fig, arg)
            return item is not None and item.owner == fig.name and (hand == 'ANYWHERE' or item.slot == 'INVENTORY')
        return any(i.owner == fig.name and i.slot == hand and i.type == str(arg).upper() for i in self.items.values())

    def held_item(self, fig, hand):
        """FUN_1138_040c: the first item the figure holds in `hand` (the item's hand string equals it)."""
        return next((i for i in self.items.values() if i.owner == fig.name and i.slot == hand), None)

    def my_hand(self, fig):
        """The holder type's `MY_HAND` property (FUN_1138_036e / 088d; FIGURES.scr NURSEBOT: UP_ARM), upper case, or None."""
        value = sys.modules[type(self).__module__].figure_prop(fig.name, fig.type, 'MY_HAND', None)
        return None if value is None else str(value).upper()

    def attach_hand(self, fig, item):
        """FUN_1138_088d: the hand string an attached item gets = the item's HANDEDNESS when the holder has a limb of that name
        (FUN_1040_17d6), else the holder type's MY_HAND; a holder with neither keeps the HANDEDNESS (no skeleton to check)."""
        hand = self.item_hand(item)
        limbs = [l.name.upper() for l in fig.assets.skel] if getattr(fig.assets, 'skel', None) else []
        if not limbs or hand in limbs:
            return hand
        return self.my_hand(fig) or hand

    def held_any(self, fig):
        """FUN_1138_036e: the first item held in lthand, rthand or MY_HAND."""
        return next((i for i in (self.held_item(fig, h) for h in HANDS + (self.my_hand(fig),)) if i is not None), None)

    def stow_item(self, fig, item):
        """FUN_1138_1274: move a held item into its holder's inventory."""
        if item.owner != fig.name or item.slot not in HANDS:
            return False
        item.slot, item.pos = 'INVENTORY', None
        return True

    def place_item(self, fig, item, slot, *where):
        """The item-placement cases needed by scripts and PIMM.

        `CARRY` calls FUN_1138_088d: use the item's declared hand (LTHAND by
        default; MY_HAND when the holder has no such limb, `attach_hand`), but
        leave the item where it is if that hand is occupied.
        """
        slot = str(slot).upper()
        if slot == 'CARRY':
            hand = self.attach_hand(fig, item) if fig is not None else self.item_hand(item)
            if fig is None or self.held_item(fig, hand) is not None:
                return False
            item.owner, item.slot, item.pos = fig.name, hand, None
            return True
        if slot == 'GROUND':
            if fig is None:
                return False
            self.drop_item(fig, item)
            return True
        if slot in ('COORDS', 'WAYPT'):                                 # 10d0:5510-5640: off its holder (FUN_1138_099b), then to x, y, z << 8 or the object's centre
            if slot == 'COORDS':
                pos = [float(int(v) << 8) for v in where[:3]]
            else:
                xy, z = self.arrival_point(str(where[0]).upper())[:2]
                pos = [float(xy[0]), float(xy[1]), float(z)]
            item.owner, item.slot = None, None
            item.pos = np.array(pos)
            item.matrix = self.ground_matrix(item)
            return True
        item.owner = fig.name if fig else item.owner
        item.slot = slot
        if slot in HANDS or slot == 'INVENTORY' or (fig is not None and slot in [l.name.upper() for l in fig.assets.skel]):
            item.pos = None             # an item attached to any limb (PLACEITEM RFINGER2) takes its pose from the holder, not a level position
        return True

    def floor_items(self):
        return [i for i in self.items.values() if i.owner is None and i.pos is not None and not i.missile]

    def pickup_candidate(self, fig, reach=PICKUP_REACH, cone=PICKUP_CONE):
        """FUN_1138_0000: the nearest floor item in front of the figure, or None (see the module doc)."""
        p = fig.pos[:2]
        for other in self.figures.values():
            if other.pos is None or other is fig or other.hidden:
                continue
            rec = self.vm.objects.get(self.object_key(other.name)) if self.vm is not None else None
            # ASSUMPTION: a figure is a corpse when its hit points are <= 0 although its maximum (~5) is set; an unset record is all zero
            if rec is not None and rec[0] <= 0 < rec[5] and int(math.hypot(*(other.pos[:2] - p))) < LOOT_NEAR:
                reach, cone = LOOT_REACH, LOOT_CONE
                break
        best, best_q = None, reach >> 8
        for item in self.floor_items():
            d = int(math.hypot(*(item.pos[:2] - p)))
            if d < reach and abs(self.rel_angle(fig, item.pos)) < cone and (best_q << 8) > d:
                best, best_q = item, d >> 8
        return best

    # ---- Enter
    def start_item_motion(self, fig, name):
        """Vtable +0x7c: the script block `<TYPE>_<MOTION>` if there is one (it decides), else the motion; refused while it is current."""
        blk = f'{fig.type}_{name}'
        if self.vm is not None and blk in self.vm.blocks:
            return self.spawn_for(fig, blk)
        if fig.motion == name and not fig.finished:
            return False
        return fig.set_motion(name, False)

    def player_pickup(self, fig):
        """FUN_1088_5729: pick up or put down, by what the hands hold and what lies in front (module doc)."""
        left, right = self.held_item(fig, 'LTHAND'), self.held_item(fig, 'RTHAND')
        cand = self.pickup_candidate(fig)
        if left is not None:
            if right is None and cand is not None and self.item_hand(cand) == 'RTHAND':
                return self.start_item_motion(fig, 'PICK_UP_RTHAND')
            return self.start_item_motion(fig, 'PUT_DOWN_LTHAND')
        if cand is None:
            return right is not None and self.start_item_motion(fig, 'PUT_DOWN_RTHAND')
        if self.item_hand(cand) == 'LTHAND':
            self.pick_targets[fig.name] = cand.key
            return self.start_item_motion(fig, 'PICK_UP_LTHAND')
        if right is not None:
            return self.start_item_motion(fig, 'PUT_DOWN_RTHAND')
        self.pick_targets[fig.name] = cand.key
        return self.start_item_motion(fig, 'PICK_UP_RTHAND')

    # ---- motion events
    def motion_events(self, fig):
        """Walk the figure's frame event list (`event_walk`), and stand the player up when its pick-up / put-down has played out."""
        if fig.frames is None:
            return
        self.event_walk(fig)
        if fig.finished and fig.motion in ITEM_MOTIONS and fig is self.player() and fig.go is None:
            fig.set_motion('STAND', True)        # ASSUMPTION: the player stands up when a pick-up / put-down ends, also when a script ran it

    def event_walk(self, fig):
        """FUN_1088_1854's frame event walk (1088:1854, dispatch FUN_1088_13ea). The list (motion header u16 count at +28, bytes from +32)
        holds frame numbers with event bytes between them. Each time the frame changes, the walk goes on from where it stopped and
        dispatches every event byte until it meets the byte frame + 1 or 0xfe (the loop end, where it waits for the wrap) or the list
        ends; a new motion and a loop wrap start it again at the first byte. So the events before frame byte k fire when frame k - 1
        shows (PICK_UP_LTHAND's 0xef while frame 15 shows), those before frame byte 0 at the motion's first frame. After a wrap the next
        walk happens at the first frame change (1088:1854 restarts the frame at 0 with the previous frame 0). Dispatch: 0xfd..0xf9 sound
        cues n = 1, 1, 2, 3, 4 (case -3 and -3 - byte; `motion_cue`), 0xef grab, 0xee / 0xf3 / 0xf4 drop both / right / left, 0xf0
        fire (see the module doc). NOT PORTED: 0xec (case -0x14: jump to the motion's last frame and commit its root; it only ever
        follows the last frame byte) and 0xf8 (the figure's ambient loop; silent in the shipped data). Hidden, frozen and arriving
        figures do not advance, so they do not walk."""
        lst = event_list(fig.type, fig.motion)
        mid, pos, last = self.cue_seen.get(fig.name, (None, 0, -1))
        if mid != fig.mot_id:
            pos, last = 0, -1
        elif fig.idx < last:                              # the loop wrapped (advance restarted at frame 0)
            pos, last = 0, 0
        if fig.idx > last:
            while pos < len(lst):
                c = lst[pos]
                if c == fig.idx + 1 or c == 0xfe:
                    break
                if 0xf9 <= c <= 0xfd:
                    self.motion_cue(fig, 1 if c == 0xfd else 0xfd - c)
                elif c == EV_GRAB:
                    self.grab_event(fig)
                elif c in (EV_DROP_ANY, EV_DROP_RIGHT, EV_DROP_LEFT):
                    self.drop_event(fig, {EV_DROP_ANY: -1, EV_DROP_RIGHT: 1, EV_DROP_LEFT: 0}[c])
                elif c == EV_FIRE:
                    self.fire_event_item(fig)
                pos += 1
            last = fig.idx
        self.cue_seen[fig.name] = (fig.mot_id, pos, last)

    def spawn_item_block(self, fig, item, suffix):
        blk = f'{fig.name}_{item.name}_{suffix}'
        if self.vm is not None and blk in self.vm.blocks:
            self.vm.spawn(blk, ctx=types.SimpleNamespace(cur_fig=fig.name, cur_item=item.key, owner='level'))
            self.key_log.append((self.vm.tick, 'item', blk))

    def fire_event_item(self, fig):
        """FUN_1090_15d0 (vtable +0x98, event 0xf0; INFERRED as the +0x98 target): the item in the right hand (FUN_1138_040c) with a
        non-zero IS_WEAPON property (FUN_1138_04e4) runs `<item name>_FIRE` with CURITEM = it; otherwise `<figure name>_FIRE` runs with
        no current item. CURFIG = the figure, the first slice runs at once, a missing block is skipped silently."""
        item = self.held_item(fig, 'RTHAND')
        vals = self.item_prop(item.type, 'IS_WEAPON') if item is not None else None
        weapon = item is not None and bool(vals) and str(vals[0]) not in ('0', '')
        blk = f'{(item.name if weapon else fig.name)}_FIRE'
        if self.vm is not None and blk in self.vm.blocks:
            self.vm.spawn(blk, ctx=types.SimpleNamespace(cur_fig=fig.name, cur_item=item.key if weapon else None, owner='level'))
            self.key_log.append((self.vm.tick, 'item', blk))

    def grab_event(self, fig):
        """FUN_1088_5923 (vtable +0x90)."""
        target = self.items.get(self.pick_targets.pop(fig.name, None))
        if target is not None and (target.owner is not None or target.pos is None):
            return
        if target is None:
            target = self.pickup_candidate(fig)
            if target is None:
                return
        if int(math.hypot(*(target.pos[:2] - fig.pos[:2]))) > GRAB_REACH:
            if fig is self.player():
                return
            target = self.pickup_candidate(fig, *GRAB_RETRY)
            if target is None:
                return
        if self.attach_item(fig, target):
            self.spawn_item_block(fig, target, 'TAKE')

    def attach_item(self, fig, item):
        """FUN_1138_088d + 05a1: the item goes into the hand its type names (`attach_hand`) unless something is already there."""
        hand = self.attach_hand(fig, item)
        if self.held_item(fig, hand) is not None:
            return False
        item.owner, item.slot, item.pos = fig.name, hand, None
        return True

    def drop_event(self, fig, which):
        """FUN_1088_5b43 (vtable +0x94): -1 = lthand then rthand, 0 = lthand, 1 = rthand."""
        item = self.held_any(fig) if which < 0 else self.held_item(fig, HANDS[which])      # -1: FUN_1138_036e, which also counts MY_HAND
        if item is None:
            return
        self.drop_item(fig, item)
        self.spawn_item_block(fig, item, 'DROP')

    def ground_matrix(self, item):
        """FUN_1138_099b: identity rotated X by I, Z by K, Y by J (the type's ON_GROUND degrees)."""
        vals = self.item_prop(item.type, 'ON_GROUND')
        a = parse_numbers(vals) if vals else {}
        R = np.eye(3)
        for axis, key in (('x', 'I'), ('z', 'K'), ('y', 'J')):
            R = salsa._rot(R, a.get(key, 0) * 256 / 360, axis, 1)
        return R

    def drop_item(self, fig, item):
        hand = self.hand_pose(fig, item)
        mesh = item_mesh(item.type)
        M = self.ground_matrix(item)
        origin = fig.pos if hand is None else place(hand[0][None, :], fig.pos, -fig.heading)[0]
        lo, hi = self.hull(fig)
        floor = self.support(fig, lo, hi)
        if floor <= -819200:                                    # NO_FLOOR: nothing below the hull
            floor = fig.pos[2] - self.foot(fig)
        low = min(float((np.asarray(v, float) @ M)[2]) for v in mesh.verts) if mesh is not None and mesh.verts else 0.0
        item.owner, item.slot = None, None
        item.pos = np.array([origin[0], origin[1], floor - low])
        item.matrix = M

    # ---- drawing
    def hand_pose(self, fig, item):
        """(origin, matrix) of a held item in the holder's model space (module doc), or None if the figure has no such limb."""
        if fig.frames is None:
            return None
        limbs = [l.name.upper() for l in fig.assets.skel]
        if item.slot not in limbs:
            return None
        i = limbs.index(item.slot)
        p, r, l = fig.frames[min(fig.idx, len(fig.frames) - 1)]
        _, R, end = salsa.solve(fig.assets.skel, ((0, 0, p[2]), r, l))
        a = parse_numbers(self.item_prop(item.type, 'ON_' + item.slot) or [])
        ang = tuple(c_div(a.get(k, 0) * 32, 45) for k in 'IJK')
        off = np.array([attach_units(a.get(k, 0)) for k in 'XYZ'], float)
        M = salsa.rotate(R[i], ang)
        origin = end[i] + off @ R[i] + M[1] * attach_units(a.get('LENGTH', 0))
        return origin, M

    def item_engine_pos(self, item):
        """The item's +0xb position as the engine's per-tick resolver leaves it (10f0:12c3 -> 10f0:1209 -> holder vtable +0x4c = 1088:5c19):
        a floor item keeps its own; a held item on a limb of its holder takes the limb pose (`hand_pose`, 1038:035b); an inventory item
        (1138:1274 frees the limb record, +0x30) or one whose limb the holder lacks takes the holder's own +0xb.  -> world position or None.
        ASSUMPTION: computed on demand from the current pose, which equals the value 1209 wrote this tick (the holder is updated first)."""
        if item.owner is None:
            return None if item.pos is None else np.asarray(item.pos, float)
        fig = self.figures.get(item.owner)
        if fig is None or fig.pos is None:
            return None
        pose = self.item_world_pose(item)
        return np.asarray(fig.pos, float) if pose is None else pose[0]

    def item_cels(self, cam, camera):
        """[(shaded mesh, world vertices)] of the floor items and the items in a hand that are drawn for `cam` (in item order)."""
        W = sys.modules[type(self).__module__]
        out = []
        for item in self.items.values():
            mesh = item_mesh(item.type)
            if mesh is None or item.hidden:
                continue
            if item.owner is None:
                if item.pos is None:
                    continue
                V = np.array([item.pos + np.asarray(v, float) @ item.matrix for v in mesh.verts])
            else:
                fig = self.figures.get(item.owner)
                if fig is None or fig.pos is None or item.slot not in HANDS or (fig.view_cams is not None and cam not in fig.view_cams):
                    continue
                pose = self.hand_pose(fig, item)
                if pose is None:
                    continue
                origin, M = pose
                V = place(np.array([origin + np.asarray(v, float) @ M for v in mesh.verts]), fig.pos, -fig.heading)
            if len(V) and np.all(project(V, camera)[:, 2] > W.NEAR_DEPTH):
                out.append((W.shade_mesh(mesh, V, np.asarray(camera['pos'], float), item.anim), V))
        return out

