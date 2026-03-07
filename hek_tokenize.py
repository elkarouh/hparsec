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

    def __init__(self, s):
        self.tokengen = tokenize_string(s)
        self.tokens = []  # a list of 2-tuples (token, list_of_expected_but_failed_tokens)
        self.pos = 0  # points to the next token, pos-1 points to the current token
        self.memos = {}  # per-stream memoization cache
        self._buffer = []  # Buffer for lookahead
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
        depth = 0
        filtered = []
        for tok, meta in self.tokens:
            if hasattr(tok, 'string'):
                if tok.string in ('(', '[', '{'):
                    depth += 1
                elif tok.string in (')', ']', '}'):
                    depth = max(0, depth - 1)
            if depth > 0 and isinstance(tok, RichNL):
                continue  # skip NLs inside brackets
            filtered.append((tok, meta))
        self.tokens = filtered

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
        return self.tokens[-1]

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
