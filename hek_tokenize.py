import tokenize as tkn
from textwrap import dedent

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

    # Tick-attribute pattern: Name'Attr  ->  Name__tick__Attr
    # Must be applied before Python tokenization since ' is a string delimiter.
    import re as _re
    _TICK_RE = _re.compile(r"(\b[A-Za-z_]\w*)'([A-Za-z_]\w*)")

    # Range-operator patterns: the issue is that Python's tokenizer greedily
    # merges a digit adjacent to '.' into a float literal, so:
    #   '0..10'  ->  NUMBER('0.')  NUMBER('.10')   (broken)
    #   'x..10'  ->  NAME('x')  OP('.')  NUMBER('.10')  (broken)
    #   '0..y'   ->  NUMBER('0.')  OP('.')  NAME('y')   (broken)
    # We insert a space on each side of '..' / '..<' when a digit is adjacent,
    # before Python's tokenizer ever sees the source.
    #   Pass 1:  digit immediately before '..' -> insert space between them
    #   Pass 2:  digit immediately after  '..' -> insert space between them
    _RANGE_LEFT_RE  = _re.compile(r'(\d)(\.\.<?)')   # '0..'  -> '0 ..'
    _RANGE_RIGHT_RE = _re.compile(r'(\.\.<?)(\d)')   # '..10' -> '.. 10'

    # Bashism patterns: rewrite bash-style argument/environment variables to
    # safe identifier placeholders before Python's tokenizer sees them.
    #
    #   $#        -> __bash_argc__   (must come before $<digit> to beat '#' comment)
    #   $@        -> __bash_args__
    #   $0        -> __bash_arg0__
    #   $1..$9    -> __bash_arg1__ .. __bash_arg9__
    #   $NAME     -> __bash_env_NAME__   (uppercase env var name)
    #
    # '$#' is the most dangerous: Python lexes '#' as a comment start, eating
    # everything after '$' to end-of-line.  The regex replaces the whole '$#'
    # before the tokenizer gets a chance to see it.
    _BASH_ARGC_RE = _re.compile(r'\$#')
    _BASH_ARGS_RE = _re.compile(r'\$@')
    _BASH_ARG_RE  = _re.compile(r'\$([0-9])')
    _BASH_ENV_RE  = _re.compile(r'\$([A-Z_][A-Z0-9_]*)')

    # Bash file-test operators: '-e FILE', '-f FILE', etc.
    # Must be preceded by whitespace or start-of-line, and followed by a space,
    # so we never confuse with subtraction or negative numbers.
    _BASH_FILE_TEST_RE = _re.compile(r'(?:^|(?<=\s)|(?<=\())-([efdLrwxscbpS])(?=\s)')
    # Bash file-comparison operators: FILE1 -nt FILE2 / FILE1 -ot FILE2
    # Only match '-nt' and '-ot' surrounded by whitespace.
    _BASH_FILE_NT_RE = _re.compile(r'(?<=\s)-nt(?=\s)')
    _BASH_FILE_OT_RE = _re.compile(r'(?<=\s)-ot(?=\s)')

    @staticmethod
    def _preprocess_file_tests(s):
        """Replace bash file-test operators with safe identifier placeholders.

        Mapping::

            -e FILE  -> __bash_test_e__ FILE
            -f FILE  -> __bash_test_f__ FILE
            -d FILE  -> __bash_test_d__ FILE
            -L FILE  -> __bash_test_L__ FILE
            -r FILE  -> __bash_test_r__ FILE
            -w FILE  -> __bash_test_w__ FILE
            -x FILE  -> __bash_test_x__ FILE
            -s FILE  -> __bash_test_s__ FILE
            -c FILE  -> __bash_test_c__ FILE
            -b FILE  -> __bash_test_b__ FILE
            -p FILE  -> __bash_test_p__ FILE
            -S FILE  -> __bash_test_S__ FILE
            -nt      -> __bash_nt__
            -ot      -> __bash_ot__
        """
        import re as _re2
        # Split into alternating non-string / string-literal+comment segments and only
        # apply substitutions outside strings and comments.
        _STR_RE = _re2.compile(r'("""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\'|"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'|#[^\n]*)')
        parts = _STR_RE.split(s)
        for i in range(0, len(parts), 2):  # even indices are outside strings
            parts[i] = Tokenizer._BASH_FILE_TEST_RE.sub(r'__bash_test_\1__', parts[i])
            parts[i] = Tokenizer._BASH_FILE_NT_RE.sub('__bash_nt__', parts[i])
            parts[i] = Tokenizer._BASH_FILE_OT_RE.sub('__bash_ot__', parts[i])
        return ''.join(parts)

    @staticmethod
    def _preprocess_bashisms(s):
        """Replace bash-style special variables with safe identifier placeholders.

        The substitutions are reversed in to_py() / to_nim() on the IDENTIFIER
        nodes that carry these placeholder strings.

        Mapping::

            $#        -> __bash_argc__
            $@        -> __bash_args__
            $0        -> __bash_arg0__
            $1 .. $9  -> __bash_arg1__ .. __bash_arg9__
            $NAME     -> __bash_env_NAME__   (all-caps env var names)

        The order of substitutions matters: ``$#`` must be replaced first
        because Python's tokenizer would otherwise consume ``#`` and
        everything following it as a comment.
        """
        s = Tokenizer._BASH_ARGC_RE.sub('__bash_argc__', s)
        s = Tokenizer._BASH_ARGS_RE.sub('__bash_args__', s)
        s = Tokenizer._BASH_ARG_RE.sub(r'__bash_arg\1__', s)
        s = Tokenizer._BASH_ENV_RE.sub(r'__bash_env_\1__', s)
        return s

    @staticmethod
    def _preprocess_range_operators(s):
        """Insert spaces around '..' and '..<' when a digit is directly adjacent.

        Python's tokenizer merges digits and dots into floats (e.g. '0.' and
        '.10'), which breaks range literals written without spaces.  Two regex
        passes cover all problem combinations::

            0..10   -> 0 .. 10
            0..<10  -> 0 ..< 10
            x..10   -> x.. 10
            0..y    -> 0 ..y    (right side fine: '..y' = OP OP NAME)
            x..y    -> x..y     (both sides fine already)
        """
        s = Tokenizer._RANGE_LEFT_RE.sub(r'\1 \2', s)
        s = Tokenizer._RANGE_RIGHT_RE.sub(r'\1 \2', s)
        return s

    @staticmethod
    def _preprocess_tick_attributes(s):
        """Replace Ada-style tick attributes (e.g. Type'First) with
        Type__tick__First so that Python's tokenizer can handle them.
        Only applies outside string literals."""
        import re as _re2
        # Split on double-quoted strings and comments only (single-quoted strings
        # are NOT split here because word'word tick attributes look like string starts).
        # Apply tick substitution only in code segments.
        # String prefixes (b, f, r, u, rb, etc.) are handled by excluding them in _tick_sub.
        _DQ_CMT_RE = _re2.compile(r'("""[\s\S]*?"""|"(?:[^"\\]|\\.)*"|#[^\n]*)')
        _STRING_PREFIXES = frozenset(['b','B','f','F','r','R','u','U',
                                      'rb','rB','Rb','RB','br','bR','Br','BR',
                                      'fr','fR','Fr','FR','rf','rF','Rf','RF'])
        def _tick_sub(m):
            if m.group(1) in _STRING_PREFIXES:
                return m.group(0)
            return m.group(1) + '__tick__' + m.group(2)
        parts = _DQ_CMT_RE.split(s)
        for i in range(0, len(parts), 2):
            parts[i] = Tokenizer._TICK_RE.sub(_tick_sub, parts[i])
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
            if hasattr(tok, 'string'):
                if tok.string in ('(', '[', '{'):
                    depth += 1
                    bracket_stack.append((tok, False))
                elif tok.string in (')', ']', '}'):
                    depth = max(0, depth - 1)
                    if bracket_stack:
                        open_tok, had_nl = bracket_stack.pop()
                        if had_nl:
                            self.multiline_brackets[open_tok.start] =                                 self._extract_source_span(open_tok, tok)
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

if __name__ == "__main__":
    # Test cases for the three issues

    print("="*60)
    print("TEST 1: Blank lines between statements")
    print("="*60)
    pysrc1 = """x = 1

y = 2
"""
    test_tokenizer(pysrc1)

    print("\n" + "="*60)
    print("TEST 2: Inline comments")
    print("="*60)
    pysrc2 = """x = 1  # inline
y = 2
"""
    test_tokenizer(pysrc2)

    print("\n" + "="*60)
    print("TEST 3: Multiple blank lines")
    print("="*60)
    pysrc3 = """# header

import os

def f():
    pass
"""
    test_tokenizer(pysrc3)
