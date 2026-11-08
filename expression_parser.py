
import re

from hek_parsec import (
    Parser, ParserState, fw, filt, fmap, ignore, shift,
    expect, expect_type, literal, nothing,
    sequence, choice,
)

# ============================================================
# 1. Small ad-hoc tokenizer
# ============================================================

class Token:
    def __init__(self, type, string, start=(1, 0), end=(1, 0), line=""):
        self.type = type
        self.string = string
        self.start = start
        self.end = end
        self.line = line

    def __repr__(self):
        return f"Token({self.type!r}, {self.string!r}, {self.start!r})"

TOKEN_SPEC = [
    ("NUMBER",   r"\d+(?:\.\d+)?"),
    ("STRING",   r'"(?:[^"\\]|\\.)*"'),
    ("IDENT",    r"[A-Za-z][A-Za-z0-9_]*"),
    ("OP",       r"/=|<=|>=|[+\-*/=<>(),]"),
    ("SKIP",     r"[ \t\r\n]+"),
]

TOKEN_RE = re.compile(
    "|".join(f"(?P<{name}>{pattern})"
             for name, pattern in TOKEN_SPEC)
)

TOKEN_TYPES = {
    "NUMBER": 1,
    "STRING": 2,
    "IDENT":  3,
    "OP":     4,
}

def tokenize(source):
    tokens = []
    line = 1
    column = 0

    for match in TOKEN_RE.finditer(source):
        kind = match.lastgroup
        value = match.group()

        if kind == "SKIP":
            newlines = value.count("\n")
            if newlines:
                line += newlines
                column = len(value.rsplit("\n", 1)[-1])
            else:
                column += len(value)
            continue

        if kind is None:
            raise SyntaxError(
                f"Invalid token at line {line}, column {column}"
            )

        start = (line, column)
        end = (line, column + len(value))
        tokens.append(Token(TOKEN_TYPES[kind], value, start, end, source))
        column += len(value)

    # Detect characters not matched by the tokenizer.
    consumed = "".join(m.group() for m in TOKEN_RE.finditer(source))
    if consumed != source:
        raise SyntaxError("Invalid character in expression")

    return tokens


# ============================================================
# 2. Token parser helpers
# ============================================================

def keyword(word):
    return literal(word)

def operator(value):
    return literal(value)

def token_type(ty):
    return expect_type(ty)


def ignored(p):
    return ignore(p)


# ============================================================
# 3. Terminals
# ============================================================

number = token_type(TOKEN_TYPES["NUMBER"])
string = token_type(TOKEN_TYPES["STRING"])

boolean = keyword("true") | keyword("false")

reserved = {"and", "or", "not", "mod", "true", "false"}

identifier = filt(
    lambda value: value not in reserved,
    token_type(TOKEN_TYPES["IDENT"]),
)

# Operators
OR = ignored(keyword("or"))
AND = ignored(keyword("and"))
NOT = ignored(keyword("not"))
MOD = ignored(keyword("mod"))

PLUS = ignored(operator("+"))
MINUS = ignored(operator("-"))
MUL = ignored(operator("*"))
DIV = ignored(operator("/"))

EQ = ignored(operator("="))
NE = ignored(operator("/="))
LT = ignored(operator("<"))
GT = ignored(operator(">"))
LE = ignored(operator("<="))
GE = ignored(operator(">="))

LPAREN = ignored(operator("("))
RPAREN = ignored(operator(")"))
COMMA = ignored(operator(","))

compare_op = NE | LE | GE | EQ | LT | GT
add_op = PLUS | MINUS
mul_op = MUL | DIV | MOD
unary_op = PLUS | MINUS | NOT


# ============================================================
# 4. Forward declarations
# ============================================================

expression = fw("expression")
logical_or = fw("logical_or")
logical_and = fw("logical_and")
comparison = fw("comparison")
additive = fw("additive")
multiplicative = fw("multiplicative")
unary = fw("unary")
primary = fw("primary")
function_call = fw("function_call")
argument_list = fw("argument_list")


# ============================================================
# 5. Grammar
# ============================================================

expression = logical_or

logical_or = logical_and + (OR + logical_and)[:]

logical_and = comparison + (AND + comparison)[:]

comparison = additive + ((compare_op + additive) | nothing)

additive = multiplicative + (add_op + multiplicative)[:]

multiplicative = unary + (mul_op + unary)[:]

unary = (unary_op + primary) | primary

primary = (
    number
    | string
    | boolean
    | function_call
    | identifier
    | (LPAREN + expression + RPAREN)
)

function_call = (
    identifier
    + LPAREN
    + (argument_list | nothing)
    + RPAREN
)

argument_list = expression + (COMMA + expression)[:]


# ============================================================
# 6. Public entry point
# ============================================================

def parse_expression(source):
    ParserState.reset()

    tokens = tokenize(source)
    result = expression.parse(tokens)

    if not result:
        raise SyntaxError(f"Invalid expression: {source}")

    ast, stream = result

    if stream.pos != len(stream.tokens):
        token = stream.tokens[stream.pos]
        raise SyntaxError(
            f"Unexpected token {token.string!r} "
            f"at position {token.start}"
        )

    return ast


# ============================================================
# 7. Tests
# ============================================================

if __name__ == "__main__":
    tests = [
        "1 + 2 * 3",
        "(1 + 2) * 3",
        "a + b * c - d",
        "not a and b or c",
        "x >= 10",
        "x /= 0",
        "foo(1, 2, 3)",
        "foo(a + b, bar(2))",
        "true or false and not false",
        "-a * +b",
        "a mod 3",
    ]

    for source in tests:
        try:
            ast = parse_expression(source)
            print("OK:", source)
            print(ast)
        except Exception as exc:
            print("ERROR:", source, exc)

