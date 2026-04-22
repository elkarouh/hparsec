import tokenize as tkn
from textwrap import dedent

# Synthetic token types (above Python's token range which tops out around 62).
TICK_TOKEN      = 90   # Ada-style tick:  x'Image, arr[i]'First
DOLLAR_TOKEN    = 91   # Bash dollar var: $#, $@, $0, $N, $NAME
BASH_TEST_TOKEN = 92   # Bash file test:  -e, -f, -d, ...
BASH_CMP_TOKEN  = 93   # Bash file cmp:   -nt, -ot
RANGE_TOKEN     = 94   # Ada/Nim range:   lo .. hi
RANGE_EXCL_TOKEN = 95  # exclusive range: lo ..< hi

#################################### UTILS ########################################
if __name__ == "__main__":
    import platform

    print(f"Python version: {platform.python_version()}")


# import see; print(see.see(tkn.TokenInfo))
# inst.exact_name= tkn.tok_name[tok.exact_type]
# inst.name = tkn.tok_name[tok.type]
def add_this_method_to(KLASS):
    """Decorator to add a method to a class."""

    def wrapper(f):
        setattr(KLASS, f.__name__, f)

    return wrapper


@add_this_method_to(tkn.TokenInfo)
def __eq__(self, val):  # WE ADD A METHOD TO AN EXISTING CLASS
    return val == self.string


@add_this_method_to(tkn.TokenInfo)
def __str__(self):  # WE ADD A METHOD TO AN EXISTING CLASS
    if self.exact_type == self.type:
        return f"Token({tkn.tok_name[self.type]!s}, {self.string!r})"
    else:
        return f"Token({tkn.tok_name[self.type]!s}, {self.string!r}, {tkn.tok_name[self.exact_type]})"


#############################################################################
class Pipe:
    def __init__(self, function):
        self.function = function

    def __ror__(self, left):
        return self.function(left)

    def __call__(self, *args, **kwargs):
        return Pipe(lambda x: self.function(x, *args, **kwargs))

    __rrshift__ = __ror__  # >>

    def __mul__(self, other):
        return Pipe(lambda x: x >> self | other)


###############################################################################


class RichNL:
    """A newline token enriched with any preceding comments.

    This replaces the old approach of storing trivia by position.
    Comments now travel naturally with the NL tokens in the parse tree.

    Attributes:
        nl_token: The original NL or NEWLINE token (for position info)
        comments: List of (kind, text, indent) tuples for comments on this line
        type: Always tkn.NL or tkn.NEWLINE so grammar rules match correctly
        string: Empty string (NL doesn't contribute source text)
        is_blank: True if this represents a blank line (no comment, just NL)
    """
    string = ''

    def __init__(self, nl_token, comments=None, is_blank=False):
        self.nl_token = nl_token
        self.comments = comments if comments else []
        self.start = nl_token.start
        self.end = nl_token.end
        self.type = nl_token.type  # Can be NL or NEWLINE
        self.is_blank = is_blank

    def __repr__(self):
        if self.is_blank:
            return f'RichNL(blank)'
        return f'RichNL(comments={self.comments!r})'

    def to_lines(self):
        """Return list of text lines this RichNL contributes: comment lines and/or a blank."""
        lines = []
        for kind, text, ind in self.comments:
            if kind == 'comment':
                lines.append(' ' * ind + text)
        if self.is_blank:
            lines.append('')
        return lines

    def to_py(self):
        """Render to a newline-joined string (used by emit_richnl and NL.to_py)."""
        return '\n'.join(self.to_lines())

    def inline_comment(self):
        """Return the inline comment as '  # text', or '' if none."""
        for kind, text, ind in self.comments:
            if kind == 'comment':
                return '  ' + text
        return ''

    @classmethod
    def extract_from(cls, node):
        """Unwrap a Filter/NL parser node to get the inner RichNL, or return None."""
        if isinstance(node, cls):
            return node
        if hasattr(node, 'nodes') and node.nodes and isinstance(node.nodes[0], cls):
            return node.nodes[0]
        return None

import io


def tokenize_string(s):
    """Generator of tokens from the string"""
    return tkn.tokenize(io.BytesIO(s.encode("utf-8")).readline)


# NOTA: difference between NL and NEWLINE
# NEWLINE is used at the end of a LOGICAL line ( which may consist of several physical lines)
# NL is generated at the end of a PHYSICAL line, e.g:
#   1.newlines that end lines that are continued after unclosed braces.
#   2.newlines that end empty lines or lines that only have comments.


class Tokenizer:
    """An enhanced tokenizer that bundles comments with newline tokens as RichNL objects.

    Handles three cases:
    1. COMMENT + NL -> RichNL with comments (type=NL)
    2. COMMENT + NEWLINE -> RichNL with comments (type=NEWLINE) for inline comments
    3. Plain NL (blank lines) -> RichNL with is_blank=True (type=NL)
    """

    # Tick-attribute patterns: replace ' with __TICK__ sentinel so Python's tokenizer
    # sees three separate NAME tokens (base, __TICK__, attr) instead of a string literal.
    # __TICK__ is then converted to a TICK_TOKEN synthetic token in _eager_tokenize.
    import re as _re
    _TICK_RE = _re.compile(r"(\b[A-Za-z_]\w*)'([A-Za-z_]\w*)")
    _SUBSCRIPT_TICK_RE = _re.compile(r"(\])'([A-Za-z_]\w*)")
    _PAREN_TICK_RE = _re.compile(r"(\))'([A-Za-z_]\w*)")

    # Range-operator patterns: the issue is that Python's tokenizer greedily
    # merges a digit adjacent to '.' into a float literal, so:
    #   '0..10'  ->  NUMBER('0.')  NUMBER('.10')   (broken)
    #   'x..10'  ->  NAME('x')  OP('.')  NUMBER('.10')  (broken)
    #   '0..y'   ->  NUMBER('0.')  OP('.')  NAME('y')   (broken)
    # We insert a space on each side of '..' / '..<' when a digit is adjacent,
    # before Python's tokenizer ever sees the source.
    # Range operator patterns: replace '..' and '..<' with sentinels.
    # Must match '..<' before '..' (longer first), and must not match '...'.
    # Negative lookahead (?!\.) avoids matching '...' (ellipsis).
    _RANGE_EXCL_RE = _re.compile(r'\.\.<')                  # '..<' -> __RANGE_EXCL__
    _RANGE_INCL_RE = _re.compile(r'(?<!\.)\.\.(?![.<])')   # '..'  -> __RANGE__ (not '...' or '..<')

    # Bashism patterns: rewrite bash-style argument/environment variables to
    # safe identifier placeholders before Python's tokenizer sees them.
    #
    #   $#        -> __bash_argc__   (must come before $<digit> to beat '#' comment)
    #   $@        -> __bash_args__
    #   $0        -> __bash_arg0__
    #   $1..$N    -> __bash_arg1__ .. __bash_argN__  (multi-digit supported)
    #   $NAME     -> __bash_env_NAME__   (uppercase env var name)
    #
    # '$#' is the most dangerous: Python lexes '#' as a comment start, eating
    # everything after '$' to end-of-line.  The regex replaces the whole '$#'
    # before the tokenizer gets a chance to see it.
    _BASH_ARGC_RE = _re.compile(r'\$#')
    _BASH_ARGS_RE = _re.compile(r'\$@')
    _BASH_ARG_RE  = _re.compile(r'\$([0-9]+)')
    _BASH_ENV_RE  = _re.compile(r'\$([A-Z_][A-Z0-9_]*)')

    # Bash file-test operators: '-e FILE', '-f FILE', etc.
    # Must be preceded by a boolean-context keyword or '(' to avoid matching
    # command-line flags like 'Csetup -e foo' inside shell: bodies.
    _BASH_FILE_TEST_RE = _re.compile(r'(?:(?<=\bif\s)|(?<=\belif\s)|(?<=\bwhile\s)|(?<=\band\s)|(?<=\bor\s)|(?<=\bnot\s)|(?<=\())-([efdLrwxscbpS])(?=\s)')
    # Bash file-comparison operators: FILE1 -nt FILE2 / FILE1 -ot FILE2
    # Only match '-nt' and '-ot' surrounded by whitespace.
    _BASH_FILE_NT_RE = _re.compile(r'(?<=\s)-nt(?=\s)')
    _BASH_FILE_OT_RE = _re.compile(r'(?<=\s)-ot(?=\s)')

    @staticmethod
    def _preprocess_file_tests(s):
        """Replace bash file-test and file-comparison operators with sentinels.

        Mapping::

            -e FILE  -> __BASH_TEST__ e FILE
            -nt      -> __BASH_NT__
            -ot      -> __BASH_OT__

        _eager_tokenize converts the __BASH_*__ NAME tokens to synthetic tokens.
        """
        import re as _re2
        _STR_RE = _re2.compile(r'("""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\'|"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'|#[^\n]*)')
        parts = _STR_RE.split(s)
        for i in range(0, len(parts), 2):
            parts[i] = Tokenizer._BASH_FILE_TEST_RE.sub(r'__BASH_TEST__ \1', parts[i])
            parts[i] = Tokenizer._BASH_FILE_NT_RE.sub('__BASH_NT__', parts[i])
            parts[i] = Tokenizer._BASH_FILE_OT_RE.sub('__BASH_OT__', parts[i])
        return ''.join(parts)

    @staticmethod
    def _preprocess_bashisms(s):
        """Replace bash dollar-variables with sentinels.

        Mapping::

            $#   -> __DOLLAR__ #
            $@   -> __DOLLAR__ @
            $0   -> __DOLLAR__ 0
            $N   -> __DOLLAR__ N
            $ENV -> __DOLLAR__ ENV

        The __DOLLAR__ NAME sentinel is converted to DOLLAR_TOKEN in
        _eager_tokenize; the following token carries the variable name/sigil.
        '$#' must be replaced first to prevent '#' being lexed as a comment.
        """
        import re as _re_bash

        def _substitute(text):
            text = Tokenizer._BASH_ARGC_RE.sub('__DOLLAR__ __HASH__', text)
            text = Tokenizer._BASH_ARGS_RE.sub('__DOLLAR__ __AT__', text)
            text = Tokenizer._BASH_ARG_RE.sub(r'__DOLLAR__ \1', text)
            text = Tokenizer._BASH_ENV_RE.sub(r'__DOLLAR__ \1', text)
            return text

        def _process_fstring(fstr):
            out = []
            depth = 0
            i = 0
            if fstr.startswith(('f"""', "f'''")):
                prefix, i = fstr[:4], 4
            else:
                prefix, i = fstr[:2], 2
            out.append(prefix)
            while i < len(fstr):
                c = fstr[i]
                if c == '{' and i + 1 < len(fstr) and fstr[i + 1] == '{':
                    out.append('{{'); i += 2; continue
                if c == '}' and i + 1 < len(fstr) and fstr[i + 1] == '}':
                    out.append('}}'); i += 2; continue
                if c == '{':
                    depth += 1; out.append(c); i += 1; continue
                if c == '}' and depth > 0:
                    depth -= 1; out.append(c); i += 1; continue
                if depth > 0:
                    j = i
                    while i < len(fstr) and fstr[i] not in '{}':
                        i += 1
                    out.append(_substitute(fstr[j:i]))
                else:
                    out.append(c); i += 1
            return ''.join(out)

        string_re = _re_bash.compile(
            r'(f"""[\s\S]*?"""|f\'\'\'[\s\S]*?\'\'\'|f"(?:[^"\\]|\\.)*"|f\'(?:[^\'\\]|\\.)*\'|'
            r'"""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\'|"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\')'
        )
        parts = string_re.split(s)
        out = []
        for i, part in enumerate(parts):
            if i % 2 == 1:
                out.append(_process_fstring(part) if part.startswith('f') else part)
            else:
                out.append(_substitute(part))
        return ''.join(out)

    @staticmethod
    def _preprocess_range_operators(s):
        """Replace '..' and '..<' with __RANGE__/__RANGE_EXCL__ sentinels.

        Eliminates all float-tokenizer ambiguity (e.g. '0..10' -> '0.__RANGE__10')
        while keeping '...' (ellipsis) intact.  _eager_tokenize converts the
        NAME sentinels to RANGE_TOKEN/RANGE_EXCL_TOKEN synthetic tokens.

        Applied outside string literals only.
        """
        import re as _re2
        _STR_CMT_RE = _re2.compile(
            r'("""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\'|"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'|#[^\n]*)'
        )
        parts = _STR_CMT_RE.split(s)
        for i in range(0, len(parts), 2):
            parts[i] = Tokenizer._RANGE_EXCL_RE.sub(' __RANGE_EXCL__ ', parts[i])
            parts[i] = Tokenizer._RANGE_INCL_RE.sub(' __RANGE__ ', parts[i])
        return ''.join(parts)

    @staticmethod
    def _preprocess_tick_attributes(s):
        """Replace Ada-style tick (') with __TICK__ sentinel outside string literals.

        x'Image      -> x __TICK__ Image
        arr[i]'First -> arr[i] __TICK__ First
        (expr)'Choice -> (expr) __TICK__ Choice

        Python then tokenizes three separate NAME tokens; _eager_tokenize converts
        NAME("__TICK__") into a TICK_TOKEN synthetic token.
        """
        import re as _re2
        _DQ_CMT_RE = _re2.compile(r'("""[\s\S]*?"""|"(?:[^"\\]|\\.)*"|#[^\n]*)')
        parts = _DQ_CMT_RE.split(s)
        for i in range(0, len(parts), 2):
            parts[i] = Tokenizer._PAREN_TICK_RE.sub(r'\1 __TICK__ \2', parts[i])
            parts[i] = Tokenizer._SUBSCRIPT_TICK_RE.sub(r'\1 __TICK__ \2', parts[i])
            parts[i] = Tokenizer._TICK_RE.sub(r'\1 __TICK__ \2', parts[i])
        return ''.join(parts)

    def __init__(self, s):
        s = self._preprocess_tick_attributes(s)
        s = self._preprocess_range_operators(s)
        s = self._preprocess_file_tests(s)
        s = self._preprocess_bashisms(s)
        self.tokengen = tokenize_string(s)
        self.source_lines = s.splitlines(True)  # keep line endings for span extraction
        self.tokens = []  # a list of 2-tuples (token, list_of_expected_but_failed_tokens)
        self.pos = 0  # points to the next token, pos-1 points to the current token
        self.memos = {}  # per-stream memoization cache
        self._buffer = []  # Buffer for lookahead
        self.multiline_brackets = {}  # (line,col) -> original source for multi-line bracket groups
        self.farthest_pos = 0  # high-water mark for error reporting
        self._eager_tokenize()  # pre-load all tokens, strip NLs inside brackets

    def _eager_tokenize(self):
        """Pre-load all tokens and strip RichNL tokens inside bracket contexts.

        Python emits NL (blank) tokens inside ( [ { for implicit line continuation.
        These break the parser because it doesn't expect NL inside expressions.
        We strip them here, once, before parsing begins.
        """
        # Read all raw tokens into self.tokens via get_new_token (without this method active)
        while True:
            tok = self._get_raw_token()
            if tok is None:
                break
            # Process into RichNL or plain token (same logic as get_new_token)
            if tok.type == tkn.COMMENT:
                next_tok = self._peek_raw_token()
                if next_tok and next_tok.type in (tkn.NL, tkn.NEWLINE):
                    next_tok = self._get_raw_token()
                    rich_nl = RichNL(next_tok, [('comment', tok.string, tok.start[1])], is_blank=False)
                    self.tokens.append((rich_nl, []))
                else:
                    self.tokens.append((tok, []))
            elif tok.type == tkn.NL:
                self.tokens.append((RichNL(tok, [], is_blank=True), []))
            elif tok.type == tkn.NEWLINE:
                self.tokens.append((RichNL(tok, [], is_blank=False), []))
            elif tok.type == tkn.NAME and tok.string == "__TICK__":
                self.tokens.append((tkn.TokenInfo(TICK_TOKEN, "'", tok.start, tok.end, tok.line), []))
            elif tok.type == tkn.NAME and tok.string == "__DOLLAR__":
                self.tokens.append((tkn.TokenInfo(DOLLAR_TOKEN, "$", tok.start, tok.end, tok.line), []))
            elif tok.type == tkn.NAME and tok.string == "__HASH__":
                # $# — emitted as NAME("#") following DOLLAR_TOKEN
                self.tokens.append((tkn.TokenInfo(tkn.NAME, "#", tok.start, tok.end, tok.line), []))
            elif tok.type == tkn.NAME and tok.string == "__AT__":
                # $@ — emitted as NAME("@") following DOLLAR_TOKEN
                self.tokens.append((tkn.TokenInfo(tkn.NAME, "@", tok.start, tok.end, tok.line), []))
            elif tok.type == tkn.NAME and tok.string == "__BASH_TEST__":
                self.tokens.append((tkn.TokenInfo(BASH_TEST_TOKEN, "-", tok.start, tok.end, tok.line), []))
            elif tok.type == tkn.NAME and tok.string == "__BASH_NT__":
                self.tokens.append((tkn.TokenInfo(BASH_CMP_TOKEN, "-nt", tok.start, tok.end, tok.line), []))
            elif tok.type == tkn.NAME and tok.string == "__BASH_OT__":
                self.tokens.append((tkn.TokenInfo(BASH_CMP_TOKEN, "-ot", tok.start, tok.end, tok.line), []))
            elif tok.type == tkn.NAME and tok.string == "__RANGE__":
                self.tokens.append((tkn.TokenInfo(RANGE_TOKEN, "..", tok.start, tok.end, tok.line), []))
            elif tok.type == tkn.NAME and tok.string == "__RANGE_EXCL__":
                self.tokens.append((tkn.TokenInfo(RANGE_EXCL_TOKEN, "..<", tok.start, tok.end, tok.line), []))
            else:
                self.tokens.append((tok, []))
            if tok.type == 0:  # ENDMARKER
                break

        # Now strip RichNL tokens inside bracket depth > 0
        # and capture original source text for multi-line bracket groups
        bracket_stack = []  # stack of (open_tok, had_nl)
        depth = 0
        filtered = []
        for tok, meta in self.tokens:
            if hasattr(tok, 'string') and not isinstance(tok, RichNL):
                # Skip FSTRING_MIDDLE tokens: their string content is literal text
                # (e.g. '(' in f"({x})"), not actual bracket tokens.
                import token as _tok_mod
                _is_fstring_middle = hasattr(tok, 'type') and tok.type == _tok_mod.FSTRING_MIDDLE
                if not _is_fstring_middle and tok.string in ('(', '[', '{'):
                    depth += 1
                    bracket_stack.append((tok, False))
                elif not _is_fstring_middle and tok.string in (')', ']', '}'):
                    depth = max(0, depth - 1)
                    if bracket_stack:
                        open_tok, had_nl = bracket_stack.pop()
                        if had_nl:
                            self.multiline_brackets[open_tok.start] = \
                                self._extract_source_span(open_tok, tok)
            if depth > 0 and isinstance(tok, RichNL):
                if bracket_stack:
                    bracket_stack[-1] = (bracket_stack[-1][0], True)
                continue  # skip NLs inside brackets
            filtered.append((tok, meta))
        self.tokens = filtered

    def _extract_source_span(self, open_tok, close_tok):
        """Extract original source text from opening to closing bracket (inclusive)."""
        start_line, start_col = open_tok.start  # 1-based line
        end_line, end_col = close_tok.end        # 1-based line, end col is exclusive
        if start_line == end_line:
            return self.source_lines[start_line - 1][start_col:end_col]
        parts = [self.source_lines[start_line - 1][start_col:]]
        for i in range(start_line, end_line - 1):
            parts.append(self.source_lines[i])
        parts.append(self.source_lines[end_line - 1][:end_col])
        return ''.join(parts)

    def mark(self):
        return self.pos  # points to the next token!

    def reset(self, pos):
        self.pos = pos  # points to the next token!

    def _get_raw_token(self):
        """Get next raw token from the generator."""
        if self._buffer:
            return self._buffer.pop(0)
        try:
            return next(self.tokengen)
        except StopIteration:
            return None

    def _peek_raw_token(self):
        """Peek at next raw token without consuming."""
        tok = self._get_raw_token()
        if tok is not None:
            self._buffer.append(tok)
        return tok

    def get_new_token(self):
        """Return the next token from the pre-loaded token list."""
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
        """Return the text between given token position and current position."""
        return " ".join(tk[0].string for tk in self.tokens[pos : self.pos])

    ############## ERROR HANDLING #########################
    def get_farthest_token(self):
        """Return (token, expected_list) at the farthest position reached."""
        idx = min(self.farthest_pos, len(self.tokens) - 1)
        return self.tokens[idx]

    def format_error(self):
        """Format a user-friendly error message from the farthest failure point.

        Scans tokens near the farthest position to find the one with the most
        expected-token annotations, giving the most informative error message.
        """
        # Find the token with the richest expected-token info near farthest_pos
        best_idx = min(self.farthest_pos, len(self.tokens) - 1)
        best_expected = self.tokens[best_idx][1]
        # Search backwards from farthest_pos for the token with most expected info
        for i in range(best_idx, max(best_idx - 3, -1), -1):
            if i < len(self.tokens) and len(self.tokens[i][1]) > len(best_expected):
                best_idx = i
                best_expected = self.tokens[i][1]
        tok = self.tokens[best_idx][0]
        line, col = tok.start if hasattr(tok, 'start') else (0, 0)
        got = repr(tok.string) if hasattr(tok, 'string') and tok.string else tok.__class__.__name__
        msg = f"Parse error at line {line}, col {col}: got {got}"
        if best_expected:
            unique = sorted(set(best_expected))
            msg += f", expected one of: {', '.join(unique)}"
        return msg

    def set_failed_token(self, expected_token_as_string):
        # the current token is at position (self.pos-1)
        self.tokens[self.pos - 1][1].append(expected_token_as_string)

    def __iter__(self):
        return self

    def __next__(self):
        tok = self.get_new_token()
        if tok is None:
            raise StopIteration
        return tok

# --- Module-level context for current tokenizer ---
_current_tokenizer = None

def set_current_tokenizer(t):
    global _current_tokenizer
    _current_tokenizer = t

def get_multiline_brackets():
    if _current_tokenizer is not None:
        return getattr(_current_tokenizer, 'multiline_brackets', {})
    return {}

######################### HEK ADDITION ############################
def test_tokenizer(source):
    mytokenizer = Tokenizer(source)
    prev_line_number = -1
    while True:
        token = mytokenizer.get_new_token()
        if token is None:
            print("{:-^60s}".format(f"OUT"))
            break
        line_number = token.start[0]
        if line_number > prev_line_number:
            print("{:*^60s}".format(f" LINE {line_number} "))
        print(repr(token))
        if hasattr(token, 'type') and token.type == tkn.ENDMARKER:
            print("{:-^60s}".format(f"OUT"))
            break
        prev_line_number = line_number

def _tok_seq(source):
    """Return list of (type, string) pairs for all non-whitespace tokens."""
    t = Tokenizer(source)
    result = []
    while True:
        tok = t.get_new_token()
        if tok is None or tok.type == tkn.ENDMARKER:
            break
        if tok.type in (tkn.ENCODING, tkn.NEWLINE, tkn.NL, tkn.INDENT, tkn.DEDENT):
            continue
        if hasattr(tok, 'type'):
            result.append((tok.type, tok.string))
    return result


if __name__ == "__main__":
    import unittest

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
            # '-e' not preceded by if/elif/while/and/or/not/( — should NOT become BASH_TEST
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
            # '...' must NOT become a range token
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
            # '..<' must produce RANGE_EXCL_TOKEN, NOT RANGE_TOKEN + LT
            toks = _tok_seq("0..<5\n")
            types = [t for t, _ in toks]
            self.assertIn(RANGE_EXCL_TOKEN, types)
            self.assertNotIn(RANGE_TOKEN, types)

    unittest.main(verbosity=2)
