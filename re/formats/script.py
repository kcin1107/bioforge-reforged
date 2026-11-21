"""BioForge script files (SCRIPT/*.SCP): detokenizer + block/call index.

SCP files are CRLF latin-1 text with tab indentation and // comments. The game's
tool replaced identifiers by tokens, padded with spaces to the original length:
  prefix char + 2 bytes (both >= 0x80); id = ((b0 & 0x7f) << 6) | (b1 & 0x3f)
  ^ variable  -> VARS.DEF entry (file order, 0-based, 1000)
  $ define    -> DEFINES.DEF entry (0-based, 255)
  ` sound     -> SOUNDS.DEF then SOUNDS2.DEF entries (0-based, 1564)
  @ function  -> value in [FUNCTIONS] of re/out/script_tokens.txt (CALL=29, SOUND=6 ...)
  ~ local register 0..9 (rendered ~0..~9; meaning is a guess)
Statement keywords: a single token byte (letter, control byte, or >= 0x80, see
[STATEMENTS]) as first non-blank byte of a line, followed by space/EOL, e.g.
I=IF M=MOTION W=WAIT 0x9c=FACE. Letters are only keywords in statement position.
A line may start with a MM:SS timestamp (timeline blocks) before the keyword.
  # label ref   -> '#' + 2 bytes: id indexes the per-file list of definitions in order of
                   appearance, counted like the engine compiler (FUN_1118_07dc) over the whole
                   file, skipping "strings" and // comments: every '[', every '{' followed by
                   (blanks and) an identifier char, every ':' not followed by a digit (CASE colons count too, unnamed, rendered #<id>;
                   ': NAME' with a blank is named by the identifier after the blank)
  . member var  -> '.' + 4 bytes: selector id (CURITEM/CURFIG/PLAYER/ENEMY, 1..4: FUN_10c0_24e1 reads 1 from the context's
                   +0xe7f, 2 from +0xe7b) + local index; rendered CURFIG.~6
  BREAK <n>     -> BREAK followed by 2 unprefixed high bytes ((b0 & 0x3f) << 6 | (b1 & 0x3f)): the innermost SWITCH's number,
                   counted through the file (FUN_10c0_01cc); blank in an inline `THEN BREAK`, which the compiler never numbered
Blocks: '{ NAME ... }' and timelines '[ NAME ... ]' (headers at column 0).
Quoted strings and // comments are left untouched.
Usage: script.py SCRIPT_DIR OUT_DIR  (writes <name>.scr and index.md)
"""
import sys, os, re, glob, collections

TOKENS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'out', 'script_tokens.txt')
EVENTS = ['HIT_WALL', 'ENTER_COMBAT', 'LEAVE_COMBAT', 'LOG_ADDED', 'HIT', 'LOAD', 'UNLOAD', 'AI', 'USE',
          'DROP', 'TAKE', 'DEATH', 'HIGHLIGHT', 'RELEASED', 'REPEAT', 'BUTTON', 'STIMULUS', 'WOUNDS',
          'FIRE', 'HIDE', 'UNHIDE']

def read_def(path):
    out = []
    for ln in open(path, 'rb').read().decode('latin1').splitlines():
        m = re.match(r'\s*([A-Za-z_]\w*)', ln)
        if m and not ln.lstrip().startswith(('//', '{', '}')): out.append(m.group(1))
    return out

def tokbyte(s):
    return int(s, 16) if s.startswith('0x') and len(s) > 1 else ord(s)

def load_symbols(script_dir):
    d = lambda n: read_def(os.path.join(script_dir, n))
    syms = {'^': d('VARS.DEF'), '$': d('DEFINES.DEF'), '`': d('SOUNDS.DEF') + d('SOUNDS2.DEF'),
            '@': {}, 'stmt': {}}
    sec = None
    for ln in open(TOKENS, encoding='latin1').read().split('\n'):
        if ln.startswith('['): sec = ln[1:].split()[0].split(']')[0]; continue
        p = ln.split('\t')
        if len(p) < 2 or not p[1] or not p[0]: continue
        if sec == 'STATEMENTS': syms['stmt'][tokbyte(p[0])] = p[1]
        elif sec == 'FUNCTIONS': syms['@'][tokbyte(p[0])] = p[1]
    return syms

def detokenize(data, syms, stats=None, name='', cols=None):
    """data: bytes of an SCP file -> str (LF). stats: Counter-like dict updated in place.
    cols: optional dict, filled with {line number: [(raw column, decoded column)]} at every token boundary (statement starts
    included), the raw -> decoded column map used to place saved script positions (pc) in the decoded source."""
    st = stats if stats is not None else collections.Counter()
    st.setdefault('unresolved', [])
    out = []
    lines = [x.rstrip(b'\r') for x in data.split(b'\n')]
    defs = []   # '#' targets, port of the engine compiler's definition counter (FUN_1118_07dc)
    for m in re.finditer(rb'"[^"]*"|//[^\n]*|\[[ \t]*(\w*)|\{[ \t]*(\w+)|(?<!\d):(?!\d)[ \t]*(\w*)', data):
        if m.group(0)[:1] not in b'"/': defs.append((m.group(1) or m.group(2) or m.group(3) or b'#%d' % len(defs)).decode('latin1'))
    for ln, raw in enumerate(lines, 1):
        def bad(kind, i):
            st['bad_' + kind] += 1
            st['unresolved'].append((kind, '%s:%d' % (name, ln), raw[i:i + 3].hex()))
        res, i, n = [], 0, len(raw)
        lc = cols.setdefault(ln, []) if cols is not None else None
        mark = lambda k: lc.append((k, sum(map(len, res)))) if lc is not None else None
        def stmt(j):
            """statement token at raw[j] -> advance i past token + padding"""
            nonlocal i
            if j < n and raw[j] in syms['stmt'] and (j + 1 == n or raw[j + 1] == 0x20):
                res.append(syms['stmt'][raw[j]]); st['stmt'] += 1
                i = j + 1
                if i < n and raw[i] == 0x20:
                    res.append(' ')
                    while i < n and raw[i] == 0x20: i += 1
                return True
            return False
        j = 0
        while j < n and raw[j] in b' \t': j += 1
        res.append(raw[:j].decode('latin1')); i = j
        m = re.match(rb'\d+:\d+(?=[ \t])', raw[j:])
        if m:   # timeline timestamp
            k = j + m.end(); res.append(m.group().decode()); st['timestamp'] += 1
            while k < n and raw[k] in b' \t': k += 1
            res.append(' '); i = j = k
        mark(j)
        if not stmt(j) and j < n and raw[j] >= 0x80 and raw[j] not in b'^$`@~': bad('stmt', j)
        instr = False
        while i < n:
            mark(i)
            c = raw[i]
            if not instr and c == 0x2f and raw[i:i + 2] == b'//':
                res.append(raw[i:].decode('latin1')); break
            if c == 0x22: instr = not instr
            if not instr and chr(c) in '^$`@~' and i + 2 < n + 0 and raw[i + 1] >= 0x80 and raw[i + 2] >= 0x80:
                k = chr(c)
                tid = ((raw[i + 1] & 0x7f) << 6) | (raw[i + 2] & 0x3f)
                if k == '~': nm = '~%d' % tid if tid < 10 else None
                elif k == '@': nm = syms['@'].get(tid)
                else: nm = syms[k][tid] if tid < len(syms[k]) else None
                if nm is None: bad(k, i); res.append(raw[i:i + 3].decode('latin1')); i += 3; continue
                st['tok' + k] += 1
                res.append(nm); i += 3
                if i < n and raw[i] == 0x20:
                    res.append(' ')
                    while i < n and raw[i] == 0x20: i += 1
                continue
            if not instr and c == 0x2e and i + 4 < n and min(raw[i + 1:i + 5]) >= 0x80:
                sel, loc = [((raw[q] & 0x7f) << 6) | (raw[q + 1] & 0x3f) for q in (i + 1, i + 3)]
                if 0 < sel < 5 and loc < 10:
                    res.append('%s.~%d' % (['', 'CURITEM', 'CURFIG', 'PLAYER', 'ENEMY'][sel], loc)); st['tok.'] += 1; i += 5; continue
                bad('.', i)
            lab = c == 0x23 and i + 2 < n and min(raw[i + 1:i + 3]) >= 0x80
            brk = c >= 0x80 and i + 1 < n and raw[i + 1] >= 0x80 and res[-2:] == ['BREAK', ' ']
            if not instr and (lab or brk):
                o = i + lab; tid = ((raw[o] & 0x7f) << 6) | (raw[o + 1] & 0x3f)
                if brk: res.append(str(tid)); st['break'] += 1
                elif tid < len(defs): res.append(defs[tid]); st['tok#'] += 1
                else: bad('#', i); res.append(raw[i:i + 3].decode('latin1'))
                i = o + 2; continue
            res.append(chr(c)); i += 1
            if not instr and c == 0x20 and raw[i - 5:i] == b'THEN ':   # inline statement after THEN
                while i < n and raw[i] == 0x20: res.append(' '); i += 1
                mark(i)
                stmt(i)
        out.append(''.join(res).rstrip(' '))
    return '\n'.join(out)

def index_scr(text, name):
    """-> blocks [(name, line, kind)], calls [(block, target, line)]"""
    blocks, calls, cur = [], [], None
    for ln, s in enumerate(text.split('\n'), 1):
        m = re.match(r'([{\[])\s+(\w+)', s)
        if m: cur = m.group(2); blocks.append((cur, ln, 'timeline' if m.group(1) == '[' else 'block'))
        for m in re.finditer(r'\bCALL\s*\(?\s*(\w+)', re.sub(r'//.*', '', s)): calls.append((cur, m.group(1), ln))
    return blocks, calls

def main(sd, od):
    syms = load_symbols(sd)
    print('symbols: vars %d defines %d sounds %d functions %d statements %d' % (
        len(syms['^']), len(syms['$']), len(syms['`']), len(syms['@']), len(syms['stmt'])))
    os.makedirs(od, exist_ok=True)
    st = collections.Counter(); nlines = 0
    files = sorted(glob.glob(os.path.join(sd, '*.SCP')) + glob.glob(os.path.join(sd, '*.scp')))
    info = {}
    for f in files:
        base = os.path.splitext(os.path.basename(f))[0]
        txt = detokenize(open(f, 'rb').read(), syms, st, os.path.basename(f))
        nlines += txt.count('\n') + 1
        open(os.path.join(od, base + '.scr'), 'w', encoding='latin1', newline='\n').write(txt)
        info[base.upper()] = index_scr(txt, base)
    # index
    allblocks = collections.defaultdict(list)
    for b, (bl, _) in info.items():
        for n, ln, _ in bl: allblocks[n.upper()].append((b, ln))
    L = ['# BioForge script index', '']
    nb = sum(k == 'block' for v in info.values() for _, _, k in v[0]); nt = sum(k == 'timeline' for v in info.values() for _, _, k in v[0]); ne = sum(len(v[1]) for v in info.values())
    missing = sorted({(f, c, t, ln) for f, (_, cs) in info.items() for c, t, ln in cs if t.upper() not in allblocks})
    L += ['- files: %d' % len(info), '- blocks: %d, timelines: %d (%d unique names)' % (nb, nt, len(allblocks)),
          '- CALL edges: %d' % ne, '- CALL targets missing as blocks: %d' % len(missing), '']
    L += ['## Blocks per file', '']
    for b, (bl, _) in sorted(info.items()):
        L.append('### %s (%d)' % (b, len(bl)))
        L += ['- %s (line %d, %s)' % x for x in bl]; L.append('')
    L += ['## CALL cross-reference (caller -> targets)', '']
    for b, (_, cs) in sorted(info.items()):
        if not cs: continue
        L.append('### %s' % b)
        by = collections.OrderedDict()
        for c, t, ln in cs: by.setdefault(c, []).append('%s%s (L%d)' % (t, '' if t.upper() in allblocks else ' **MISSING**', ln))
        L += ['- %s: %s' % (c, ', '.join(v)) for c, v in by.items()]; L.append('')
    L += ['## Missing CALL targets', ''] + ['- %s:%d in %s calls %s' % (f, ln, c, t) for f, c, t, ln in missing] + ['']
    L += ['## Event handlers by suffix', '']
    ev = collections.defaultdict(list)
    for n, locs in allblocks.items():
        for suf in EVENTS:
            if n.endswith('_' + suf): ev[suf] += [(n, f, ln) for f, ln in locs]; break
    for suf in EVENTS:
        if suf in ev:
            L.append('### _%s (%d)' % (suf, len(ev[suf])))
            L += ['- %s (%s:%d)' % x for x in sorted(ev[suf])]; L.append('')
    L += ['## Levels', '']
    for f in sorted(glob.glob(os.path.join(sd, '*.LVL'))):
        txt = open(f, 'rb').read().decode('latin1')
        names = [x.strip() for x in txt.splitlines() if x.strip().lower().endswith('.scr')]
        L.append('### %s (%d scripts)' % (os.path.basename(f), len(names)))
        L += ['- %s%s' % (x, '' if x[:-4].upper() in info else ' (no SCP)') for x in names]; L.append('')
    open(os.path.join(od, 'index.md'), 'w').write('\n'.join(L))
    print('files %d lines %d' % (len(files), nlines))
    print('tokens replaced:', {k: st['tok' + k] for k in '^$`@~#.'}, 'statements', st['stmt'], 'BREAK ids', st['break'], 'timestamps', st['timestamp'], 'timelines', nt)
    bad = st['unresolved']
    pb = [x for x in bad if x[0] != 'stmt']
    print('unresolved prefixed tokens: %d; unknown statement bytes: %d' % (len(pb), len(bad) - len(pb)))
    for x in pb[:10]: print('  prefixed', x)
    for x in [x for x in bad if x[0] == 'stmt'][:10]: print('  stmt', x)
    print('blocks %d, timelines %d, CALL edges %d, missing %d, event handlers %s' % (
        nb, nt, ne, len(missing), {s: len(v) for s, v in ev.items()}))

if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
