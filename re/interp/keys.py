"""Player key mapping of the original handler FUN_10a8_0541 (see NOTES "Player keyboard handler").

    action(scan, mods, combat, playing) -> one of
      ('motion', name, True)   motion that lasts while the key is held (walk, run, turn_*, sidestep_*, atk_M*)
      ('oneshot', name)        motion started once (shoot, atk_shoot, atk_F*, atk_H*)
      ('use',) ('combat_toggle',) ('pickup',) ('pimm', 'INVENTORY'|''|'DIAGNOSTICS'|'JOURNAL')
      ('options',) ('credits',) ('save',) ('load',) ('exit',) ('gamma', +-10) ('version',)   or None

`scan` is the PC scan code (numpad and arrow/Home/End keys share them: the original told them apart only by
combat mode), `mods` the modifier flags (0x0c Shift, 0x30 Ctrl, 0xc0 Alt), `playing` the name of the motion the
player is playing now (only used by the combat M4/M6 rule).  SDL_SCANCODE -> PC scan code table: SDL_TO_PC.
"""
SHIFT, CTRL, ALT = 0x0c, 0x30, 0xc0      # ASSUMPTION: 0x30 / 0xc0 = Ctrl / Alt (NOTES: "probably"; Alt+V = version)

WALK_KEYS = (0x48, 0x47, 0x49)           # up, Home, PgUp (also numpad 8 / 7 / 9)
MOVES = {0x4b: 'turn_left', 0x4d: 'turn_right', 0x50: 'walk_back', 0x4f: 'sidestep_left', 0x51: 'sidestep_right'}
FAST = {'turn_left': 'turn_left_fast', 'turn_right': 'turn_right_fast'}
COMBAT_PAD = {0x47: 'M7', 0x48: 'M8', 0x49: 'M9', 0x4b: 'M4', 0x4d: 'M6', 0x4f: 'M1', 0x50: 'M2', 0x51: 'M3'}
# M4/M6 only start when none of these is playing (the NOTES list; the key's own motion may continue)
M46_BUSY = {'atk_m1', 'atk_m2', 'atk_m3', 'atk_m4', 'atk_m6', 'atk_m7', 'atk_m8', 'run', 'atk_m9'}
PIMM = {0x17: 'INVENTORY', 0x19: '', 0x20: 'DIAGNOSTICS', 0x24: 'JOURNAL'}
GAMMA = {0x33: -10, 0x34: 10, 0x4a: -10, 0x4e: 10}      # , . numpad- numpad+


def action(scan, mods, combat, playing=None):
    playing = (playing or '').lower()
    if scan in PIMM:
        return ('pimm', PIMM[scan]) if not mods else None
    if scan in GAMMA:
        return ('gamma', GAMMA[scan]) if mods & (SHIFT | ALT) else None
    if scan == 0x2f:
        return ('version',) if mods & ALT else None
    if scan == 0x1f:                                    # S: ignored with Alt (FUN_10a8_0541)
        return ('save',) if not mods & ALT else None
    if scan == 0x2d:                                    # Alt+X (global hook FUN_1128_0f7f)
        return ('exit',) if mods & ALT else None
    other = {0x2e: ('combat_toggle',), 0x39: ('use',), 0x13: ('credits',), 0x18: ('options',), 0x26: ('load',), 0x1c: ('pickup',)}
    if scan in other:
        return other[scan]
    if combat:
        if scan == 0x48 and mods & SHIFT:
            return ('motion', 'run', True)
        if scan == 0x4c:
            return ('oneshot', 'atk_shoot')
        if scan in COMBAT_PAD:
            pad = COMBAT_PAD[scan]
            kind = 'F' if mods & CTRL else 'H' if mods & ALT else 'M'
            name = 'atk_' + kind + pad[1]
            if scan in (0x4b, 0x4d) and kind == 'M' and playing in M46_BUSY and playing != name.lower():
                return None
            return ('motion', name, True) if kind == 'M' else ('oneshot', name)
        return None
    if scan in WALK_KEYS:
        return ('motion', 'run' if mods & SHIFT else 'walk', True)
    if scan in MOVES:
        name = MOVES[scan]
        return ('motion', FAST[name] if mods & SHIFT and name in FAST else name, True)
    if scan == 0x4c:
        return ('oneshot', 'shoot')
    return None


# SDL scancode -> PC scan code (arrow/Home/End/PgUp/PgDn and the keypad map to the same code)
SDL_TO_PC = {
    82: 0x48, 96: 0x48, 74: 0x47, 95: 0x47, 75: 0x49, 97: 0x49,        # up/KP8, Home/KP7, PgUp/KP9
    80: 0x4b, 92: 0x4b, 79: 0x4d, 94: 0x4d, 81: 0x50, 90: 0x50,        # left/KP4, right/KP6, down/KP2
    77: 0x4f, 89: 0x4f, 78: 0x51, 91: 0x51, 93: 0x4c,                  # End/KP1, PgDn/KP3, KP5
    6: 0x2e, 44: 0x39, 12: 0x17, 19: 0x19, 7: 0x20, 13: 0x24,          # C, Space, I, P, D, J
    22: 0x1f, 21: 0x13, 25: 0x2f, 54: 0x33, 55: 0x34, 86: 0x4a, 87: 0x4e,   # S, R, V, comma, period, KP-, KP+
    18: 0x18, 15: 0x26, 27: 0x2d, 40: 0x1c, 88: 0x1c,                        # O, L, X, Return, KP Enter
}
SDL_MODS = {225: 0x0c, 229: 0x0c, 224: 0x30, 228: 0x30, 226: 0xc0, 230: 0xc0}   # Shift, Ctrl, Alt
HELP = ('arrows/Home/PgUp walk (Shift run), End/PgDn sidestep, Space use, Enter pick up / put down, C combat, KP5 shoot, '
        'KP 7894 6123 attacks in combat (Ctrl F, Alt H), I P D J PIMM, '
        'O options, S save, L load, R credits, Alt+X exit, Esc quit/close monitor')
