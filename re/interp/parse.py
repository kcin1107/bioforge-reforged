"""Parser for BioForge script sources (re/out/scripts/*.scr) -> AST.

Report CLI:  re/.venv/bin/python -I re/interp/parse.py re/out/scripts

AST: File(blocks, tables, defs); Block(name, kind, body, tables, defid); File.defs: definition id -> owning Block;
Stmt(op, args, ...).  Expressions are tuples:
  ('num', n) ('str', s) ('name', s) ('var', lowername) ('const', n) ('local', i)
  ('mlocal', SELECTOR, i) ('un', op, a) ('bin', op, a, b) ('in', neg, a, list)
  ('call', FUNC, [args]) ('list', [items])
Statement ops: keyword (IF, WAIT, ...), plus LABEL, ASSIGN, EXPR (function call as a
statement), CASE, DEFAULT.  IF has .then/.els (lists of Stmt), SWITCH has .then (body
with flat CASE/DEFAULT/BREAK markers) and .idx (the switch's number in the file: one counter over every SWITCH line of the file,
as the engine's switch table numbers them, FUN_10c0_01cc).
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SCRIPT_DIR = os.path.join(ROOT, 'game', 'app', 'Bioforge', 'SCRIPT')
TOKENS = os.path.join(ROOT, 're', 'out', 'script_tokens.txt')


def read_lines(path):
    with open(path, encoding='latin-1') as fh:
        return fh.read().split('\n')


def load_tokens():
    """STATEMENTS {name: token byte}, FUNCTIONS set (from script_tokens.txt)."""
    stmts, funcs, sect = {}, set(), None
    for line in read_lines(TOKENS):
        if line.startswith('['):
            sect = line[1:].split()[0].split('@')[0]
        elif '\t' in line and sect in ('STATEMENTS', 'FUNCTIONS'):
            tok, name = line.split('\t', 1)
            if name:
                (stmts.__setitem__(name, tok) if sect == 'STATEMENTS' else funcs.add(name))
    return stmts, funcs


STATEMENTS, FUNCTIONS = load_tokens()
# raw statement-token bytes left in the decoded text: 'I' -> IF, 'J' -> JUMP, '\x1a' -> STOPSOUND ...
TOKEN_BYTE = {(v if len(v) == 1 else chr(int(v, 16))): k for k, v in STATEMENTS.items()}
RESERVED = {'AND', 'OR', 'THEN', 'IN', 'NOTIN', 'ELSE'}
CMP = {'=', '==', '!=', '<', '>', '<=', '>=', '=<', '=>'}
ASSIGN_OPS = {'=', '+=', '-=', '*=', '/=', '++', '--'}
# statements whose bare-name arguments are never function calls (e.g. MOTION FIRE, a motion name)
NAMES_ONLY = {'MOTION'}


class Defs:
    """Globals (VARS.DEF) and constants (DEFINES.DEF), keyed by lower-cased name."""

    def __init__(self):
        self.consts, self.vars, self.collisions = {}, {}, []
        for line in read_lines(os.path.join(SCRIPT_DIR, 'DEFINES.DEF')):
            m = re.match(r'\s*(_\w+)\s+(-?\d+)', line)
            if m:
                self.consts[m.group(1).lower()] = int(m.group(2))
        for line in read_lines(os.path.join(SCRIPT_DIR, 'VARS.DEF')):
            m = re.match(r'\s*(_\w+)\s*=\s*(\S+)', line)
            if m:
                k, v = m.group(1).lower(), m.group(2)
                self.vars[k] = int(v) if re.fullmatch(r'-?\d+', v) else self.consts.get(v.lower(), 0)
        self.collisions = sorted(set(self.consts) & set(self.vars))


class Stmt:
    def __init__(self, op, args=(), line=0, ts=None, **kw):
        self.op, self.args, self.line, self.ts = op, list(args), line, ts
        self.then = self.els = self.defid = self.idx = self.col = None     # col: decoded source column of the first token
        self.__dict__.update(kw)

    def __repr__(self):
        return f'Stmt({self.op} {self.args}@{self.line})'


class Block:
    def __init__(self, name, kind, line, defid):
        self.name, self.kind, self.line, self.defid = name, kind, line, defid
        self.body, self.tables, self.file = [], [], None


class File:
    def __init__(self, path):
        self.path, self.name = path, os.path.basename(path)
        self.blocks, self.tables, self.defs, self.failures = [], [], {}, []
        self._pos = None

    @property
    def scp(self):
        """The tokenized source (game SCRIPT/<NAME>.SCP) this decoded file comes from, or None."""
        p = os.path.join(SCRIPT_DIR, os.path.splitext(self.name)[0].upper() + '.SCP')
        return p if os.path.exists(p) else None

    def positions(self):
        """[(byte offset in the original .SCP, Stmt, Block)] of every statement in source order (cached). The offset is the
        start of the statement's first token, which is where the engine's script cursor (a text position, `pc`/`pc0` of
        a saved process, see savegame.Proc) sits. Needs the raw .SCP: the decoded text has different column widths, so the
        decoded column of each statement is mapped back through script.detokenize's token-boundary map."""
        if self._pos is None:
            sys.path.insert(0, os.path.join(ROOT, 're', 'formats'))
            import script
            raw = open(self.scp, 'rb').read()
            cols = {}
            script.detokenize(raw, script.load_symbols(SCRIPT_DIR), cols=cols)
            starts = [0]
            for ln in raw.split(b'\n')[:-1]:
                starts.append(starts[-1] + len(ln) + 1)
            out = []
            for b in self.blocks:
                for st in walk(b.body):
                    pairs = cols.get(st.line)
                    if not pairs or st.col is None:
                        continue
                    r, d = next(((r, d) for r, d in pairs if d == st.col), None) or max(((r, d) for r, d in pairs if d <= st.col),
                                                                                       default=(st.col, st.col))
                    out.append((starts[st.line - 1] + r + st.col - d, st, b))
            out.sort(key=lambda x: x[0])
            self._pos = out
        return self._pos

    def statements_from(self, offset):
        """Statements (Stmt, Block) from the first one that starts at or after raw .SCP byte `offset`, in source order."""
        pos = self.positions()
        lo, hi = 0, len(pos)
        while lo < hi:
            mid = (lo + hi) // 2
            if pos[mid][0] < offset:
                lo = mid + 1
            else:
                hi = mid
        return [(st, b) for _, st, b in pos[lo:]]


class ParseError(Exception):
    pass


# ---------------------------------------------------------------- lexing

TOKRE = re.compile(r'''\s*(?:
    (?P<str>"[^"]*") |
    (?P<mloc>\w+\.~\d) |
    (?P<word>~\d|\w+) |
    (?P<op>!IN\b|\+\+|--|\+=|-=|\*=|/=|==|!=|<=|>=|=<|=>|&&|\|\||.)
)''', re.X | re.S)


class Tok(tuple):
    """(kind, value, space_before) that also knows its column (.pos) in the decoded source line."""
    pos = 0


def _tok(k, v, sp, pos):
    t = Tok((k, v, sp))
    t.pos = pos
    return t


def tokenise(text, base=0):
    """-> list of (kind, value, space_before); kinds: num str ident op. `base` = column of text[0] in the source line
    (the Tok.pos of each token is base + its offset)."""
    out, pos = [], 0
    while pos < len(text):
        m = TOKRE.match(text, pos)
        if not m:
            break
        sp = m.start(m.lastgroup) > pos
        at = base + m.start(m.lastgroup)
        pos = m.end()
        v = m.group(m.lastgroup)
        k = m.lastgroup
        if k == 'str':
            out.append(_tok('str', v[1:-1], sp, at))
        elif k == 'word' and v.isdigit():
            out.append(_tok('num', int(v), sp, at))
        elif k in ('word', 'mloc'):
            out.append(_tok('ident', v, sp, at))
        elif v == '!IN':
            out.append(_tok('ident', 'NOTIN', sp, at))
        else:
            out.append(_tok('op', v, sp, at))
    return out


class Line:
    def __init__(self, no, text, defid, col0=0):
        self.no, self.text, self.defid, self.col0 = no, text, defid, col0     # col0 = column of text[0] in the source line


def logical_lines(src):
    """Strip comments, join multi-line strings, number definition sites (see NOTES: each
    `[`, each `{` followed by a name, each `:` not followed by a digit).
    -> (lines, total_defs)"""
    lines, ndef, pend, pno = [], 0, None, 0
    for no, raw in enumerate(src.split('\n'), 1):
        if pend is not None:
            raw, no = pend + '\n' + raw, pno
        # scan for comment start outside strings
        instr, cut = False, len(raw)
        for i, ch in enumerate(raw):
            if ch == '"':
                instr = not instr
            elif ch == '/' and not instr and raw.startswith('//', i):
                cut = i
                break
        if instr:                       # unterminated string: continues on the next line
            pend, pno = raw, no
            continue
        pend = None
        text = raw[:cut].rstrip().rstrip(';').rstrip()
        if not text.strip():
            continue
        bare = re.sub(r'"[^"]*"', '""', text)
        n = bare.count('[') + len(re.findall(r'\{\s*(?=[A-Za-z_])', bare)) + len(re.findall(r':(?!\d)', bare))
        lines.append(Line(no, text.strip(), ndef if n else None, len(text) - len(text.lstrip())))
        ndef += n
    return lines, ndef


# ---------------------------------------------------------------- expressions

class Expr:
    def __init__(self, toks, defs, calls=True):
        self.t, self.p, self.defs, self.sym, self.calls = toks, 0, defs, 0, calls

    def peek(self, k=0):
        return self.t[self.p + k] if self.p + k < len(self.t) else (None, None, False)

    def is_op(self, *ops, k=0):
        t = self.peek(k)
        return t[0] == 'op' and t[1] in ops

    def is_word(self, *ws, k=0):
        t = self.peek(k)
        return t[0] == 'ident' and t[1].upper() in ws

    def startable(self):
        k, v, sp = self.peek()
        if k in ('num', 'str'):
            return True
        if k == 'ident':
            return v.upper() not in RESERVED
        if k == 'op' and v == '(':
            return True
        if k == 'op' and v in ('+', '-'):    # sign glued to the next token, separated from the previous
            n = self.peek(1)
            return sp and not n[2] and (n[0] in ('num', 'ident') or n[1] == '(')
        return False

    def full(self):                       # or-level expression
        a = self.and_()
        while self.is_word('OR') or self.is_op('||'):
            self.p += 1
            a = ('bin', 'OR', a, self.and_())
        return a

    def and_(self):
        a = self.cmp()
        while self.is_word('AND') or self.is_op('&&'):
            self.p += 1
            a = ('bin', 'AND', a, self.cmp())
        return a

    def cmp(self):
        a = self.add()
        while True:
            if self.is_op(*CMP):
                op = self.peek()[1]
                self.p += 1
                a = ('bin', {'=': '==', '=<': '<=', '=>': '>='}.get(op, op), a, self.add())
            elif self.is_word('IN', 'NOTIN'):
                neg = self.peek()[1].upper() == 'NOTIN'
                self.p += 1
                a = ('in', neg, a, self.in_list())
            else:
                return a

    def in_list(self):
        items = [self.add()]
        if items[0][0] == 'list':
            return items[0]
        while self.is_op(','):
            self.p += 1
            items.append(self.add())
        return ('list', items)

    def binary_ok(self):
        if not self.sym:
            return True
        return self.peek()[2] == self.peek(1)[2]    # `a - b` / `a-b` binary, `a -b` = two args

    def add(self):
        a = self.mul()
        while self.is_op('+', '-') and self.binary_ok():
            op = self.peek()[1]
            self.p += 1
            a = ('bin', op, a, self.mul())
        return a

    def mul(self):
        a = self.unary()
        while self.is_op('*', '/', '%'):
            op = self.peek()[1]
            self.p += 1
            a = ('bin', op, a, self.unary())
        return a

    def unary(self):
        if self.is_op('-', '+'):
            op = self.peek()[1]
            self.p += 1
            a = self.unary()
            return a if op == '+' else (('num', -a[1]) if a[0] == 'num' else ('un', '-', a))
        return self.atom()

    def group_items(self):
        """After '(' : items separated by optional commas, up to ')' (a missing ')' is tolerated)."""
        self.p += 1
        items = []
        self.sym += 1
        while self.peek()[0] is not None and not self.is_op(')'):
            if self.is_op(','):
                self.p += 1
                continue
            items.append(self.full())
        self.sym -= 1
        if self.is_op(')'):
            self.p += 1
        return items

    def arg_seq(self):
        """Space/comma separated arguments (no parentheses) while an argument can start."""
        items = []
        self.sym += 1
        while True:
            if items and self.is_op(',') and self.p + 1 < len(self.t):
                self.p += 1
            if not self.startable():
                break
            items.append(self.add())
        self.sym -= 1
        return items

    def atom(self):
        k, v, sp = self.peek()
        if k is None:
            raise ParseError('unexpected end of expression')
        self.p += 1
        if k == 'num':
            return ('num', v)
        if k == 'str':
            return ('str', v)
        if k == 'op' and v == '(':
            self.p -= 1
            items = self.group_items()
            return items[0] if len(items) == 1 else ('list', items)
        if k == 'ident':
            return self.ident(v)
        raise ParseError(f'unexpected {v!r}')

    def ident(self, v):
        if '.~' in v:
            sel, i = v.split('.~')
            return ('mlocal', sel.upper(), int(i))
        if v[0] == '~':
            return ('local', int(v[1:]))
        up = v.upper()
        if self.calls and up in FUNCTIONS:
            if self.is_op('('):
                return ('call', up, self.group_items())
            return ('call', up, self.arg_seq())
        lo = v.lower()
        if v[0] == '_':
            if lo in self.defs.consts:
                return ('const', self.defs.consts[lo])
            if lo in self.defs.vars:
                return ('var', lo)
        return ('name', v)

    def args(self):
        """Statement arguments: arg_seq; a single parenthesised group is unpacked."""
        a = self.arg_seq()
        if len(a) == 1 and a[0][0] == 'list':
            a = a[0][1]
        if self.p < len(self.t) and not (self.p == len(self.t) - 1 and self.is_op(')')):
            raise ParseError(f'unexpected {self.peek()[1]!r} in arguments')
        return a


# ---------------------------------------------------------------- statements

class Parser:
    def __init__(self, path, defs):
        self.defs = defs
        self.file = File(path)
        with open(path, encoding='latin-1') as fh:
            src = fh.read()
        self.lines, ndef = logical_lines(src)
        self.i, self.block, self.nswitch = 0, None, 0
        self.claimed = 0

    def fail(self, line, msg):
        self.file.failures.append((self.file.name, line.no, line.text, msg))

    def claim(self, line):
        if line.defid is not None:
            self.claimed += 1
            self.file.defs[line.defid] = self.block      # definition id -> owning block (for JUMP #id)
        return line.defid

    def parse(self):
        L = self.lines
        while self.i < len(L):
            line = L[self.i]
            m = re.match(r'([{\[])\s*([^\s].*)$', line.text)
            if m and m.group(2) not in ('{', '['):
                self.parse_block(line, m)
            elif line.text.startswith('<'):
                self.i += 1
                self.table(line, self.file.tables)
            else:
                self.i += 1
                self.fail(line, 'outside_block')
        return self.file

    def parse_block(self, line, m):
        name = m.group(2).split()[0]
        b = Block(name, 'timeline' if m.group(1) == '[' else 'routine', line.no, line.defid)
        b.file = self.file
        self.file.blocks.append(b)
        self.block = b                    # nswitch runs on through the file: the engine numbers switches per file (FUN_10c0_01cc)
        self.claim(line)
        self.i += 1
        b.body = self.stmts(top=True)
        self.block = None

    def table(self, line, dest):
        inner = line.text.strip().lstrip('<').rstrip().rstrip('>').strip()
        m = re.match(r'(\S+)\s*=\s*(.*)$', inner, re.S)
        name, rest = (m.group(1), m.group(2)) if m else (None, inner)
        vals = [int(x) if re.fullmatch(r'-?\d+', x) else (x[1:-1] if x[0] == '"' else x)
                for x in re.findall(r'"[^"]*"|[^\s,()]+', rest)]
        dest.append((name, vals, line.no))

    def stmts(self, top=False):
        """Statements until a closing `}`/`]` (consumed) -- or, at block level, the next block header."""
        out, L = [], self.lines
        while self.i < len(L):
            line = L[self.i]
            t = line.text
            if t in ('}', ']'):
                self.i += 1
                return out
            if top and re.match(r'[{\[]\s*\S', t) and not re.match(r'[{\[]\s*[{\[]', t):
                return out
            if t.startswith('<'):
                self.i += 1
                self.table(line, (self.block or self.file).tables)
                continue
            start = self.i
            try:
                s = self.stmt()
                out.append(s)
            except ParseError as e:
                self.fail(line, str(e))
                self.i = max(self.i, start + 1)
        return out

    def stmt(self):
        line = self.lines[self.i]
        self.i += 1
        m = re.match(r'(\d+):(\d+)(?:\s+(.*))?$', line.text, re.S)
        ts, base = None, 0
        text = line.text
        if m:
            ts, text, base = int(m.group(1)) * 30 + int(m.group(2)), m.group(3), m.start(3)
            if not text:                      # timestamp alone: applies to the next line's statement
                s = self.stmt()
                s.ts = ts if s.ts is None else s.ts
                return s
        return self.stmt_toks(tokenise(text, base), line, ts)

    def body(self):
        """IF/ELSE body on following lines: `{ ... }` or one statement."""
        if self.i >= len(self.lines):
            raise ParseError('missing body')
        if self.lines[self.i].text == '{':
            self.i += 1
            return self.stmts()
        if self.lines[self.i].text in ('}', ']'):
            raise ParseError('missing body')
        return [self.stmt()]

    def stmt_toks(self, toks, line, ts):
        if not toks:
            raise ParseError('empty statement')
        k, v, _ = toks[0]
        up = v.upper() if k == 'ident' else None
        mk = lambda op, args=(), **kw: Stmt(op, args, line.no, ts, col=line.col0 + toks[0].pos, **kw)
        if k == 'op' and v == ':':               # label (`:NAME` or `: NAME`)
            if len(toks) != 2 or toks[1][0] != 'ident':
                raise ParseError('bad label')
            return mk('LABEL', [toks[1][1]], defid=self.claim(line))
        if k == 'op' and v == '{' and len(toks) == 1:      # bare `{ ... }` (e.g. CASE body)
            return mk('BLOCK', [], then=self.stmts())
        toks = self.fix_else(toks)                  # raw token byte as statement keyword
        k, v, _ = toks[0]
        up = v.upper() if k == 'ident' else None
        if up == 'IF':
            return self.if_(toks, line, ts)
        if up == 'ELSE':
            raise ParseError('ELSE without IF')
        if up == 'SWITCH':
            e = Expr(toks[1:], self.defs)
            cond = e.full()
            idx = self.nswitch
            self.nswitch += 1
            if self.i >= len(self.lines) or self.lines[self.i].text != '{':
                raise ParseError('SWITCH without {')
            self.i += 1
            return mk('SWITCH', [cond], then=self.stmts(), idx=idx)
        if up in ('CASE', 'DEFAULT'):
            e = Expr(toks[1:], self.defs)
            args = [e.full()] if up == 'CASE' else []
            claimed = self.claim(line) if any(t[:2] == ('op', ':') for t in toks) else None
            if e.is_op(':'):
                e.p += 1
            s = mk(up, args, defid=claimed)
            if e.p < len(e.t):                    # body on the same line
                return mk('BLOCK', [], then=[s, self.stmt_toks(e.t[e.p:], line, None)])
            return s
        if up in STATEMENTS:
            e = Expr(toks[1:], self.defs, calls=up not in NAMES_ONLY)
            if up == 'JUMP' and e.is_op('#'):      # JUMP #<definition id>
                n = e.peek(1)
                if n[0] != 'num':
                    raise ParseError('bad JUMP #id')
                return mk('JUMP', [('defid', n[1])])
            if up == 'LOCALVAR' and len(toks) > 3 and toks[2][:2] == ('op', '='):
                # GUESS: `LOCALVAR ~0 = 0` declares and initialises
                return mk('LOCALVAR', [e.ident(toks[1][1])], init=Expr(toks[3:], self.defs).full())
            a = e.arg_seq()
            if len(a) == 1 and a[0][0] == 'list':
                a = a[0][1]
            if e.is_op('=') and up == 'SETFLAG':    # GUESS: `SETFLAG (v, bit) = 1` -> trailing value kept as extra arg
                e.p += 1
                a.append(e.full())
            if e.p < len(e.t) and not (e.p == len(e.t) - 1 and e.is_op(')')):
                raise ParseError(f'unexpected {e.peek()[1]!r} in arguments')
            return mk(up, a)
        if up in FUNCTIONS:
            e = Expr(toks, self.defs)
            call = e.atom()
            if e.p < len(e.t) and not (e.p == len(e.t) - 1 and e.is_op(')')):
                raise ParseError(f'unexpected {e.peek()[1]!r} after call')
            return mk('EXPR', [call])
        if k == 'ident' and (v[0] == '~' or '.~' in v or v[0] == '_'):
            e = Expr(toks, self.defs)
            tgt = e.ident(v)
            e.p = 1
            op = e.peek()[1] if e.peek()[0] == 'op' else None
            if tgt[0] in ('var', 'local', 'mlocal', 'name') and op in ASSIGN_OPS:
                e.p += 1
                if op not in ('++', '--') and e.p >= len(e.t):    # value continues on the next line
                    e = Expr(tokenise(self.lines[self.i].text), self.defs)
                    self.i += 1
                    e.p = 0
                val = ('num', 1) if op in ('++', '--') else e.full()
                if e.p < len(e.t):
                    raise ParseError(f'unexpected {e.peek()[1]!r} after assignment')
                return mk('ASSIGN', [tgt, op, val])
        raise ParseError('unrecognised statement')

    def if_(self, toks, line, ts):
        try:
            j = next(n for n, t in enumerate(toks) if t[0] == 'ident' and t[1].upper() == 'THEN')
        except StopIteration:
            j = len(toks)
        e = Expr(toks[1:j], self.defs)
        cond = e.full()
        if e.p < len(e.t) and not all(t[:2] == ('op', ')') for t in e.t[e.p:]):
            raise ParseError(f'unexpected {e.peek()[1]!r} in condition')
        rest = [t for t in toks[j + 1:]]
        while rest and rest[-1][:2] == ('op', ')') and sum(t[1] == '(' for t in rest) < sum(t[1] == ')' for t in rest):
            rest.pop()
        s = Stmt('IF', [cond], line.no, ts, col=line.col0 + toks[0].pos)
        s.braced = False                          # THEN is a { } block (vm.Code: a dangling ELSE after a braceless IF chain)
        if rest == [('op', '{', rest[0][2])] if rest else False:
            s.then, s.braced = self.stmts(), True
        elif rest:
            s.then = [self.stmt_toks(rest, line, None)]
        elif self.i < len(self.lines) and re.match(r'ELSE\b', self.lines[self.i].text, re.I):
            s.then = []                           # empty THEN body directly followed by ELSE
        else:
            s.braced = self.lines[self.i].text == '{' if self.i < len(self.lines) else False
            s.then = self.body()
        if self.i < len(self.lines) and re.match(r'ELSE\b', self.lines[self.i].text, re.I):
            eline = self.lines[self.i]
            self.i += 1
            etoks = tokenise(eline.text)[1:]
            etoks = self.fix_else(etoks)
            s.els = [self.stmt_toks(etoks, eline, None)] if etoks else self.body()
        return s

    def fix_else(self, toks):
        """Defensive: raw statement-token bytes after ELSE (`ELSE I (..)`, `ELSE J X`, `ELSE !`)."""
        if toks and toks[0][0] in ('ident', 'op') and toks[0][1] in TOKEN_BYTE and len(toks) > 1 \
                and (toks[0][0] == 'ident' or toks[0][1] == '!' or ord(toks[0][1]) < 32):
            return [_tok('ident', TOKEN_BYTE[toks[0][1]], toks[0][2], toks[0].pos)] + toks[1:]
        return toks


def parse_file(path, defs=None):
    p = Parser(path, defs or Defs())
    f = p.parse()
    with open(path, encoding='latin-1') as fh:
        total = logical_lines(fh.read())[1]
    f.def_count, f.def_claimed = total, p.claimed
    return f


def walk(stmts):
    for s in stmts:
        yield s
        for sub in (s.then, s.els):
            if sub:
                yield from walk(sub)


IGNORABLE = {'outside_block': 'text outside any block (comment continuation lines without //)'}


def main(argv):
    d = argv[1] if len(argv) > 1 else os.path.join(ROOT, 're', 'out', 'scripts')
    defs = Defs()
    files = [parse_file(os.path.join(d, n), defs) for n in sorted(os.listdir(d)) if n.lower().endswith('.scr')]
    nb = sum(len(f.blocks) for f in files)
    nt = sum(b.kind == 'timeline' for f in files for b in f.blocks)
    ns = sum(1 for f in files for b in f.blocks for _ in walk(b.body))
    ntab = sum(len(f.tables) + sum(len(b.tables) for b in f.blocks) for f in files)
    fails = [x for f in files for x in f.failures]
    real = [x for x in fails if x[3] not in IGNORABLE]
    print(f'files: {len(files)}  blocks: {nb} (timelines {nt})  statements parsed: {ns}  data-table lines: {ntab}')
    print(f'constants: {len(defs.consts)}  globals: {len(defs.vars)}  name collisions (const wins): {defs.collisions or "none"}')
    unclaimed = [(f.name, f.def_count, f.def_claimed) for f in files if f.def_count != f.def_claimed]
    print(f'files where definition sites != claimed (blocks/labels/CASE:) : {unclaimed or "none"}')
    print(f'ignorable lines: {len(fails) - len(real)}')
    for cat, desc in IGNORABLE.items():
        print(f'  {cat}: {sum(1 for x in fails if x[3] == cat)}  ({desc})')
    print(f'failed lines: {len(real)}')
    for f, no, text, msg in real[:20]:
        print(f'  {f}:{no}: {text[:100]!r}  [{msg}]')
    return 1 if real else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
