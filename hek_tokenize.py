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
import io


def tokenize_string(s):
    """Generator of tokens from the string"""
    return tkn.tokenize(io.BytesIO(s.encode("utf-8")).readline)


# NOTA: difference between NL and NEWLINE
# NEWLINE is used at the end of a LOGICAL line ( which may consist of several physical lines)
# NL is used at the end of a PHYSICAL line, e.g:
#   1.newlines that end lines that are continued after unclosed braces.
#   2.newlines that end empty lines or lines that only have comments.


class Tokenizer:
    """An enhanced tokenizer"""

    def __init__(self, s):
        self.tokengen = tokenize_string(s)
        self.tokens = []  # a list of 2-tuples (token, list_of_expected_but_failed_tokens)
        self.pos = 0  # points to the next token, pos-1 points to the current token
        self.memos = {}  # per-stream memoization cache
        self.trivia = {}  # {token_pos: [(kind, text, indent), ...]}
        self._trivia_buf = []  # buffer for collecting trivia between real tokens
        self._last_real_line = 0  # line number of last non-trivia token
        self.get_new_token_original = (
            self.get_new_token
        )  # saved for get_new_token_skip_trivia
        self._last_comment_line = (
            -1
        )  # line of last COMMENT token (to skip its trailing NL)

    def mark(self):
        return self.pos  # points to the next token!

    def reset(self, pos):
        self.pos = pos  # points to the next token!

    def get_new_token(self):
        if self.pos == len(self.tokens):
            self.tokens.append((next(self.tokengen), []))
        token = self.tokens[self.pos][0]
        self.pos += 1
        return token

    def get_new_token_skip_trivia(self):
        """Like get_new_token but skips COMMENT and NL tokens, buffering them as trivia.

        Trivia (comments and blank lines) is stored in self.trivia keyed by the
        position of the next real token. This allows trivia to be attached to
        AST nodes without modifying the parser grammar.

        Each trivia entry is a tuple: (kind, text, indent) where:
            kind:   'comment' | 'blank' | 'inline'
            text:   the comment string (e.g. '# foo') or '' for blanks
            indent: column offset (for preserving indentation)
        """
        while True:
            tok = self.get_new_token_original()
            if tok.type == tkn.COMMENT:
                self._last_comment_line = tok.start[0]
                if tok.start[0] == self._last_real_line and self._last_real_line > 0:
                    # Inline comment: same line as previous real token
                    self._trivia_buf.append(("inline", tok.string, tok.start[1]))
                else:
                    # Standalone comment
                    self._trivia_buf.append(("comment", tok.string, tok.start[1]))
            elif tok.type == tkn.NL:
                if tok.start[0] == self._last_comment_line:
                    # NL on same line as comment — skip it (part of the comment line)
                    pass
                else:
                    self._trivia_buf.append(("blank", "", 0))
            else:
                # Real token — flush buffered trivia
                if self._trivia_buf:
                    self.trivia[self.pos - 1] = self._trivia_buf
                    self._trivia_buf = []
                self._last_real_line = tok.start[0]
                return tok

    def peep_next_token(self):
        tok = self.get_new_token()
        self.pos -= 1
        return tok

    def get_current_token(self):
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
        return self.get_new_token()


######################### HEK ADDITION ############################
def test_tokenizer(source):
    mytokenizer = Tokenizer(source)
    prev_line_number = -1
    while True:
        token = mytokenizer.get_new_token()
        line_number = token.start[0]
        if line_number > prev_line_number:
            # print(f"************************** LINE {line_number} *****************************")
            print("{:*^60s}".format(f" LINE {line_number} "))
        print(repr(token))
        # print ("Current token",mytokenizer.current_token)
        if token.type == tkn.ENDMARKER:
            # print("OUT_______")
            print("{:-^60s}".format(f"OUT"))
            break
        prev_line_number = line_number
    # HEK ADDITION ####
    # print("$"*80)
    for tok in tokenize_string(source):
        print(repr(tok))


if __name__ == "__main__":
    pysrc1 = """
    /* comment 0 */
    for i in range(5): /* comment1 */
        print i /* comment2 */
    /* comment 3
    comment 4 */
    print /* comment 5 */
    /*comment 6 */
    a= ( 8,
    7)
    b=[9,
    10
    ]
    for i in range():
        for xc in fdf:
            for fsdf inmfdsd:
    pass
    """
    pysrc2 = """a not in d"""
    pysrc3 = """a-444.5"""
    pysrc4 = """mode=0666"""
    pysrc5 = """ur'dddd'"""
    pysrc6 = """largest = -1e10"""
    pysrc7 = """a(...,4, **b)"""
    pysrc8 = """
#comment 0
for i in range(5): # comment1
    #comment 1.1
    print "HELLO" # comment2
#comment 3
#comment 4
'''
multiline1
multiline2
'''
print # comment 5
#comment 6
a= ( 8, # comment 7
# comment 8
    7)
continued=head\
tail
$b=[999_999,
    +10e-3]
b **= -0x44
if a not in b: f'aaaa' r"bbb" rf"ccc" '''ddd''' r'''eee''' f'''zzz'''
"""
    pysrc9 = """
#comment 0
for i in range(5): # comment1
    #comment 1.1
    #comment 1.2

    print "HELLO" # comment2
#comment 3
#comment 4
"""

    pysrc10 = """ # BUG remove last paren and it crashes !!!
func(args()-> func(args()->int))
"""

    pysrc11 = "$eee=123.44e8+3j"
    pysrc12 = "for x in range(5**2):"
    pysrc13 = """\
def fullName(): # this is a same-line comment
# this is a comment at level 0 but it shows at level 1 !!!
    # this is a comment at level1
    print ...
    return self._fullName
    """
    pysrc14 = "@static"
    code = dedent("""
    for i in 1..5:
        myvar:MYTYPE
        total := total | price * quantity;
        if X:
            tax := price * 0.05;
    """)

    # NL is only used after plain-line comments and within brackets spread over more than 1 line
    # The NEWLINE token indicates the end of a logical line of Python code;
    # NL tokens are generated when a logical line of code is continued over multiple physical lines.
    # prev_token = Token(77,0, 0, (0, 0), (0, 0), 0)
    source = code

    # source="7kg"
    if 0:
        print(source)
        print("-----------------------------------------------------")
        print("{:-^60s}".format("///"))
    test_tokenizer(source)
