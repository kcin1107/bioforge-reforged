"""Live preview of the Python world prototype (requires Homebrew SDL2).

    re/.venv/bin/python -I re/interp/play.py [--skip N]

Original key map (keys.py): arrows/Home/PgUp walk (Shift run), left/right turn, down back, End/PgDn sidestep,
Space use, C combat, keypad 5 shoot, keypad 7894 6123 attacks in combat (Ctrl F, Alt H), I/P/D/J PIMM,
Escape quits (or closes a monitor).  --headless N runs N ticks without a window as a smoke test.
--editor-cursor draws the MOUSE.SHP arrow at the mouse, as the original does only when started with -e (editor mode).
"""
import argparse
import ctypes as C
import ctypes.util
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import keys as keysmod  # noqa: E402
import settings as settingsmod  # noqa: E402
import vm as vmmod  # noqa: E402
import world as worldmod  # noqa: E402
import cam as cammod  # noqa: E402  (re/formats, on the path through world)
import mouse as mousemod  # noqa: E402
from flex import read_flex  # noqa: E402

RGB24 = 0x17101803
ESCAPE = 41
MOUSE_MOTION, MOUSE_DOWN, MOUSE_UP = 0x400, 0x401, 0x402
LEFT_MOUSE = 1


def monitor_coords(x, y):
    """Convert the fixed 640x400 SDL preview to the monitor's 320x200 coordinates."""
    return max(0, min(319, int(x) * 320 // 640)), max(0, min(199, int(y) * 200 // 400))


def sdl_api():
    path = C.util.find_library('SDL2')
    if not path:
        raise SystemExit('SDL2 not found; install Homebrew sdl2')
    sdl = C.CDLL(path)
    signatures = {
        'SDL_Init': (C.c_int, [C.c_uint32]),
        'SDL_Quit': (None, []),
        'SDL_GetError': (C.c_char_p, []),
        'SDL_CreateWindow': (C.c_void_p, [C.c_char_p, C.c_int, C.c_int, C.c_int, C.c_int, C.c_uint32]),
        'SDL_DestroyWindow': (None, [C.c_void_p]),
        'SDL_CreateRenderer': (C.c_void_p, [C.c_void_p, C.c_int, C.c_uint32]),
        'SDL_DestroyRenderer': (None, [C.c_void_p]),
        'SDL_CreateTexture': (C.c_void_p, [C.c_void_p, C.c_uint32, C.c_int, C.c_int, C.c_int]),
        'SDL_DestroyTexture': (None, [C.c_void_p]),
        'SDL_UpdateTexture': (C.c_int, [C.c_void_p, C.c_void_p, C.c_void_p, C.c_int]),
        'SDL_RenderClear': (C.c_int, [C.c_void_p]),
        'SDL_RenderCopy': (C.c_int, [C.c_void_p, C.c_void_p, C.c_void_p, C.c_void_p]),
        'SDL_RenderPresent': (None, [C.c_void_p]),
        'SDL_SetWindowTitle': (None, [C.c_void_p, C.c_char_p]),
        'SDL_PollEvent': (C.c_int, [C.c_void_p]),
        'SDL_GetKeyboardState': (C.POINTER(C.c_uint8), [C.c_void_p]),
    }
    for name, (result, args) in signatures.items():
        fn = getattr(sdl, name)
        fn.restype, fn.argtypes = result, args
    return sdl


AFTER_CHAOS_LOAD = 1197    # Lex stands in the cell this many ticks after the first CHAOS LOADLEVEL (scenarios.opening_ticks(1170))


def boot(skip, automated=None, settings=None):
    """Start a new game; skipped previews select the default difficulty themselves.  `skip`: boot ticks to run, or None to
    play the intro up to the first CHAOS load and then AFTER_CHAOS_LOAD ticks (Lex standing in the cell).  `settings`: the
    options to start with (the user's INSTALL.OPT by default)."""
    if automated is None:
        automated = skip is None or skip > 0
    world = worldmod.World('TITLE', state_dir=worldmod.INITGAME)
    world.configure_settings(settings or settingsmod.Settings.load())
    vm = vmmod.VM(world)
    vmmod.load_level(vm, 'TITLE')
    world.fire_event('TITLE_LOAD')
    vm.fire('GAME', 'global')

    def tick():
        vm.tick_once()
        world.step()
        if automated:
            world.choose_default_difficulty()
    if skip is None:
        while not world.level_loads:
            tick()
        skip = AFTER_CHAOS_LOAD
    for _ in range(skip):
        tick()
    if world.level == 'CHAOS' and 'CE31' in world.cameras:
        # The opening scene keeps CE33 locked while the nurse speaks; show Lex in this preview.
        world.script_auto = True
        world.set_camera('CE31', 'live preview')
    return world, vm


_shapes, _room_palettes = [], {}


def room_palette(cam):
    """The RGB palette of ROOMS/<cam>.CAM (its first entry), or None for a camera without room art."""
    if cam not in _room_palettes:
        path = os.path.join(worldmod.ROOMS, str(cam).upper() + '.CAM')
        pal = None
        if cam is not None and os.path.exists(path):
            d, ents = read_flex(path)
            pal = np.frombuffer(cammod.palette(d[ents[0][1]:ents[0][1] + 768]), np.uint8).reshape(256, 3)
        _room_palettes[cam] = pal
    return _room_palettes[cam]


def six_bit(pal):
    """A 256x3 palette of 8-bit channels (c * 255 // 63) back to the DAC's 6-bit values."""
    return (np.asarray(pal, np.int32) * 63 + 127) // 255


def to_rgb(world, cursor=None):
    """The 320x200 RGB frame to show: options, monitor, or room, with the gamma step applied (presentation only: the engine
    adds the offset to every palette it uploads, FUN_10e8_16bb; indexed frames and oracle palettes stay as they are).
    `cursor` = (x, y): draw the MOUSE.SHP arrow there in the screen's palette, as BIOFORGE.EXE -e does over every screen."""
    if world.credits_rolling():
        frame, pal, src = world.credits_rgb(), None, None       # the roll over the live picture, not dimmed
    elif world.options is not None and not world.options.closed:
        px, pal = world.options.render(world.options_underlay())
        pal = np.frombuffer(bytes(pal), np.uint8).reshape(256, 3)
        frame = pal[np.frombuffer(bytes(px), np.uint8)].reshape(200, 320, 3)
        src = six_bit(pal)
    elif world.monitor is not None:
        px, pal = world.monitor.render()
        pal = np.frombuffer(bytes(pal), np.uint8).reshape(256, 3)
        frame = pal[np.frombuffer(bytes(px), np.uint8)].reshape(200, 320, 3)
        src = six_bit(pal)
    else:
        shown = world.shown_picture_rgb() if world.flic is None else None
        if shown is not None:                                    # CAMERA SHOW (10d0:115c) switched the screen to the picture camera
            frame, room = shown, room_palette(world.shown_picture)
        else:
            frame, room = world.render(), room_palette(world.current_camera())
        pal = room if cursor is not None else None
        if world.flic is not None:                               # an open flic shows its own palette (flic_rgb)
            src = None if world.flic.frame is None else np.frombuffer(world.flic.frame.palette, np.uint8).reshape(256, 3) >> 2
        else:
            src = None if room is None else six_bit(room)
    if cursor is not None and pal is not None:
        if not _shapes:
            _shapes.append(mousemod.MouseShapes(os.path.join(worldmod.monitor_mod.DATA, 'MOUSE.SHP')))
        idx = np.zeros((200, 320), np.uint8)
        _shapes[0].draw(idx, 320, 200, mousemod.ARROW, *cursor)
        frame = frame.copy()
        frame[idx != 0] = pal[idx[idx != 0]]
    return world.present_rgb(frame, src)


def headless(skip, ticks):
    """Smoke test without SDL: hold up, open PIMM inventory, close it, render each stage."""
    world, vm = boot(skip, automated=True)
    while world.player() is None:
        vm.tick_once()
        world.step()
        world.choose_default_difficulty()
    player = world.player()
    start, seen = player.pos.copy(), set()
    shots = {5: lambda: world.key_down(0x48), 25: lambda: world.key_up(0x48), 30: lambda: world.key_down(0x17),
             50: lambda: (world.key_up(0x17), world.monitor_key('ESCAPE'))}
    for t in range(ticks):
        shots.get(t, lambda: None)()
        vm.tick_once()
        world.step()
        world.choose_default_difficulty()
        frame = to_rgb(world)
        assert frame.shape == (200, 320, 3)
        seen.add(player.motion if world.monitor is None else 'MON:' + world.monitor.name)
    print(f'headless ok: {ticks} ticks, moved {float(np.hypot(*(player.pos[:2] - start[:2]))):.0f} units, seen {sorted(seen)}')


def run(skip, max_ticks=None, editor_cursor=False):
    world, vm = boot(skip)
    sdl = sdl_api()
    if sdl.SDL_Init(0x20):
        raise SystemExit(sdl.SDL_GetError().decode())
    window = renderer = texture = None
    try:
        window = sdl.SDL_CreateWindow(b'BioForge prototype', 100, 100, 640, 400, 0x4)
        if not window:
            raise RuntimeError(sdl.SDL_GetError().decode())
        renderer = sdl.SDL_CreateRenderer(window, -1, 0)
        if not renderer:
            raise RuntimeError(sdl.SDL_GetError().decode())
        texture = sdl.SDL_CreateTexture(renderer, RGB24, 1, 320, 200)
        if not texture:
            raise RuntimeError(sdl.SDL_GetError().decode())
        event = C.create_string_buffer(64)
        keys = sdl.SDL_GetKeyboardState(None)
        sdl.SDL_SetWindowTitle(window, ('BioForge prototype - ' + keysmod.HELP).encode())
        down_scans, esc_down = set(), False
        cursor = (160, 100)                     # the engine centres the mouse at start-up (FUN_1058_066d(0xa0, 100))
        deadline = time.perf_counter()
        ticks = 0
        while True:
            if max_ticks is not None and ticks >= max_ticks:
                return
            if world.exit_requested:
                return
            if world.pending_load:
                world, vm = world.pending_load
            while sdl.SDL_PollEvent(event):
                kind = C.cast(event, C.POINTER(C.c_uint32)).contents.value
                if kind == 0x100:
                    return
                options_open = world.options is not None and not world.options.closed
                if kind in (MOUSE_MOTION, MOUSE_DOWN, MOUSE_UP):
                    cursor = monitor_coords(C.c_int32.from_buffer(event, 20).value, C.c_int32.from_buffer(event, 24).value)
                if kind in (MOUSE_MOTION, MOUSE_DOWN, MOUSE_UP) and (options_open or world.monitor is not None):
                    pos = cursor
                    if options_open:
                        world.options.pointer_move(*pos)
                        if kind != MOUSE_MOTION and C.c_uint8.from_buffer(event, 16).value == LEFT_MOUSE:
                            if kind == MOUSE_DOWN:
                                world.options.mouse_down()
                            else:
                                world.options.mouse_up()
                        continue
                    world.monitor.pointer_move(*pos)
                    if kind != MOUSE_MOTION and C.c_uint8.from_buffer(event, 16).value == LEFT_MOUSE:
                        if kind == MOUSE_DOWN:
                            world.monitor.mouse_down()
                        else:
                            world.monitor.mouse_up()
            mods = 0
            for sc, bit in keysmod.SDL_MODS.items():
                mods |= bit if keys[sc] else 0
            esc = bool(keys[ESCAPE])
            if esc and not esc_down:
                # A monitor or the dialog takes the keys before a script's keyboard hook (FUN_10e8_11e3 gives them to the monitor while
                # one is up), as in the app.
                if world.options is not None and not world.options.closed:
                    world.option_key('ESCAPE')
                elif world.keyboard_captured and world.monitor is None:
                    pass                                 # the hook block answers (key_event below)
                elif world.flic is not None:
                    pass                                 # an open flic ignores Esc (10a8:02cc)
                elif world.monitor is None:
                    return
                else:
                    world.monitor_key('ESCAPE')
            esc_down = esc
            now = {pc for sc, pc in keysmod.SDL_TO_PC.items() if keys[sc]}
            for pc in sorted(down_scans - now):
                world.key_up(pc, mods)
            screen_up = world.monitor is not None or (world.options is not None and not world.options.closed)
            for pc in sorted(now - down_scans):
                # a captured keyboard answers to the hook block, unless a monitor or the dialog is up
                (world.key_event if world.keyboard_captured and not screen_up else world.key_down)(pc, mods)
            world.key_mods = mods
            down_scans = now
            vm.tick_once()
            world.step()
            ticks += 1
            frame = to_rgb(world, cursor if editor_cursor else None)
            if sdl.SDL_UpdateTexture(texture, None, C.c_void_p(frame.ctypes.data), 960):
                raise RuntimeError(sdl.SDL_GetError().decode())
            sdl.SDL_RenderClear(renderer)
            sdl.SDL_RenderCopy(renderer, texture, None, None)
            sdl.SDL_RenderPresent(renderer)
            deadline += 1 / vmmod.TPS
            delay = deadline - time.perf_counter()
            if delay > 0:
                time.sleep(delay)
            elif delay < -1 / vmmod.TPS:
                deadline = time.perf_counter()
    finally:
        if texture:
            sdl.SDL_DestroyTexture(texture)
        if renderer:
            sdl.SDL_DestroyRenderer(renderer)
        if window:
            sdl.SDL_DestroyWindow(window)
        sdl.SDL_Quit()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--skip', type=int, default=None,
                        help='boot ticks to run before opening the window (default: through the intro until Lex stands in the cell)')
    parser.add_argument('--ticks', type=int, default=None, help='close after N live ticks (for smoke tests)')
    parser.add_argument('--headless', type=int, default=None, metavar='N', help='run N ticks without a window (smoke test)')
    parser.add_argument('--editor-cursor', action='store_true', help='draw the MOUSE.SHP arrow at the mouse, as BIOFORGE.EXE -e does')
    args = parser.parse_args()
    if args.headless is not None:
        headless(args.skip, args.headless)
    else:
        run(args.skip, args.ticks, args.editor_cursor)
