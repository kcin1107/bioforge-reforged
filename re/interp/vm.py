"""BioForge script VM: cooperative scheduler (30 Hz), processes, expression evaluator.

Everything not listed in VM_STMTS / VM_FUNCS is delegated to the Engine interface:
    engine.call(kind, name, args, proc) -> value        kind = 'stmt' | 'func'
GUESSES (not established from the executable) are marked "GUESS" in comments.
"""
import collections
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import parse  # noqa: E402

TPS = 30
# Statements / functions implemented by the VM itself (SWITCH/CASE/DEFAULT/BREAK/IF/LABEL are compiled to jumps).
VM_STMTS = {'IF', 'ASSIGN', 'EXPR', 'WAIT', 'SUSPEND', 'SUSPENDWHILE', 'RETURN', 'JUMP', 'LOOP', 'LOCALVAR',
            'SWITCH', 'CASE', 'DEFAULT', 'BREAK', 'LABEL', 'BLOCK', 'KILLPROCESS', 'SUSPENDPROCESS',
            'RESUMEPROCESS', 'RESETREALTIME', 'SETFLAG', 'CLEARFLAG', 'TOGGLEFLAG', 'JUMPON'}
# SETCURRENTFIGURE / SETCURRENTITEM also update the process context and are forwarded to the engine.
VM_FUNCS = {'CALL', 'PROCESS', 'ISPROCESSVALID', 'SETCURRENTFIGURE', 'SETCURRENTITEM', 'MODIFYVAREVERYNTH', 'GETFLAG'}
ENGINE_STMTS = sorted(set(parse.STATEMENTS) - VM_STMTS)
ENGINE_FUNCS = sorted(parse.FUNCTIONS - VM_FUNCS)
FOREVER = 10 ** 9                # a native handle's sleep: it never runs again, only the engine finishes it
SLICE_BUDGET = 100000            # statements per slice before a runaway loop is forced to yield


class Engine:
    def call(self, kind, name, args, proc):
        raise NotImplementedError

    def scene_alive(self):
        """10c8:081b step 2: a RUNFLIC scene process lives while a flic is open and not finished."""
        return True


class RecordingEngine(Engine):
    """Logs (tick, process block name, kind, name, args); returns 0 unless `returns[name]` is set."""

    def __init__(self, returns=None):
        self.log, self.returns, self.vm = [], returns or {}, None

    def call(self, kind, name, args, proc):
        self.log.append((self.vm.tick if self.vm else 0, proc.block.name, kind, name, args))
        return self.returns.get(name, 0)


class Blocked(Exception):
    """Raised inside expression evaluation when the process must wait (CALL) and re-run the statement."""


class Ins:
    __slots__ = ('op', 'a', 'b', 'ts', 'line', 'stmt')

    def __init__(self, op, a=None, b=None, ts=None, line=0, stmt=None):
        self.op, self.a, self.b, self.ts, self.line, self.stmt = op, a, b, ts, line, stmt


class Code:
    def __init__(self, block):
        self.block, self.ins, self.labels, self.defidx = block, [], {}, {}
        self._else_at = {}                        # id(IF) -> where a false test of it (or of an IF wrapping it braceless) goes
        self._gen(block.body, [])
        self.ins.append(Ins('END'))

    def _gen(self, stmts, sw):
        emit = lambda op, a=None, b=None, s=None: (self.ins.append(Ins(op, a, b, s.ts if s else None, s.line if s else 0, s)),
                                                   len(self.ins) - 1)[1]
        for s in stmts:
            here = len(self.ins)
            if s.op == 'LABEL':
                self.labels.setdefault(s.args[0].upper(), here)
                self.defidx[s.defid] = here
            elif s.op == 'BLOCK':
                self._gen(s.then, sw)
            elif s.op == 'IF':
                jz = emit('JZ', s.args[0], None, s)
                self._gen(s.then, sw)
                if s.els is not None:
                    jmp = emit('JMP')
                    self.ins[jz].b = self._else_at[id(s)] = len(self.ins)
                    self._gen(s.els, sw)
                    self.ins[jmp].b = len(self.ins)
                else:
                    # IF (10d0:3a6c) stores its result per brace depth (ctx+0x75+depth) and a false one skips one statement
                    # (10c0:0f78: a nested IF is skipped as its line and body, not its ELSE); ELSE (10d0:27f9) runs iff that flag is
                    # 0. So an ELSE after a braceless chain `IF a THEN IF b THEN x ELSE y` also runs when `a` is false (WARHEAD_TIMER)
                    inner = s.then[0] if len(s.then) == 1 and s.then[0].op == 'IF' and not getattr(s, 'braced', False) else None
                    target = self._else_at.get(id(inner)) if inner is not None else None
                    self.ins[jz].b = len(self.ins) if target is None else target
                    if target is not None:
                        self._else_at[id(s)] = target
            elif s.op == 'SWITCH':
                ctx = {'idx': s.idx, 'cases': [], 'default': None, 'breaks': []}
                si = emit('SWITCH', s.args[0], ctx, s)
                self._gen(s.then, sw + [ctx])
                end = len(self.ins)
                ctx['end'] = end
                if ctx['default'] is None:
                    ctx['default'] = end
                for i in ctx['breaks']:
                    self.ins[i].b = end
            elif s.op in ('CASE', 'DEFAULT'):
                if not sw:
                    continue
                if s.op == 'CASE':
                    sw[-1]['cases'].append((s.args[0], here))
                else:
                    sw[-1]['default'] = here
                if s.defid is not None:
                    self.defidx[s.defid] = here
            elif s.op == 'BREAK':
                if sw:
                    sw[-1]['breaks'].append(emit('BREAK', s.args[0] if s.args else None, None, s))
                    self.ins[-1].a = (s.args[0] if s.args else None, sw[-1]['idx'])
            else:
                emit('STMT', s, None, s)


class Process:
    def __init__(self, vm, handle, block, code, ctx=None):
        self.vm, self.handle, self.block, self.code, self.pc = vm, handle, block, code, 0
        self.locals = [0] * 10
        self.cur_fig, self.cur_item = (ctx.cur_fig, ctx.cur_item) if ctx else (None, None)
        self.fig_index = 0           # FINDFIRSTFIGURE / FINDNEXTFIGURE's position in the engine figure list (+0x42)
        self.owner = getattr(ctx, 'owner', 'level') if ctx else 'level'     # 'global' (boot chain) | 'level': a label only, LOADLEVEL kills both
        self.wait_pred = None        # engine-installed predicate (blocking MOTION): the process sleeps until it is true
        self.goto = None             # engine-requested jump to a label of the current block (MON_JUMP)
        self.ended = False           # set by LOADLEVEL for a level-owned caller: finish after the current statement
        self.yield_now = False       # the statement just run ends this slice
        self.wake, self.suspended, self.done, self.retval = vm.tick, False, False, 0
        self.wait_on, self.waiters = None, []
        self.pending = {}            # id(CALL node) -> child process (blocked-in-expression CALLs)
        self.loops = {}              # LOOP counters, per instruction
        self.origin = None           # timeline clock origin (tick), None = not started
        self.gen = None              # native (VM-internal) process: generator yielding ticks to sleep
        self.referent = None         # +0xe83: the object whose destruction kills this process (SETREFERENT), set by the engine at spawn
        self.jumpon = None           # JUMPON watch (10d0:4024): (global variable key, (Code, pc) of the label) or None
        self.scene = False           # a RUNFLIC scene process (10c8:081b): dies when the flic is gone
        self.hold = None             # tick in which a wake-up came during the walk (1230:177a, flag 0x40): skipped for that walk
        self.cameras = []            # LINKMETOCAMERAS (10d0:4c72): every camera switch sets `suspended` unless the new camera is listed (10c0:5688)


class VM:
    def __init__(self, engine=None, defs=None, seed=0):
        self.defs = defs or parse.Defs()
        self.engine = engine or RecordingEngine()
        if hasattr(self.engine, 'vm'):
            self.engine.vm = self
        self.globals = dict(self.defs.vars)
        self.objects = collections.defaultdict(lambda: [0] * 10)
        if hasattr(self.engine, 'vm_attached'):
            self.engine.vm_attached()
        self.blocks, self.files, self.codes = {}, [], {}
        self.procs, self.next_handle, self.tick = collections.OrderedDict(), 1, 0
        self.walking = False                             # a scheduler walk is under way ([989f])
        self.changes, self.warnings, self.duplicates = [], [], []
        self._warned = set()

    # ---- loading
    def load(self, path):
        f = parse.parse_file(path, self.defs)
        self.files.append(f)
        for b in f.blocks:
            k = b.name.upper().rstrip('(')       # `{ FIRSTBOT_STIMULUS( _DAMAGE )` (no space) parses with the '(' in the name
            if k in self.blocks:         # GUESS: the first definition wins; duplicates are recorded
                self.duplicates.append((k, f.name, b.line))
            else:
                self.blocks[k] = b
        return f

    def unload_scripts(self):
        """Forget every loaded script file/block (level change). Globals and object state persist;
        running processes keep their own Code, so they can still finish."""
        self.blocks, self.files, self.codes, self.duplicates = {}, [], {}, []

    def call_chain(self, p):
        """`p` and the processes CALLing it, innermost first (the context's +0x71 caller links)."""
        chain = [p]
        while True:
            up = next((q for q in self.procs.values() if chain[-1] in q.pending.values()), None)
            if up is None or up in chain:
                return chain
            chain.append(up)

    def kill_level_owned(self, caller=None, keep=None):
        """LOADLEVEL: stop every process except `caller` and its CALL chain (FUN_10b0_13fb, 10b0.c:1103-1160, run by 1148:14a3 with the
        caller: it kills every kernel task but the caller and the contexts on its +0x71 links, and a class-0x110 sound manager the ports do
        not model). There is no exemption for the boot chain: a process fired with owner 'global' dies like any other. `keep` is the sound
        handle LOADLEVEL's voice stop (FUN_1028_12d2) leaves playing: a voice is not a kernel task, so its handle process survives the walk.
        Killed processes are dropped without resuming their waiters. -> number killed. The caller's fate is decided after the load:
        `end_unloaded`."""
        spared = self.call_chain(caller) if caller is not None else []
        n = 0
        for h, q in list(self.procs.items()):
            if q in spared or h == keep:
                continue
            q.done, q.waiters = True, []
            del self.procs[h]
            n += 1
        return n

    def end_unloaded(self, caller):
        """The tail of LOADLEVEL (10d0:4d46 after 1148:15c7): the caller ends (vtable +8, return 2) when its script file record
        (context +0xe87, found by name through 1118:434d) has no loaded code (+0xd/+0xf), i.e. its file is not in the new level's .LVL;
        otherwise it continues after LOADLEVEL (ELEVATOR.scr:280 → EXITSTASIS, ENDGAME.scr:4 in TITLE, TUN2PLAT.scr:12 'IT WORKS').
        TUNROOM.scr:160's caller dies because TUNROOM.scr is not in DIGSITE. ASSUMPTION: a level-owned CALL ancestor whose file is gone
        is dropped the same way (its code is not loaded either)."""
        loaded = {f.name.upper() for f in self.files}
        for q in self.call_chain(caller):
            file = getattr(q.block, 'file', None)
            if getattr(q, 'owner', None) != 'level' or file is None or file.name.upper() in loaded:
                continue
            if q is caller:
                q.ended = True
            else:
                q.done, q.waiters = True, []
                self.procs.pop(q.handle, None)

    def code(self, block):
        if block not in self.codes:
            self.codes[block] = Code(block)
        return self.codes[block]

    def warn(self, msg):
        if msg not in self._warned:
            self._warned.add(msg)
            self.warnings.append(f'tick {self.tick}: {msg}')

    # ---- processes
    def spawn(self, name, args=(), ctx=None, run=True, owner=None):
        b = self.blocks.get(str(name).upper())
        if b is None:
            self.warn(f'unknown block {name!r}')
            return None
        p = Process(self, self.next_handle, b, self.code(b), ctx)
        self.next_handle += 1
        if hasattr(self.engine, 'process_referent'):
            p.referent = self.engine.process_referent(p)
        if owner:
            p.owner = owner
        for i, v in enumerate(list(args)[:10]):          # args -> callee locals ~0.. (rest stay 0)
            p.locals[i] = v if isinstance(v, int) else 0
        self.procs[p.handle] = p
        if run:
            self.run(p)                                  # first slice immediately
        return p

    def locate(self, block, offset):
        """-> (Code, instruction index) of the first statement of `block` that starts at or after byte `offset` of its tokenized
        .SCP source (a saved process's pc / pc0); the END instruction when the block has none left."""
        code = self.code(block)
        first = {}
        for k, i in enumerate(code.ins):
            if i.stmt is not None:
                first.setdefault(id(i.stmt), k)
        for st, b in block.file.statements_from(offset):
            if b is not block:
                break
            if id(st) in first:                  # labels / CASE markers emit no instruction: fall through to the next one
                return code, first[id(st)]
        return code, len(code.ins) - 1

    def adopt(self, block, index, handle, ctx=None):
        """Register a process with an explicit handle (restored from a save: handles are task serials) positioned at
        instruction `index`; it does not run until the next tick. Later handles continue above it."""
        p = Process(self, handle, block, self.code(block), ctx)
        p.pc = index
        self.procs[handle] = p
        self.next_handle = max(self.next_handle, handle + 1)
        return p

    def fire(self, name, owner='level'):
        """Engine event: start block `name` as a detached process if it exists. -> handle or None.
        `owner` is a label only ('global' marks the boot chain, which everything it CALLs/PROCESSes inherits); LOADLEVEL kills both alike."""
        p = self.spawn(name, owner=owner)
        return p.handle if p else None

    def finish(self, p):
        if p.done:
            return
        p.done = True
        self.procs.pop(p.handle, None)
        ws, p.waiters = p.waiters, []
        for w in ws:                                     # 1238:077f clears the waiter's wait list; nothing runs it here
            if w.wait_on is p and not w.done:
                w.wait_on = None
                if self.walking:                         # 1230:177a: a task woken during a walk sits it out (flag 0x40); one
                    w.hold = self.tick                   # already passed would not be reached again either -> next walk

    def tick_once(self):
        if getattr(self.engine, 'paused', False):        # options dialog: scheduler and clock stand still (FUN_10b0_136b)
            return
        self.walking = True                              # [989f] (1230:0259)
        for p in list(self.procs.values()):
            if p.done or p.suspended or p.hold == self.tick:     # hold: 0x40, tested before the task's update (1230.c:173)
                continue
            if p.scene and not self.engine.scene_alive():        # 10c8:081b: no flic (or a finished one): ends before running anything
                self.finish(p)
                continue
            if p.jumpon is not None and self.watch_fires(p):     # 10c0:2626: polled at every update, also while waiting
                self.run(p)
                continue
            if p.wait_on or p.wake > self.tick:
                continue
            if p.wait_pred is not None:
                if not p.wait_pred():
                    continue
                p.wait_pred = None
            self.run(p)
        start = getattr(self.engine, 'start_pending_idles', None)
        if start is not None:
            start()                                      # idle motion tasks made in the last walk run in this one (World.request_idle)
        self.walking = False
        self.tick += 1

    def watch_fires(self, p):
        """The JUMPON poll (10c0:2626): when the watched global is non-zero the registration is cleared (one-shot), a pending wait is
        cancelled (also the waited-on process's waiters entry) and the process continues at the label. Level-triggered; the variable is
        not reset. -> True if it jumped."""
        if p.jumpon is None or not truth(self.globals.get(p.jumpon[0], 0)):
            return False
        (code, pc), p.jumpon = p.jumpon[1], None
        if p.wait_on is not None:
            if p in p.wait_on.waiters:
                p.wait_on.waiters.remove(p)
            p.wait_on = None
        p.wait_pred = None
        p.code, p.pc, p.block, p.wake = code, pc, code.block, self.tick
        return True

    def jumpon(self, p, args):
        """`JUMPON <VAR> <LABEL>` (10d0:4024): watch global `_VAR`, jump to LABEL of the current block. A later one replaces it. Warnings
        (registration cleared): no label (0x29), no variable (6), unknown variable (0x17), unknown label (0x11)."""
        words = [str(a) for a in args if isinstance(a, str)]
        var, label = (words + ['', ''])[:2]
        key = '_' + var.lower()
        p.jumpon = None
        if not label:
            self.warn('JUMPON: needs a label (error 0x29)')
        elif not var:
            self.warn('JUMPON: needs a variable (error 6)')
        elif key not in self.globals:
            self.warn(f'JUMPON {var}: unknown variable (error 0x17)')
        elif label.upper() not in p.code.labels:
            self.warn(f'JUMPON {var} {label}: unknown label (error 0x11)')
        else:
            p.jumpon = (key, (p.code, p.code.labels[label.upper()]))

    def run_ticks(self, n):
        for _ in range(n):
            self.tick_once()

    def run(self, p):
        if p.gen is not None:
            try:
                p.wake = self.tick + next(p.gen)
            except StopIteration:
                self.finish(p)
            return
        budget = SLICE_BUDGET
        while not p.done:
            if p.jumpon is not None:
                self.watch_fires(p)                      # ... and before every statement
            budget -= 1
            if budget == 0:
                self.warn(f'{p.block.name}: statement budget exhausted (runaway loop?), forcing a yield')
                p.wake = self.tick + 1
                return
            ins = p.code.ins[p.pc]
            if ins.ts is not None:                       # timeline: wait for the local clock
                if p.origin is None:
                    p.origin = self.tick                 # GUESS: clock starts at the first timed line / after RESETREALTIME
                if self.tick - p.origin < ins.ts:
                    p.wake = p.origin + ins.ts
                    return
            try:
                r = self.step(p, ins)
            except Blocked:
                return
            if r == 'yield' or r == 'end':
                if r == 'end':
                    self.finish(p)
                return

    # ---- execution
    def step(self, p, ins):
        nxt = p.pc + 1
        op = ins.op
        if op == 'END':
            return 'end'
        if op == 'JZ':
            if not truth(self.eval(p, ins.a)):
                nxt = ins.b
        elif op == 'JMP':
            nxt = ins.b
        elif op == 'SWITCH':
            v = self.eval(p, ins.a)
            nxt = ins.b['default']
            for e, idx in ins.b['cases']:
                if self.eval(p, e) == v:
                    nxt = idx
                    break
        elif op == 'BREAK':
            # FUN_10d0_0b77: BREAK n jumps past the file's n-th SWITCH, the number the compiler wrote in, always the innermost one
            # (FUN_10c0_01cc). An inline `IF ... THEN BREAK` never got a number (the compiler only reads a line's first statement),
            # and an empty operand is ERR_BREAK_NOT_PREPROCESSED: the statement does nothing and the next one runs.
            n, sidx = ins.a
            if n is not None:
                if self.eval(p, n) != sidx:
                    self.warn(f'{p.block.name}:{ins.line}: BREAK {self.eval(p, n)} != innermost switch index {sidx}')
                nxt = ins.b
        else:
            s = ins.a
            r = self.stmt(p, s, ins)
            if r is not None and not isinstance(r, str):    # jump: (kind, code, pc)
                p.code, p.pc = r[0], r[1]
                if r[0].block is not p.block:
                    p.block = r[0].block
                if p.wait_pred is not None:                   # jump and yield (MON_JUMP on a button event)
                    p.wake = self.tick + 1
                    return 'yield'
                return None
            if r == 'end':
                return 'end'
            p.pc = nxt
            return r
        p.pc = nxt
        return None

    def stmt(self, p, s, ins):
        op, a = s.op, s.args
        if op == 'ASSIGN':
            tgt, aop, val = a
            v = self.eval(p, val)
            if aop != '=':
                cur, v = self.eval(p, tgt), (v if isinstance(v, int) else 0)
                v = {'+=': cur + v, '++': cur + v, '-=': cur - v, '--': cur - v, '*=': cur * v,
                     '/=': idiv(cur, v)}[aop]
            self.assign(p, tgt, v)
        elif op == 'EXPR':
            self.eval(p, a[0])
        elif op == 'WAIT':
            n = self.eval(p, a[0])
            if len(a) > 1 and a[1][0] == 'name' and a[1][1].upper() in ('SECOND', 'SECONDS'):
                n *= TPS
            p.wake = self.tick + max(int(n), 1)
            return 'yield'
        elif op == 'SUSPEND':
            p.wake = self.tick + 1
            return 'yield'
        elif op == 'SUSPENDWHILE':
            h = self.eval(p, a[0])
            t = self.procs.get(h) if isinstance(h, int) else None
            if t and not t.done:
                p.wait_on = t
                t.waiters.append(p)
                p.pc += 1                                 # resume after the statement
                raise Blocked
        elif op == 'RETURN':
            p.retval = self.eval(p, a[0]) if a else 0
            return 'end'
        elif op == 'JUMP':
            return self.jump(p, a[0], ins)
        elif op == 'LOOP':
            n = self.eval(p, a[1]) if len(a) > 1 else None
            if n is None:
                return self.jump(p, a[0], ins)            # GUESS: LOOP without count = unconditional jump
            c = p.loops.get(id(ins), 0) + 1
            if c < n:
                p.loops[id(ins)] = c
                return self.jump(p, a[0], ins)
            p.loops.pop(id(ins), None)                    # GUESS: counter resets when the loop completes
        elif op == 'LOCALVAR':
            if getattr(s, 'init', None) is not None:      # GUESS: `LOCALVAR ~0 = v` initialises
                self.assign(p, a[0], self.eval(p, s.init))
        elif op == 'KILLPROCESS':
            t = self.procs.get(self.eval(p, a[0]))
            if t:
                self.finish(t)
        elif op in ('SUSPENDPROCESS', 'RESUMEPROCESS'):
            t = self.procs.get(self.eval(p, a[0]))
            if t:
                t.suspended = op == 'SUSPENDPROCESS'
        elif op == 'JUMPON':
            args = self.args(p, a)
            self.engine.call('stmt', op, args, p)             # logged like every statement; the watch itself is the VM's
            self.jumpon(p, args)
        elif op == 'RESETREALTIME':
            p.origin = None
        elif op in ('SETFLAG', 'CLEARFLAG', 'TOGGLEFLAG'):
            # GUESS: flag bit n of a variable is 1 << n; `SETFLAG (v, bit) = 1` extra value ignored
            cur, bit = self.eval(p, a[0]), 1 << self.eval(p, a[1])
            self.assign(p, a[0], cur | bit if op == 'SETFLAG' else cur & ~bit if op == 'CLEARFLAG' else cur ^ bit)
        else:
            self.engine.call('stmt', op, self.args(p, a), p)
            if p.ended:
                return 'end'
            if p.yield_now:                               # AI OFF on the process's own figure (10d0:04b3 returns 1)
                p.yield_now = False
                return 'yield'
            label, p.goto = p.goto, None
            if label is not None and label in p.code.labels:
                return (p.code, p.code.labels[label])
            if p.wait_pred is not None:                       # engine asked to block this process
                p.wake = self.tick + 1
                return 'yield'
        return None

    def jump(self, p, node, ins):
        """-> (Code, pc). Same block first; then block names; then labels of other blocks in the file."""
        if node[0] == 'defid':
            owner = p.code.block.file.defs.get(node[1])
            if owner is None:
                self.warn(f'{p.block.name}:{ins.line}: JUMP #{node[1]} unresolved; ignored')
                return None
            c = self.code(owner)
            return (c, c.defidx.get(node[1], 0))
        name = str(node[1]).upper() if node[0] == 'name' else None
        if name in p.code.labels:
            return (p.code, p.code.labels[name])
        if name == p.code.block.name.upper():
            return (p.code, 0)
        if name in self.blocks:
            self.warn(f'{p.block.name}:{ins.line}: JUMP {name} targets another block')
            return (self.code(self.blocks[name]), 0)
        for b in p.code.block.file.blocks:
            c = self.code(b)
            if name in c.labels:
                self.warn(f'{p.block.name}:{ins.line}: JUMP {name} targets a label in block {b.name}')
                return (c, c.labels[name])
        self.warn(f'{p.block.name}:{ins.line}: JUMP {node[1]!r} unresolved; ignored')
        return None

    # ---- variables
    def objname(self, p, sel):
        """Key into self.objects for `CURFIG.~n` / `CURITEM.~n` / `NAME.~n` (FUN_10c0_24e1). An unset CURFIG / CURITEM is error
        0x6f in the engine; here it falls to a placeholder record named after the selector. The engine may map names further
        (PLAYER -> the flagged player figure) with object_key()."""
        n = {'CURFIG': p.cur_fig, 'CURITEM': p.cur_item}.get(sel, sel) or sel
        key = getattr(self.engine, 'object_key', None)
        return key(n) if key else n

    def rename_object(self, old, new):
        """INDIVIDUALIZE: an object's locals live in the object itself (10c0:24e1 addresses them at +0x92 + 4n), so its record follows
        the new name (a record already under `new` is replaced)."""
        if old in self.objects:
            self.objects[new] = self.objects.pop(old)
        else:
            self.objects.pop(new, None)             # the item had no locals yet: it must not inherit a dead item's record

    def assign(self, p, tgt, v):
        k = tgt[0]
        if k == 'local':
            p.locals[tgt[1]] = v
        elif k == 'mlocal':
            self.objects[self.objname(p, tgt[1])][tgt[2]] = v
        elif k in ('var', 'name'):
            name = tgt[1].lower()
            old = self.globals.get(name, 0)
            self.globals[name] = v
            if old != v:
                self.changes.append((self.tick, name, old, v))
        else:
            self.warn(f'{p.block.name}: cannot assign to {tgt}')

    # ---- expressions
    def args(self, p, nodes):
        return [self.eval(p, n) for n in nodes]

    def eval(self, p, e):
        k = e[0]
        if k in ('num', 'const', 'str'):
            return e[1]
        if k == 'name':
            return e[1]
        if k == 'var':
            return self.globals.get(e[1], 0)
        if k == 'local':
            return p.locals[e[1]]
        if k == 'mlocal':
            return self.objects[self.objname(p, e[1])][e[2]]
        if k == 'list':
            return [self.eval(p, x) for x in e[1]]
        if k == 'un':
            return -num(self.eval(p, e[2]))
        if k == 'in':
            v, lst = self.eval(p, e[2]), self.eval(p, e[3])
            if not isinstance(lst, list):
                lst = [lst]
            # `x IN lo, hi` is an inclusive range in every use in the corpus (angles, COMPASS); other
            # list lengths: GUESS plain membership
            r = lst[0] <= num(v) <= lst[1] if len(lst) == 2 and all(isinstance(i, int) for i in lst) else v in lst
            return int(r != e[1])
        if k == 'bin':
            op = e[1]
            if op == 'OR':
                return int(truth(self.eval(p, e[2])) or truth(self.eval(p, e[3])))
            if op == 'AND':
                return int(truth(self.eval(p, e[2])) and truth(self.eval(p, e[3])))
            a, b = self.eval(p, e[2]), self.eval(p, e[3])
            if op == '==':
                return int(a == b)
            if op == '!=':
                return int(a != b)
            a, b = num(a), num(b)
            return {'<': lambda: int(a < b), '>': lambda: int(a > b), '<=': lambda: int(a <= b),
                    '>=': lambda: int(a >= b), '+': lambda: a + b, '-': lambda: a - b, '*': lambda: a * b,
                    '/': lambda: idiv(a, b), '%': lambda: a - b * idiv(a, b) if b else 0}[op]()
        if k == 'call':
            return self.call(p, e)
        raise ValueError(f'bad expression {e}')

    def call(self, p, e):
        name, a = e[1], e[2]
        if name in ('CALL', 'PROCESS'):
            if not a:
                return 0
            bname = a[0][1] if a[0][0] == 'name' else self.eval(p, a[0])
            rest = a[1:]
            if len(rest) == 1 and rest[0][0] == 'list':     # `CALL ( NAME( a, b ) )`: the parenthesised list is the argument list
                rest = rest[0][1]
            if name == 'PROCESS':
                # FUN_10c0_37e9 (10c0.c:2962-3027) runs the child's first slice only when the caller's block is a `{` routine; from a `[`
                # timeline block the child waits for the scheduler (CALL, 10c0:3968, always runs it). The task constructor (1238.c:154,
                # 1230:177a) holds a task created during a walk for the rest of it, so the child first runs in the next walk, as here.
                c = self.spawn(bname, self.args(p, rest), p, run=p.block.kind == 'routine')
                return c.handle if c else 0
            c = p.pending.get(id(e))                     # resumed after blocking?
            if c is None:
                c = self.spawn(bname, self.args(p, rest), p, run=False)
                if c is None:
                    return 0
                p.pending[id(e)] = c                     # the +0x71 link exists before the child's first slice: a LOADLEVEL in it spares the caller
                self.run(c)
            if not c.done:
                p.pending[id(e)] = c
                p.wait_on = c
                c.waiters.append(p)
                raise Blocked
            p.pending.pop(id(e), None)
            return c.retval
        if name == 'ISPROCESSVALID':
            h = self.eval(p, a[0]) if a else 0
            return int(h in self.procs)
        if name == 'MODIFYVAREVERYNTH':
            return self.modify_var(p, a)
        if name == 'GETFLAG':
            return (self.eval(p, a[0]) >> self.eval(p, a[1])) & 1      # GUESS: bit n = 1 << n
        args = [x[1] if x[0] == 'name' else self.eval(p, x) for x in a]
        if name == 'RUNFLIC' and len(a) >= 3 and a[2][0] == 'var':       # its optional 3rd argument is a live variable, not a snapshot
            args.append(a[2][1])
        prev = p.cur_fig
        if name == 'SETCURRENTFIGURE' and args:
            p.cur_fig = str(args[0]).upper()
            if p.cur_fig == 'ENEMY' and hasattr(self.engine, 'enemy_of'):     # ENEMY = the previous figure's enemy
                p.cur_fig = self.engine.enemy_of(prev) or p.cur_fig
        elif name == 'SETCURRENTITEM' and args and not hasattr(self.engine, 'set_current_item'):
            p.cur_item = str(args[0]).upper()           # a stub engine: the literal; an engine that models 10c0:3fd9 decides itself
        return self.engine.call('func', name, args, p)

    def timed_handle(self, ticks, owner='level'):
        """A native process that stays valid for `ticks` ticks (SUBTITLE / sound handles). -> handle"""
        c = Process(self, self.next_handle, parse.Block('TIMED', 'native', 0, None), None, None)
        c.code = Code(c.block)
        c.owner = owner
        self.next_handle += 1
        c.gen = iter([max(int(ticks), 1)])
        self.procs[c.handle] = c
        self.run(c)
        return c.handle

    def native_handle(self, name, owner='level'):
        """A native process that stays valid until the engine finishes it (a missile's handle: the original task serial, valid until
        the task is destroyed). Finishing it wakes the SUSPENDWHILE waiters like any process. -> handle"""
        c = Process(self, self.next_handle, parse.Block(name, 'native', 0, None), None, None)
        c.code = Code(c.block)
        c.owner = owner
        self.next_handle += 1
        c.gen = iter([FOREVER])
        self.procs[c.handle] = c
        self.run(c)
        return c.handle

    def native_generator(self, name, gen, owner='level'):
        """A native process driven by the generator `gen` (it yields the ticks to sleep; its end finishes the process): the OVERTIME
        ramps. -> handle"""
        c = Process(self, self.next_handle, parse.Block(name, 'native', 0, None), None, None)
        c.code = Code(c.block)
        c.owner = owner
        self.next_handle += 1
        c.gen = gen
        self.procs[c.handle] = c
        self.run(c)
        return c.handle

    def set_global(self, name, v):
        """An engine write of a script global (as `assign`)."""
        name = name.lower()
        old = self.globals.get(name, 0)
        self.globals[name] = v
        if old != v:
            self.changes.append((self.tick, name, old, v))

    def spawn_at(self, name, label, args=(), ctx=None, owner=None):
        """Start block `name` at `label` (engine-dispatched entry such as HIT_PLAYER_ATK_SYRINGE). -> Process or None"""
        b = self.blocks.get(str(name).upper())
        if b is None or str(label).upper() not in self.code(b).labels:
            return None
        p = self.spawn(name, args, ctx, run=False, owner=owner)
        p.pc = p.code.labels[str(label).upper()]
        self.run(p)
        return p

    def modify_var(self, p, a):
        """MODIFYVAREVERYNTH(var, step, start, end, n): native process. GUESS: var = start now, then
        var += step every n ticks until var == end."""
        tgt = a[0]
        step, start, end, n = self.args(p, a[1:5])
        def gen():
            v = start
            self.assign(p, tgt, v)
            while v != end and (v - end) * step < 0:
                yield max(n, 1)
                v += step
                self.assign(p, tgt, v)
        c = Process(self, self.next_handle, parse.Block('MODIFYVAREVERYNTH', 'native', 0, None), None, p)
        c.code = Code(c.block)
        self.next_handle += 1
        c.gen = gen()
        self.procs[c.handle] = c
        self.run(c)
        return c.handle


def truth(v):
    return bool(v)


def num(v):
    return v if isinstance(v, int) else 0


def idiv(a, b):
    return int(a / b) if b else 0


def load_level(vm, level, script_dir=None):
    """Load the scripts listed in <SCRIPT>/<LEVEL>.LVL (names mapped case-insensitively to re/out/scripts)."""
    script_dir = script_dir or os.path.join(parse.ROOT, 're', 'out', 'scripts')
    have = {n.lower(): n for n in os.listdir(script_dir)}
    lvl = os.path.join(parse.SCRIPT_DIR, level.upper() + '.LVL')
    loaded = []
    for line in parse.read_lines(lvl):
        w = line.split('//')[0].strip()
        if w.lower().endswith('.scr'):
            n = have.get(w.lower())
            if n:
                loaded.append(vm.load(os.path.join(script_dir, n)))
            else:
                vm.warn(f'{w}: not found in {script_dir}')
    return loaded
