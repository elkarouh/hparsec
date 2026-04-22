"""hek_tokenize.py — Custom AdaScript tokenizer.

Replaces Python's built-in tokenize module with a hand-written single-pass
lexer that handles AdaScript extensions (tick, dollar-vars, bash operators,
range operators) inline without sentinel preprocessing.

Public API (unchanged):
    Tokenizer(source)      — main class
    RichNL                 — newline+comment bundle
    TICK_TOKEN             — synthetic type constant
    DOLLAR_TOKEN           — synthetic type constant
    BASH_TEST_TOKEN        — synthetic type constant
    BASH_CMP_TOKEN         — synthetic type constant
    RANGE_TOKEN            — synthetic type constant
    RANGE_EXCL_TOKEN       — synthetic type constant
    tokenize_string(s)     — kept for compatibility (delegates to _lex)
    set_current_tokenizer  — context tracker
    get_multiline_brackets — context tracker
"""

import re
import tokenize as tkn  # for TokenInfo, tok_name, and token type constants only

# ---------------------------------------------------------------------------
# Synthetic token types (above Python's token range, which tops at ~69)
# ---------------------------------------------------------------------------
TICK_TOKEN       = 90   # Ada-style tick:  x'Image, arr[i]'First
DOLLAR_TOKEN     = 91   # Bash dollar var: $#, $@, $0, $N, $NAME
BASH_TEST_TOKEN  = 92   # Bash file test:  -e, -f, -d ...
BASH_CMP_TOKEN   = 93   # Bash file cmp:   -nt, -ot
RANGE_TOKEN      = 94   # Ada/Nim range:   lo .. hi
RANGE_EXCL_TOKEN = 95   # exclusive range: lo ..< hi

# ---------------------------------------------------------------------------
# Monkey-patch TokenInfo so existing code can compare tok == "string"
# ---------------------------------------------------------------------------
def _ti_eq(self, val):
    return val == self.string

def _ti_str(self):
    if self.exact_type == self.type:
        return f"Token({tkn.tok_name[self.type]!s}, {self.string!r})"
    return f"Token({tkn.tok_name[self.type]!s}, {self.string!r}, {tkn.tok_name[self.exact_type]})"

tkn.TokenInfo.__eq__ = _ti_eq
tkn.TokenInfo.__str__ = _ti_str

# ---------------------------------------------------------------------------
# Pipe utility (unchanged)
# ---------------------------------------------------------------------------
class Pipe:
    def __init__(self, function):
        self.function = function

    def __ror__(self, left):
        return self.function(left)

    def __call__(self, *args, **kwargs):
        return Pipe(lambda x: self.function(x, *args, **kwargs))

    __rrshift__ = __ror__

    def __mul__(self, other):
        return Pipe(lambda x: x >> self | other)


# ---------------------------------------------------------------------------
# RichNL (unchanged)
# ---------------------------------------------------------------------------
class RichNL:
    """A newline token enriched with any preceding comments."""
    string = ''

    def __init__(self, nl_token, comments=None, is_blank=False):
        self.nl_token = nl_token
        self.comments = comments if comments else []
        self.start = nl_token.start
        self.end = nl_token.end
        self.type = nl_token.type
        self.is_blank = is_blank

    def __repr__(self):
        if self.is_blank:
            return 'RichNL(blank)'
        return f'RichNL(comments={self.comments!r})'

    def to_lines(self):
        lines = []
        for kind, text, ind in self.comments:
            if kind == 'comment':
                lines.append(' ' * ind + text)
        if self.is_blank:
            lines.append('')
        return lines

    def to_py(self):
        return '\n'.join(self.to_lines())

    def inline_comment(self):
        for kind, text, ind in self.comments:
            if kind == 'comment':
                return '  ' + text
        return ''

    @classmethod
    def extract_from(cls, node):
        if isinstance(node, cls):
            return node
        if hasattr(node, 'nodes') and node.nodes and isinstance(node.nodes[0], cls):
            return node.nodes[0]
        return None


# ---------------------------------------------------------------------------
# Token type constants (re-exported from token module for convenience)
# ---------------------------------------------------------------------------
_NAME      = tkn.NAME
_NUMBER    = tkn.NUMBER
_STRING    = tkn.STRING
_NEWLINE   = tkn.NEWLINE
_NL        = tkn.NL
_INDENT    = tkn.INDENT
_DEDENT    = tkn.DEDENT
_COMMENT   = tkn.COMMENT
_OP        = tkn.OP
_ENDMARKER = tkn.ENDMARKER
_ENCODING  = tkn.ENCODING
_ERRORTOKEN = tkn.ERRORTOKEN

# ---------------------------------------------------------------------------
# Exact-type mapping for operators (mirrors Python's tokenize)
# ---------------------------------------------------------------------------
_EXACT = {
    '(':  tkn.LPAR,   ')':  tkn.RPAR,
    '[':  tkn.LSQB,   ']':  tkn.RSQB,
    '{':  tkn.LBRACE, '}':  tkn.RBRACE,
    ':':  tkn.COLON,  ',':  tkn.COMMA,
    ';':  tkn.SEMI,   '+':  tkn.PLUS,
    '-':  tkn.MINUS,  '*':  tkn.STAR,
    '/':  tkn.SLASH,  '|':  tkn.VBAR,
    '&':  tkn.AMPER,  '<':  tkn.LESS,
    '>':  tkn.GREATER,'=':  tkn.EQUAL,
    '.':  tkn.DOT,    '%':  tkn.PERCENT,
    '~':  tkn.TILDE,  '^':  tkn.CIRCUMFLEX,
    '@':  tkn.AT,     '!':  tkn.EXCLAMATION,
    '==': tkn.EQEQUAL,'!=': tkn.NOTEQUAL,
    '<=': tkn.LESSEQUAL,'>=':tkn.GREATEREQUAL,
    '<<': tkn.LEFTSHIFT,'>>':tkn.RIGHTSHIFT,
    '**': tkn.DOUBLESTAR,'//':tkn.DOUBLESLASH,
    '+=': tkn.PLUSEQUAL,'-=':tkn.MINEQUAL,
    '*=': tkn.STAREQUAL,'/=':tkn.SLASHEQUAL,
    '%=': tkn.PERCENTEQUAL,'&=':tkn.AMPEREQUAL,
    '|=': tkn.VBAREQUAL,'^=':tkn.CIRCUMFLEXEQUAL,
    '<<=':tkn.LEFTSHIFTEQUAL,'>>=':tkn.RIGHTSHIFTEQUAL,
    '**=':tkn.DOUBLESTAREQUAL,'//=':tkn.DOUBLESLASHEQUAL,
    '@=': tkn.ATEQUAL,'->': tkn.RARROW,
    '...':tkn.ELLIPSIS,':=':tkn.COLONEQUAL,
}

# Multi-char operators sorted longest-first for greedy matching
_MULTICHAR_OPS = sorted(_EXACT.keys(), key=lambda s: -len(s))
_MULTICHAR_OPS_RE = re.compile(
    '|'.join(re.escape(op) for op in _MULTICHAR_OPS if len(op) > 1)
    + r'|[()[\]{}:,;+\-*/%|&<>=.~^@!]'
)

# ---------------------------------------------------------------------------
# Bash file-test context keywords (token immediately before must be one of these)
# ---------------------------------------------------------------------------
_FILE_TEST_CONTEXT = frozenset(('if', 'elif', 'while', 'and', 'or', 'not'))
_FILE_TEST_FLAGS   = frozenset('efdLrwxscbpS')

# ---------------------------------------------------------------------------
# Tick-attribute detection patterns (applied on NAME tokens)
# ---------------------------------------------------------------------------
_TICK_CONTEXT = frozenset((
    _NAME, _NUMBER,           # x'Image, 42'T
    tkn.RPAR, tkn.RSQB,       # (e)'C, arr[i]'F
))

# ---------------------------------------------------------------------------
# Core lexer: _lex(source) -> generator of TokenInfo
#
# Emits tokens in the same order and format as tokenize.tokenize() but:
#   - Handles AdaScript extensions inline (no preprocessing)
#   - Emits synthetic token types directly
#   - No ENCODING token (not needed by Tokenizer)
# ---------------------------------------------------------------------------

# Regex fragments
_WS_RE        = re.compile(r'[ \t]+')
_NL_RE        = re.compile(r'\r?\n|\r')
_NAME_RE      = re.compile(r'[A-Za-z_]\w*')
_NUMBER_RE    = re.compile(
    r'0[xX][0-9a-fA-F]+[lL]?'        # hex
    r'|0[oO][0-7]+'                   # octal 0o
    r'|0[bB][01]+'                    # binary
    r'|(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?[jJ]?'  # decimal / float / complex
)
_COMMENT_RE   = re.compile(r'#[^\r\n]*')

# String prefixes
_STR_PREFIX_RE = re.compile(r'(?i)(f|b|r|u|fr|rf|br|rb)?(?=\"|\')')

# Operators
_OP_RE = re.compile(
    r'\.\.\<'                        # ..<  (exclusive range — must be FIRST)
    r'|\.\.\.'                       # ...  (ellipsis — before ..)
    r'|\.\.'                         # ..   (inclusive range)
    r'|<<=|>>=|\*\*=|//='            # 4-char compound ops
    r'|<<|>>|\*\*|//|->|:='          # 2-char ops
    r'|[+\-*/%|&^]=|[<>!=]='         # augmented assignment / comparison
    r'|[(){}\[\]:,;.+\-*/%|&<>=~^@!]'  # single-char ops
)


def _make_tok(typ, string, start, end, line):
    """Create a TokenInfo, setting exact_type correctly."""
    exact = _EXACT.get(string, typ)
    return tkn.TokenInfo(exact, string, start, end, line)


def _read_string(src, pos, line_no, col, lines):
    """Read a string literal starting at src[pos]. Return (string, new_pos, lines_consumed)."""
    start_col = col
    i = pos
    # Detect prefix
    prefix_match = _STR_PREFIX_RE.match(src, i)
    prefix = ''
    if prefix_match:
        prefix = prefix_match.group(0)
        i += len(prefix)

    if src[i:i+3] in ('"""', "'''"):
        delim = src[i:i+3]
    elif src[i] in ('"', "'"):
        delim = src[i]
    else:
        return None, pos, 0

    i += len(delim)
    result = [prefix + delim]
    extra_lines = 0

    while i < len(src):
        c = src[i]
        if c == '\\':
            if i + 1 < len(src):
                nc = src[i + 1]
                result.append(src[i:i+2])
                if nc == '\n':
                    extra_lines += 1
                i += 2
            else:
                result.append(c)
                i += 1
        elif src[i:i+len(delim)] == delim:
            result.append(delim)
            i += len(delim)
            break
        elif c == '\n':
            if len(delim) == 1:
                # Unterminated single-line string — stop at newline
                break
            result.append(c)
            extra_lines += 1
            i += 1
        else:
            result.append(c)
            i += 1

    return ''.join(result), i, extra_lines


def _lex(source):
    """Tokenize AdaScript/Python source, yielding TokenInfo objects.

    Handles all standard Python tokens plus AdaScript extensions:
      - '..' -> RANGE_TOKEN
      - '..<' -> RANGE_EXCL_TOKEN
      - x'Attr -> NAME x, TICK_TOKEN, NAME Attr
      - $VAR / $0 / $# / $@ -> DOLLAR_TOKEN + NAME/NUMBER
      - -e/-f/-d (in boolean context) -> BASH_TEST_TOKEN + NAME flag
      - -nt / -ot (surrounded by whitespace) -> BASH_CMP_TOKEN
    """
    lines = source.splitlines(True)
    if not lines:
        lines = ['']

    # Indentation tracking
    indent_stack = [0]
    # Track bracket depth to suppress INDENT/DEDENT/NEWLINE inside brackets
    bracket_depth = 0
    # Track the last non-whitespace/non-comment token type for context
    last_type = _ENDMARKER

    # Emit ENCODING first (expected by callers)
    yield tkn.TokenInfo(_ENCODING, 'utf-8', (0, 0), (0, 0), '')

    line_no = 0
    pos = 0
    # We process char-by-char using a flat source string + line index
    src = source

    # Build line start offsets for (line, col) calculation
    line_starts = [0]
    for ln in lines:
        line_starts.append(line_starts[-1] + len(ln))

    def get_linecol(offset):
        # Binary search for line
        lo, hi = 0, len(line_starts) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if line_starts[mid] <= offset:
                lo = mid
            else:
                hi = mid - 1
        ln = lo  # 0-based line index
        col = offset - line_starts[ln]
        return (ln + 1, col)  # 1-based line

    def current_line_text(offset):
        ln_idx, _ = get_linecol(offset)
        if 1 <= ln_idx <= len(lines):
            return lines[ln_idx - 1]
        return ''

    i = 0
    n = len(src)

    # pending_dedents: number of DEDENT tokens still to emit
    pending_dedents = 0

    while i <= n:
        # ---- emit pending DEDENTs ----
        while pending_dedents > 0:
            lc = get_linecol(i)
            line_txt = current_line_text(i)
            yield tkn.TokenInfo(_DEDENT, '', lc, lc, line_txt)
            pending_dedents -= 1

        if i == n:
            # End of source: emit NEWLINE if needed, then ENDMARKER
            lc = get_linecol(i)
            yield tkn.TokenInfo(_NEWLINE, '', lc, lc, '')
            yield tkn.TokenInfo(_ENDMARKER, '', lc, lc, '')
            break

        c = src[i]
        start_lc = get_linecol(i)
        line_txt = current_line_text(i)

        # ---- beginning of line: handle indentation ----
        if start_lc[1] == 0 and c not in ('\n', '\r', '#'):
            # Measure indent
            ws_m = _WS_RE.match(src, i)
            indent_str = ws_m.group(0) if ws_m else ''
            indent = len(indent_str.expandtabs(8))  # tabs count as multiples of 8
            i += len(indent_str)
            if bracket_depth == 0:
                prev_indent = indent_stack[-1]
                if indent > prev_indent:
                    indent_stack.append(indent)
                    ind_end = get_linecol(i)
                    yield tkn.TokenInfo(_INDENT, indent_str, start_lc, ind_end, line_txt)
                elif indent < prev_indent:
                    while indent_stack[-1] > indent:
                        indent_stack.pop()
                        yield tkn.TokenInfo(_DEDENT, '', start_lc, start_lc, line_txt)
            continue  # re-enter loop to process actual token at new i

        # ---- whitespace (mid-line) ----
        if c in (' ', '\t'):
            ws_m = _WS_RE.match(src, i)
            i += len(ws_m.group(0))
            continue

        # ---- newline ----
        if c in ('\n', '\r'):
            nl_m = _NL_RE.match(src, i)
            nl_str = nl_m.group(0)
            end_lc = get_linecol(i + len(nl_str))
            if bracket_depth > 0:
                # Inside brackets: emit NL (continuation), not NEWLINE
                yield tkn.TokenInfo(_NL, nl_str, start_lc, end_lc, line_txt)
            else:
                yield tkn.TokenInfo(_NEWLINE, nl_str, start_lc, end_lc, line_txt)
                # Handle dedents for next line
                next_i = i + len(nl_str)
                # Peek at next line's indentation
                if next_i < n:
                    next_lc = get_linecol(next_i)
                    if next_lc[1] == 0:
                        ws2 = _WS_RE.match(src, next_i)
                        next_ind_str = ws2.group(0) if ws2 else ''
                        next_ind = len(next_ind_str.expandtabs(8))
                        next_c = src[next_i + len(next_ind_str)] if next_i + len(next_ind_str) < n else ''
                        if next_c not in ('\n', '\r', '#', ''):
                            while len(indent_stack) > 1 and indent_stack[-1] > next_ind:
                                indent_stack.pop()
                                pending_dedents += 1
            last_type = _NEWLINE
            i += len(nl_str)
            continue

        # ---- comment ----
        if c == '#':
            cm_m = _COMMENT_RE.match(src, i)
            cm_str = cm_m.group(0)
            end_lc = get_linecol(i + len(cm_str))
            yield tkn.TokenInfo(_COMMENT, cm_str, start_lc, end_lc, line_txt)
            last_type = _COMMENT
            i += len(cm_str)
            continue

        # ---- string literal ----
        # Check for string prefix + quote
        str_pfx_m = _STR_PREFIX_RE.match(src, i)
        if str_pfx_m or (c in ('"', "'")):
            pfx_len = len(str_pfx_m.group(0)) if str_pfx_m else 0
            if i + pfx_len < n and src[i + pfx_len] in ('"', "'"):
                s_str, new_i, _ = _read_string(src, i, start_lc[0], start_lc[1], lines)
                if s_str is not None:
                    end_lc = get_linecol(new_i)
                    yield tkn.TokenInfo(_STRING, s_str, start_lc, end_lc, line_txt)
                    last_type = _STRING
                    i = new_i
                    continue

        # ---- number ----
        if c.isdigit() or (c == '.' and i + 1 < n and src[i+1].isdigit()):
            nm = _NUMBER_RE.match(src, i)
            if nm:
                num_str = nm.group(0)
                end_lc = get_linecol(i + len(num_str))
                yield tkn.TokenInfo(_NUMBER, num_str, start_lc, end_lc, line_txt)
                last_type = _NUMBER
                i += len(num_str)
                continue

        # ---- identifier / keyword ----
        if c.isalpha() or c == '_':
            nm = _NAME_RE.match(src, i)
            name_str = nm.group(0)
            end_lc = get_linecol(i + len(name_str))
            yield tkn.TokenInfo(_NAME, name_str, start_lc, end_lc, line_txt)
            last_type = _NAME
            i += len(name_str)
            # Check for tick immediately after name: x'Attr
            if i < n and src[i] == "'":
                # Only if followed by identifier (not end of string)
                tick_m = re.match(r"'([A-Za-z_]\w*)", src, i)
                if tick_m:
                    tick_lc = get_linecol(i)
                    tick_end = get_linecol(i + 1)
                    attr_str = tick_m.group(1)
                    attr_start = get_linecol(i + 1)
                    attr_end = get_linecol(i + 1 + len(attr_str))
                    yield tkn.TokenInfo(TICK_TOKEN, "'", tick_lc, tick_end, line_txt)
                    yield tkn.TokenInfo(_NAME, attr_str, attr_start, attr_end, line_txt)
                    last_type = _NAME
                    i += 1 + len(attr_str)
            continue

        # ---- dollar variable: $#, $@, $0, $N, $NAME ----
        if c == '$':
            dol_lc = start_lc
            dol_end = get_linecol(i + 1)
            j = i + 1
            if j < n:
                nc = src[j]
                if nc == '#':
                    # $# -> DOLLAR_TOKEN + NAME("#")
                    yield tkn.TokenInfo(DOLLAR_TOKEN, '$', dol_lc, dol_end, line_txt)
                    h_lc = get_linecol(j)
                    h_end = get_linecol(j + 1)
                    yield tkn.TokenInfo(_NAME, '#', h_lc, h_end, line_txt)
                    last_type = _NAME
                    i = j + 1
                    continue
                elif nc == '@':
                    # $@ -> DOLLAR_TOKEN + NAME("@")
                    yield tkn.TokenInfo(DOLLAR_TOKEN, '$', dol_lc, dol_end, line_txt)
                    at_lc = get_linecol(j)
                    at_end = get_linecol(j + 1)
                    yield tkn.TokenInfo(_NAME, '@', at_lc, at_end, line_txt)
                    last_type = _NAME
                    i = j + 1
                    continue
                elif nc.isdigit():
                    # $0, $1 .. $N -> DOLLAR_TOKEN + NUMBER
                    nm2 = re.match(r'\d+', src, j)
                    num_s = nm2.group(0)
                    yield tkn.TokenInfo(DOLLAR_TOKEN, '$', dol_lc, dol_end, line_txt)
                    n_lc = get_linecol(j)
                    n_end = get_linecol(j + len(num_s))
                    yield tkn.TokenInfo(_NUMBER, num_s, n_lc, n_end, line_txt)
                    last_type = _NUMBER
                    i = j + len(num_s)
                    continue
                elif nc.isalpha() or nc == '_':
                    # $NAME (uppercase env var) -> DOLLAR_TOKEN + NAME
                    nm3 = _NAME_RE.match(src, j)
                    env_s = nm3.group(0)
                    yield tkn.TokenInfo(DOLLAR_TOKEN, '$', dol_lc, dol_end, line_txt)
                    e_lc = get_linecol(j)
                    e_end = get_linecol(j + len(env_s))
                    yield tkn.TokenInfo(_NAME, env_s, e_lc, e_end, line_txt)
                    last_type = _NAME
                    i = j + len(env_s)
                    continue
            # Bare '$' with nothing following — emit as ERRORTOKEN
            yield tkn.TokenInfo(_ERRORTOKEN, '$', dol_lc, dol_end, line_txt)
            last_type = _ERRORTOKEN
            i += 1
            continue

        # ---- operators (including range ops and tick after ] or )) ----
        op_m = _OP_RE.match(src, i)
        if op_m:
            op_str = op_m.group(0)

            # Range operators: '..' and '..<'
            if op_str == '..<':
                end_lc = get_linecol(i + 3)
                yield tkn.TokenInfo(RANGE_EXCL_TOKEN, '..<', start_lc, end_lc, line_txt)
                last_type = RANGE_EXCL_TOKEN
                i += 3
                continue
            if op_str == '..':
                end_lc = get_linecol(i + 2)
                yield tkn.TokenInfo(RANGE_TOKEN, '..', start_lc, end_lc, line_txt)
                last_type = RANGE_TOKEN
                i += 2
                continue

            # Tick after ] or )
            if op_str == "'" and last_type in (tkn.RPAR, tkn.RSQB):
                tick_m = re.match(r"'([A-Za-z_]\w*)", src, i)
                if tick_m:
                    tick_end = get_linecol(i + 1)
                    attr_str = tick_m.group(1)
                    attr_start = get_linecol(i + 1)
                    attr_end = get_linecol(i + 1 + len(attr_str))
                    yield tkn.TokenInfo(TICK_TOKEN, "'", start_lc, tick_end, line_txt)
                    yield tkn.TokenInfo(_NAME, attr_str, attr_start, attr_end, line_txt)
                    last_type = _NAME
                    i += 1 + len(attr_str)
                    continue

            # Minus: check for bash file-test (-e, -f, ...) or bash cmp (-nt, -ot)
            if op_str == '-':
                rest = src[i+1:]
                # -nt / -ot (surrounded by whitespace — previous token must have space)
                cmp_m = re.match(r'-(nt|ot)(?=\s|$)', src, i)
                if cmp_m:
                    op_val = cmp_m.group(0)  # '-nt' or '-ot'
                    end_lc = get_linecol(i + len(op_val))
                    yield tkn.TokenInfo(BASH_CMP_TOKEN, op_val, start_lc, end_lc, line_txt)
                    last_type = BASH_CMP_TOKEN
                    i += len(op_val)
                    continue
                # -e, -f, -d, etc. — only in boolean context
                ft_m = re.match(r'-([efdLrwxscbpS])(?=\s)', src, i)
                if ft_m:
                    # Check context: is the previous token a boolean-context keyword or '('?
                    _in_test_ctx = False
                    if last_type == _NAME:
                        # Find the previous NAME token string
                        # We need to look backwards in what we've emitted — track prev_name
                        _in_test_ctx = (_prev_name in _FILE_TEST_CONTEXT)
                    elif last_type == tkn.LPAR:
                        _in_test_ctx = True
                    if _in_test_ctx:
                        flag_char = ft_m.group(1)
                        end_lc = get_linecol(i + 2)
                        flag_lc = get_linecol(i + 1)
                        flag_end = get_linecol(i + 2)
                        yield tkn.TokenInfo(BASH_TEST_TOKEN, '-', start_lc, end_lc, line_txt)
                        yield tkn.TokenInfo(_NAME, flag_char, flag_lc, flag_end, line_txt)
                        last_type = _NAME
                        i += 2
                        continue

            # Normal operator
            exact = _EXACT.get(op_str, _OP)
            end_lc = get_linecol(i + len(op_str))
            yield tkn.TokenInfo(exact, op_str, start_lc, end_lc, line_txt)
            last_type = exact
            # Track bracket depth
            if op_str in ('(', '[', '{'):
                bracket_depth += 1
            elif op_str in (')', ']', '}'):
                bracket_depth = max(0, bracket_depth - 1)
            i += len(op_str)
            continue

        # ---- unknown character ----
        end_lc = get_linecol(i + 1)
        yield tkn.TokenInfo(_ERRORTOKEN, c, start_lc, end_lc, line_txt)
        last_type = _ERRORTOKEN
        i += 1


# The _lex function needs a _prev_name tracker — inject it properly:
def _lex_tracked(source):
    """Wrapper around _lex that tracks previous NAME string for bash-test context."""
    prev_name = ''
    # We need to inject _prev_name into _lex — reimplement the minus handler here
    # by post-processing: easier to just track in a wrapper.
    # Actually, we rebuild _lex inline with prev_name tracking via a closure.
    # See _lex_impl below.
    return _lex_impl(source)


def _lex_impl(source):
    """Full lexer with prev_name tracking for bash file-test context detection."""
    lines = source.splitlines(True)
    if not lines:
        lines = ['']

    indent_stack = [0]
    bracket_depth = 0
    last_type = _ENDMARKER
    prev_name = ''  # last NAME string seen
    prev_op = ''    # last OP string seen (for context checks)

    yield tkn.TokenInfo(_ENCODING, 'utf-8', (0, 0), (0, 0), '')

    src = source
    n = len(src)

    line_starts = [0]
    for ln in lines:
        line_starts.append(line_starts[-1] + len(ln))

    def get_linecol(offset):
        o = max(0, min(offset, n))
        lo2, hi2 = 0, len(line_starts) - 1
        while lo2 < hi2:
            mid = (lo2 + hi2 + 1) // 2
            if line_starts[mid] <= o:
                lo2 = mid
            else:
                hi2 = mid - 1
        col = o - line_starts[lo2]
        return (lo2 + 1, col)

    def current_line_text(offset):
        ln_idx, _ = get_linecol(offset)
        if 1 <= ln_idx <= len(lines):
            return lines[ln_idx - 1]
        return ''

    pending_dedents = 0
    i = 0
    at_line_start = True  # True when we're at column 0 waiting for indent processing

    while i <= n:
        # emit pending DEDENTs
        while pending_dedents > 0:
            lc = get_linecol(i)
            line_txt = current_line_text(i)
            yield tkn.TokenInfo(_DEDENT, '', lc, lc, line_txt)
            pending_dedents -= 1
            last_type = _DEDENT

        if i == n:
            lc = get_linecol(i)
            # Emit NEWLINE if the last token wasn't already a newline
            if last_type not in (_NEWLINE, _NL, _DEDENT, _ENDMARKER, _ENCODING):
                yield tkn.TokenInfo(_NEWLINE, '', lc, lc, '')
            # Emit remaining dedents
            while len(indent_stack) > 1:
                indent_stack.pop()
                yield tkn.TokenInfo(_DEDENT, '', lc, lc, '')
            yield tkn.TokenInfo(_ENDMARKER, '', lc, lc, '')
            break

        c = src[i]
        start_lc = get_linecol(i)
        line_txt = current_line_text(i)

        # ---- indentation at start of line ----
        if at_line_start and c not in ('\n', '\r', '#'):
            at_line_start = False
            ws_m = _WS_RE.match(src, i)
            indent_str = ws_m.group(0) if ws_m else ''
            indent = len(indent_str.expandtabs(8))
            # Peek past whitespace: if this is a comment-only or blank line,
            # skip INDENT/DEDENT entirely (Python's tokenizer does the same).
            peek_i = i + len(indent_str)
            peek_c = src[peek_i] if peek_i < n else ''
            if peek_c in ('\n', '\r', '#'):
                i = peek_i  # skip the leading whitespace; let comment/NL handler fire
                continue
            i += len(indent_str)
            if bracket_depth == 0:
                prev_ind = indent_stack[-1]
                if indent > prev_ind:
                    indent_stack.append(indent)
                    ind_end = get_linecol(i)
                    yield tkn.TokenInfo(_INDENT, indent_str, start_lc, ind_end, line_txt)
                    last_type = _INDENT
                elif indent < prev_ind:
                    while len(indent_stack) > 1 and indent_stack[-1] > indent:
                        indent_stack.pop()
                        yield tkn.TokenInfo(_DEDENT, '', start_lc, start_lc, line_txt)
                        last_type = _DEDENT
            continue

        # ---- whitespace ----
        if c in (' ', '\t'):
            ws_m = _WS_RE.match(src, i)
            i += len(ws_m.group(0))
            continue

        # ---- newline ----
        if c in ('\n', '\r'):
            at_line_start = True
            nl_m = _NL_RE.match(src, i)
            nl_str = nl_m.group(0)
            end_lc = get_linecol(i + len(nl_str))
            if bracket_depth > 0:
                yield tkn.TokenInfo(_NL, nl_str, start_lc, end_lc, line_txt)
                last_type = _NL
            else:
                yield tkn.TokenInfo(_NEWLINE, nl_str, start_lc, end_lc, line_txt)
                last_type = _NEWLINE
                # Peek ahead for dedents
                next_i = i + len(nl_str)
                if next_i < n:
                    ws2 = _WS_RE.match(src, next_i)
                    next_ind_str = ws2.group(0) if ws2 else ''
                    next_ind = len(next_ind_str.expandtabs(8))
                    ni2 = next_i + len(next_ind_str)
                    next_c = src[ni2] if ni2 < n else ''
                    if next_c not in ('\n', '\r', '#', ''):
                        while len(indent_stack) > 1 and indent_stack[-1] > next_ind:
                            indent_stack.pop()
                            pending_dedents += 1
            i += len(nl_str)
            continue

        # ---- comment ----
        if c == '#':
            cm_m = _COMMENT_RE.match(src, i)
            cm_str = cm_m.group(0)
            end_lc = get_linecol(i + len(cm_str))
            yield tkn.TokenInfo(_COMMENT, cm_str, start_lc, end_lc, line_txt)
            last_type = _COMMENT
            i += len(cm_str)
            continue

        # ---- tick after ] or ) — must come before string handler ----
        if c == "'" and last_type == _OP and prev_op in (')', ']'):
            tick_m = re.match(r"'([A-Za-z_]\w*)", src[i:])
            if tick_m:
                attr_str = tick_m.group(1)
                tick_end = get_linecol(i + 1)
                attr_start = get_linecol(i + 1)
                attr_end = get_linecol(i + 1 + len(attr_str))
                yield tkn.TokenInfo(TICK_TOKEN, "'", start_lc, tick_end, line_txt)
                yield tkn.TokenInfo(_NAME, attr_str, attr_start, attr_end, line_txt)
                prev_name = attr_str; last_type = _NAME
                i += 1 + len(attr_str); continue

        # ---- string literal ----
        str_pfx_m = _STR_PREFIX_RE.match(src, i)
        pfx_len = len(str_pfx_m.group(0)) if str_pfx_m else 0
        if pfx_len > 0 or c in ('"', "'"):
            qi = i + pfx_len
            if qi < n and src[qi] in ('"', "'"):
                s_str, new_i, _ = _read_string(src, i, start_lc[0], start_lc[1], lines)
                if s_str is not None:
                    end_lc = get_linecol(new_i)
                    yield tkn.TokenInfo(_STRING, s_str, start_lc, end_lc, line_txt)
                    last_type = _STRING
                    i = new_i
                    continue

        # ---- number ----
        if c.isdigit() or (c == '.' and i + 1 < n and src[i+1].isdigit()):
            nm = _NUMBER_RE.match(src, i)
            if nm:
                num_str = nm.group(0)
                # If number ends with '.' and the next char is also '.', we're at
                # a range boundary like '1..10' — strip the trailing dot.
                while num_str.endswith('.') and i + len(num_str) < n and src[i + len(num_str)] == '.':
                    num_str = num_str[:-1]
                end_lc = get_linecol(i + len(num_str))
                yield tkn.TokenInfo(_NUMBER, num_str, start_lc, end_lc, line_txt)
                last_type = _NUMBER
                i += len(num_str)
                continue

        # ---- identifier / keyword ----
        if c.isalpha() or c == '_':
            nm = _NAME_RE.match(src, i)
            name_str = nm.group(0)
            end_lc = get_linecol(i + len(name_str))
            yield tkn.TokenInfo(_NAME, name_str, start_lc, end_lc, line_txt)
            prev_name = name_str
            last_type = _NAME
            i += len(name_str)
            # Tick immediately after name: x'Attr
            if i < n and src[i] == "'":
                tick_m = re.match(r"'([A-Za-z_]\w*)", src[i:])
                if tick_m:
                    attr_str = tick_m.group(1)
                    tick_lc = get_linecol(i)
                    tick_end = get_linecol(i + 1)
                    attr_start = get_linecol(i + 1)
                    attr_end = get_linecol(i + 1 + len(attr_str))
                    yield tkn.TokenInfo(TICK_TOKEN, "'", tick_lc, tick_end, line_txt)
                    yield tkn.TokenInfo(_NAME, attr_str, attr_start, attr_end, line_txt)
                    prev_name = attr_str
                    last_type = _NAME
                    i += 1 + len(attr_str)
            continue

        # ---- dollar variable ----
        if c == '$':
            dol_lc = start_lc
            dol_end = get_linecol(i + 1)
            j = i + 1
            if j < n:
                nc = src[j]
                if nc == '#':
                    yield tkn.TokenInfo(DOLLAR_TOKEN, '$', dol_lc, dol_end, line_txt)
                    h_lc = get_linecol(j)
                    h_end = get_linecol(j + 1)
                    yield tkn.TokenInfo(_NAME, '#', h_lc, h_end, line_txt)
                    prev_name = '#'; last_type = _NAME
                    i = j + 1; continue
                elif nc == '@':
                    yield tkn.TokenInfo(DOLLAR_TOKEN, '$', dol_lc, dol_end, line_txt)
                    at_lc = get_linecol(j)
                    at_end = get_linecol(j + 1)
                    yield tkn.TokenInfo(_NAME, '@', at_lc, at_end, line_txt)
                    prev_name = '@'; last_type = _NAME
                    i = j + 1; continue
                elif nc.isdigit():
                    nm2 = re.match(r'\d+', src[j:])
                    num_s = nm2.group(0)
                    yield tkn.TokenInfo(DOLLAR_TOKEN, '$', dol_lc, dol_end, line_txt)
                    n_lc = get_linecol(j)
                    n_end = get_linecol(j + len(num_s))
                    yield tkn.TokenInfo(_NUMBER, num_s, n_lc, n_end, line_txt)
                    last_type = _NUMBER
                    i = j + len(num_s); continue
                elif nc.isalpha() or nc == '_':
                    nm3 = _NAME_RE.match(src, j)
                    env_s = nm3.group(0)
                    yield tkn.TokenInfo(DOLLAR_TOKEN, '$', dol_lc, dol_end, line_txt)
                    e_lc = get_linecol(j)
                    e_end = get_linecol(j + len(env_s))
                    yield tkn.TokenInfo(_NAME, env_s, e_lc, e_end, line_txt)
                    prev_name = env_s; last_type = _NAME
                    i = j + len(env_s); continue
            yield tkn.TokenInfo(_ERRORTOKEN, '$', dol_lc, dol_end, line_txt)
            last_type = _ERRORTOKEN; i += 1; continue

        # ---- operators ----
        # Check range/ellipsis first (. is ambiguous with float)
        if c == '.':
            if src[i:i+3] == '..<':
                end_lc = get_linecol(i + 3)
                yield tkn.TokenInfo(RANGE_EXCL_TOKEN, '..<', start_lc, end_lc, line_txt)
                last_type = RANGE_EXCL_TOKEN; i += 3; continue
            if src[i:i+3] == '...':
                end_lc = get_linecol(i + 3)
                yield tkn.TokenInfo(_OP, '...', start_lc, end_lc, line_txt)
                last_type = _OP; i += 3; continue
            if src[i:i+2] == '..':
                end_lc = get_linecol(i + 2)
                yield tkn.TokenInfo(RANGE_TOKEN, '..', start_lc, end_lc, line_txt)
                last_type = RANGE_TOKEN; i += 2; continue
            # Single dot
            end_lc = get_linecol(i + 1)
            yield tkn.TokenInfo(_OP, '.', start_lc, end_lc, line_txt)
            last_type = _OP; i += 1; continue

        # Minus: bash file-test or bash cmp
        if c == '-':
            # -nt / -ot
            cmp_m = re.match(r'-(nt|ot)(?=[\s\n\r]|$)', src[i:])
            if cmp_m:
                op_val = cmp_m.group(0)
                end_lc = get_linecol(i + len(op_val))
                yield tkn.TokenInfo(BASH_CMP_TOKEN, op_val, start_lc, end_lc, line_txt)
                last_type = BASH_CMP_TOKEN; i += len(op_val); continue
            # -e, -f, -d, etc. in boolean context
            ft_m = re.match(r'-([efdLrwxscbpS])(?=[\s\n\r]|$)', src[i:])
            if ft_m:
                _in_ctx = (last_type == _NAME and prev_name in _FILE_TEST_CONTEXT) \
                          or last_type == _OP and prev_op == '('
                if _in_ctx:
                    flag_char = ft_m.group(1)
                    end_lc = get_linecol(i + 2)
                    flag_lc = get_linecol(i + 1)
                    flag_end = get_linecol(i + 2)
                    yield tkn.TokenInfo(BASH_TEST_TOKEN, '-', start_lc, end_lc, line_txt)
                    yield tkn.TokenInfo(_NAME, flag_char, flag_lc, flag_end, line_txt)
                    prev_name = flag_char; last_type = _NAME
                    i += 2; continue

        # General operator matching (longest match first)
        op_m = _OP_RE.match(src, i)
        if op_m:
            op_str = op_m.group(0)
            end_lc = get_linecol(i + len(op_str))
            yield tkn.TokenInfo(_OP, op_str, start_lc, end_lc, line_txt)
            last_type = _OP
            prev_op = op_str
            if op_str in ('(', '[', '{'):
                bracket_depth += 1
            elif op_str in (')', ']', '}'):
                bracket_depth = max(0, bracket_depth - 1)
            i += len(op_str)
            continue

        # Unknown character
        end_lc = get_linecol(i + 1)
        yield tkn.TokenInfo(_ERRORTOKEN, c, start_lc, end_lc, line_txt)
        last_type = _ERRORTOKEN; i += 1


# ---------------------------------------------------------------------------
# tokenize_string — kept for compatibility
# ---------------------------------------------------------------------------
def tokenize_string(s):
    """Tokenize a source string, returning a generator of TokenInfo."""
    return _lex_impl(s)


# ---------------------------------------------------------------------------
# Tokenizer class
# ---------------------------------------------------------------------------
class Tokenizer:
    """Enhanced tokenizer that bundles comments with newlines as RichNL objects.

    Replaces Python's tokenize module with a custom lexer (_lex_impl).
    All synthetic tokens (TICK, DOLLAR, BASH_TEST, BASH_CMP, RANGE, RANGE_EXCL)
    are emitted directly by the lexer with no preprocessing step.
    """

    def __init__(self, s):
        self.source_lines = s.splitlines(True)
        self.tokens = []
        self.pos = 0
        self.memos = {}
        self._buffer = []
        self.multiline_brackets = {}
        self.farthest_pos = 0
        self._raw_gen = _lex_impl(s)
        self._eager_tokenize()

    def _eager_tokenize(self):
        """Pre-load all tokens, bundle comments+NLs into RichNL, strip NLs inside brackets."""
        raw_tokens = []
        buf_idx = 0

        # Collect all raw tokens
        for tok in self._raw_gen:
            raw_tokens.append(tok)
            if tok.type == _ENDMARKER:
                break

        # First pass: bundle COMMENT+NL into RichNL
        bundled = []
        j = 0
        while j < len(raw_tokens):
            tok = raw_tokens[j]
            if tok.type == _COMMENT:
                # Look ahead for NL/NEWLINE
                if j + 1 < len(raw_tokens) and raw_tokens[j+1].type in (_NL, _NEWLINE):
                    nl_tok = raw_tokens[j+1]
                    rich = RichNL(nl_tok, [('comment', tok.string, tok.start[1])], is_blank=False)
                    bundled.append((rich, []))
                    j += 2
                    continue
                else:
                    bundled.append((tok, []))
            elif tok.type == _NL:
                bundled.append((RichNL(tok, [], is_blank=True), []))
            elif tok.type == _NEWLINE:
                bundled.append((RichNL(tok, [], is_blank=False), []))
            else:
                bundled.append((tok, []))
            j += 1

        # Second pass: strip NLs inside brackets, track multiline bracket spans
        bracket_stack = []
        depth = 0
        filtered = []
        for tok, meta in bundled:
            if hasattr(tok, 'string') and not isinstance(tok, RichNL):
                import token as _tm
                is_fmid = hasattr(tok, 'type') and tok.type == getattr(_tm, 'FSTRING_MIDDLE', -1)
                if not is_fmid and tok.string in ('(', '[', '{'):
                    depth += 1
                    bracket_stack.append((tok, False))
                elif not is_fmid and tok.string in (')', ']', '}'):
                    depth = max(0, depth - 1)
                    if bracket_stack:
                        open_tok, had_nl = bracket_stack.pop()
                        if had_nl:
                            self.multiline_brackets[open_tok.start] = \
                                self._extract_source_span(open_tok, tok)
            if depth > 0 and isinstance(tok, RichNL):
                if bracket_stack:
                    bracket_stack[-1] = (bracket_stack[-1][0], True)
                continue
            filtered.append((tok, meta))
        self.tokens = filtered

    def _extract_source_span(self, open_tok, close_tok):
        start_line, start_col = open_tok.start
        end_line, end_col = close_tok.end
        if start_line == end_line:
            return self.source_lines[start_line - 1][start_col:end_col]
        parts = [self.source_lines[start_line - 1][start_col:]]
        for idx in range(start_line, end_line - 1):
            parts.append(self.source_lines[idx])
        parts.append(self.source_lines[end_line - 1][:end_col])
        return ''.join(parts)

    def mark(self):
        return self.pos

    def reset(self, pos):
        self.pos = pos

    def get_new_token(self):
        if self.pos < len(self.tokens):
            token = self.tokens[self.pos][0]
            if token is not None:
                self.pos += 1
                if self.pos > self.farthest_pos:
                    self.farthest_pos = self.pos
                return token
        return None

    def peep_next_token(self):
        tok = self.get_new_token()
        self.pos -= 1
        return tok

    def get_current_token(self):
        if self.pos == 0:
            return None
        return self.tokens[self.pos - 1][0]

    def get_text(self, pos):
        return " ".join(tk[0].string for tk in self.tokens[pos:self.pos])

    def get_farthest_token(self):
        idx = min(self.farthest_pos, len(self.tokens) - 1)
        return self.tokens[idx]

    def format_error(self):
        best_idx = min(self.farthest_pos, len(self.tokens) - 1)
        best_expected = self.tokens[best_idx][1]
        for idx in range(best_idx, max(best_idx - 3, -1), -1):
            if idx < len(self.tokens) and len(self.tokens[idx][1]) > len(best_expected):
                best_idx = idx
                best_expected = self.tokens[idx][1]
        tok = self.tokens[best_idx][0]
        line, col = tok.start if hasattr(tok, 'start') else (0, 0)
        got = repr(tok.string) if hasattr(tok, 'string') and tok.string else tok.__class__.__name__
        msg = f"Parse error at line {line}, col {col}: got {got}"
        if best_expected:
            unique = sorted(set(best_expected))
            msg += f", expected one of: {', '.join(unique)}"
        return msg

    def set_failed_token(self, expected_token_as_string):
        self.tokens[self.pos - 1][1].append(expected_token_as_string)

    def __iter__(self):
        return self

    def __next__(self):
        tok = self.get_new_token()
        if tok is None:
            raise StopIteration
        return tok


# ---------------------------------------------------------------------------
# Module-level context tracker
# ---------------------------------------------------------------------------
_current_tokenizer = None

def set_current_tokenizer(t):
    global _current_tokenizer
    _current_tokenizer = t

def get_multiline_brackets():
    if _current_tokenizer is not None:
        return getattr(_current_tokenizer, 'multiline_brackets', {})
    return {}


# ---------------------------------------------------------------------------
# Debug helper
# ---------------------------------------------------------------------------
def test_tokenizer(source):
    mytokenizer = Tokenizer(source)
    prev_line_number = -1
    while True:
        token = mytokenizer.get_new_token()
        if token is None:
            print("{:-^60s}".format("OUT"))
            break
        line_number = token.start[0] if hasattr(token, 'start') else 0
        if line_number > prev_line_number:
            print("{:*^60s}".format(f" LINE {line_number} "))
        print(repr(token))
        if hasattr(token, 'type') and token.type == _ENDMARKER:
            print("{:-^60s}".format("OUT"))
            break
        prev_line_number = line_number


def _tok_seq(source):
    """Return list of (type, string) pairs for all non-whitespace tokens."""
    t = Tokenizer(source)
    result = []
    while True:
        tok = t.get_new_token()
        if tok is None or tok.type == _ENDMARKER:
            break
        if tok.type in (_ENCODING, _NEWLINE, _NL, _INDENT, _DEDENT):
            continue
        if hasattr(tok, 'type'):
            result.append((tok.type, tok.string))
    return result


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import platform, unittest
    print(f"Python version: {platform.python_version()}")

    class TestSyntheticTokens(unittest.TestCase):

        # ------------------------------------------------------------------ TICK
        def test_tick_bare_name(self):
            toks = _tok_seq("x'Image\n")
            self.assertIn((TICK_TOKEN, "'"), toks)
            types = [t for t, _ in toks]
            tick_idx = types.index(TICK_TOKEN)
            self.assertEqual(toks[tick_idx + 1][1], "Image")

        def test_tick_subscript(self):
            toks = _tok_seq("arr[i]'First\n")
            self.assertIn((TICK_TOKEN, "'"), toks)

        def test_tick_paren(self):
            toks = _tok_seq("(expr)'Choice\n")
            self.assertIn((TICK_TOKEN, "'"), toks)

        def test_tick_inside_string_untouched(self):
            toks = _tok_seq("s = \"it's fine\"\n")
            self.assertNotIn(TICK_TOKEN, [t for t, _ in toks])

        # ------------------------------------------------------------------ DOLLAR
        def test_dollar_zero(self):
            toks = _tok_seq("$0\n")
            self.assertIn((DOLLAR_TOKEN, "$"), toks)
            strings = [s for _, s in toks]
            self.assertIn("0", strings)

        def test_dollar_positional(self):
            toks = _tok_seq("$1\n")
            self.assertIn((DOLLAR_TOKEN, "$"), toks)
            strings = [s for _, s in toks]
            self.assertIn("1", strings)

        def test_dollar_at(self):
            toks = _tok_seq("$@\n")
            self.assertIn((DOLLAR_TOKEN, "$"), toks)
            strings = [s for _, s in toks]
            self.assertIn("@", strings)

        def test_dollar_hash(self):
            toks = _tok_seq("$#\n")
            self.assertIn((DOLLAR_TOKEN, "$"), toks)
            strings = [s for _, s in toks]
            self.assertIn("#", strings)

        def test_dollar_env(self):
            toks = _tok_seq("$HOME\n")
            self.assertIn((DOLLAR_TOKEN, "$"), toks)
            strings = [s for _, s in toks]
            self.assertIn("HOME", strings)

        def test_dollar_inside_string_untouched(self):
            toks = _tok_seq('"hello $1 world"\n')
            self.assertNotIn(DOLLAR_TOKEN, [t for t, _ in toks])

        # ------------------------------------------------------------------ BASH_TEST
        def test_bash_test_e(self):
            toks = _tok_seq("if -e path:\n    pass\n")
            self.assertIn((BASH_TEST_TOKEN, "-"), toks)
            strings = [s for _, s in toks]
            self.assertIn("e", strings)

        def test_bash_test_d(self):
            toks = _tok_seq("if -d path:\n    pass\n")
            self.assertIn((BASH_TEST_TOKEN, "-"), toks)

        def test_bash_test_f(self):
            toks = _tok_seq("if -f path:\n    pass\n")
            self.assertIn((BASH_TEST_TOKEN, "-"), toks)

        def test_bash_test_not_in_arbitrary_context(self):
            toks = _tok_seq("x = func(-e, y)\n")
            self.assertNotIn(BASH_TEST_TOKEN, [t for t, _ in toks])

        # ------------------------------------------------------------------ BASH_CMP
        def test_bash_cmp_nt(self):
            toks = _tok_seq("f1 -nt f2\n")
            self.assertIn((BASH_CMP_TOKEN, "-nt"), toks)

        def test_bash_cmp_ot(self):
            toks = _tok_seq("f1 -ot f2\n")
            self.assertIn((BASH_CMP_TOKEN, "-ot"), toks)

        def test_bash_cmp_inside_string_untouched(self):
            toks = _tok_seq('"file -nt other"\n')
            self.assertNotIn(BASH_CMP_TOKEN, [t for t, _ in toks])

        # ------------------------------------------------------------------ RANGE
        def test_range_incl_name_name(self):
            toks = _tok_seq("x..y\n")
            self.assertIn((RANGE_TOKEN, ".."), toks)

        def test_range_incl_digit_digit(self):
            toks = _tok_seq("1..10\n")
            self.assertIn((RANGE_TOKEN, ".."), toks)

        def test_range_incl_digit_name(self):
            toks = _tok_seq("0..n\n")
            self.assertIn((RANGE_TOKEN, ".."), toks)

        def test_range_incl_name_digit(self):
            toks = _tok_seq("lo..10\n")
            self.assertIn((RANGE_TOKEN, ".."), toks)

        def test_range_excl_name_name(self):
            toks = _tok_seq("x..<y\n")
            self.assertIn((RANGE_EXCL_TOKEN, "..<"), toks)

        def test_range_excl_digit_digit(self):
            toks = _tok_seq("0..<10\n")
            self.assertIn((RANGE_EXCL_TOKEN, "..<"), toks)

        def test_range_not_ellipsis(self):
            toks = _tok_seq("x = ...\n")
            types = [t for t, _ in toks]
            self.assertNotIn(RANGE_TOKEN, types)
            self.assertNotIn(RANGE_EXCL_TOKEN, types)

        def test_range_inside_string_untouched(self):
            toks = _tok_seq('"1..10"\n')
            types = [t for t, _ in toks]
            self.assertNotIn(RANGE_TOKEN, types)
            self.assertNotIn(RANGE_EXCL_TOKEN, types)

        def test_range_excl_not_matched_as_incl(self):
            toks = _tok_seq("0..<5\n")
            types = [t for t, _ in toks]
            self.assertIn(RANGE_EXCL_TOKEN, types)
            self.assertNotIn(RANGE_TOKEN, types)

    unittest.main(verbosity=2)
