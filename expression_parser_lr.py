
import re

from hek_parsec import (
    ParserState,
    expect_type,
    filt,
    fw,
    ignore,
    literal,
    method,
    nothing,
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
    ("OP",       r"/=|<=|>=|[+\-*/=<>(),]"),   # no space in char-class
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
        end   = (line, column + len(value))
        tokens.append(Token(TOKEN_TYPES[kind], value, start, end, source))
        column += len(value)

    # Reject any character not covered by the spec.
    consumed = "".join(m.group() for m in TOKEN_RE.finditer(source))
    if consumed != source:
        raise SyntaxError("Invalid character in expression")

    return tokens


# ============================================================
# 2. Token parser helpers
# ============================================================

def op(symbol):
    """Match and ignore an operator or keyword token."""
    return ignore(literal(symbol))


# ============================================================
# 3. Terminals
# ============================================================

number = expect_type(TOKEN_TYPES["NUMBER"])
string = expect_type(TOKEN_TYPES["STRING"])
boolean = literal("true") | literal("false")

reserved = {"and", "or", "not", "mod", "true", "false"}

identifier = filt(
    lambda value: value not in reserved,
    expect_type(TOKEN_TYPES["IDENT"]),
)

# Ignored operator tokens, (consumed but not kept in the AST)
# by convention, we use UPPERCASE 
EQ    = op("=")
NE    = op("/=")
LT    = op("<")
GT    = op(">")
LE    = op("<=")
GE    = op(">=")

LPAREN = op("(")
RPAREN = op(")")
COMMA  = op(",")
AND    = op("and")
OR     = op("or")

COMPARE_OP = NE | LE | GE | EQ | LT | GT

# Visible operator tokens (kept in the AST for evaluate() dispatch)
# These use literal() without ignore() so evaluate() can read self.nodes[1].node.
add_op  = literal("+") | literal("-")
mul_op  = literal("*") | literal("/") | literal("mod")
unary_op = literal("+") | literal("-") | literal("not")


# ============================================================
# 4. Forward declarations
# ============================================================

expression    = fw("expression")
logical_or    = fw("logical_or")
logical_and   = fw("logical_and")
comparison    = fw("comparison")
additive      = fw("additive")
multiplicative = fw("multiplicative")
unary         = fw("unary")
primary       = fw("primary")
function_call = fw("function_call")
argument_list = fw("argument_list")

# ============================================================
# 5. Left-recursive grammar
#
# Every binary-operator level is written as a **direct** left recursion in a single Choice_Parser:
#
#   additive = additive add_op multiplicative   <- LR case
#            | multiplicative                   <- base case
#
# The binary operators are kept VISIBLE (not ignored) so that
# the @method evaluate() can dispatch on self.nodes[1].node.
#
# hek_parsec resolves LR via the Warth/Erdweg/Rompf seed-growing algorithm, so no stack overflow occurs.
# ============================================================

expression = logical_or
logical_or = (logical_or + OR + logical_and) | logical_and
logical_and = (logical_and + AND + comparison) | comparison
# comparison is non-associative: only one optional RHS allowed.
# Written without left-recursion to enforce that.
comparison = additive + ((COMPARE_OP + additive) | nothing)
additive = (additive + add_op + multiplicative) | multiplicative
multiplicative = (multiplicative + mul_op + unary) | unary
unary = (unary_op + primary) | primary # unary is right-recursive by nature
group = LPAREN + expression + RPAREN
primary = number | string | boolean | function_call | identifier | group
function_call = identifier + LPAREN + (argument_list | nothing) + RPAREN
argument_list = (argument_list + COMMA + expression) | expression

# ============================================================
# 6. AST Evaluation Methods (via @method)
#
# For Choice_Parser rules (additive, multiplicative, unary),
# @method automatically distributes to the Sequence_Parser binary
# alternative — the only case that gets instantiated as an AST node.
# The passthrough / base case delegates through Parser.evaluate().
# ============================================================

@method(number)
def evaluate(self):
    val = float(self.node)
    return int(val) if val.is_integer() else val

@method(additive)
def evaluate(self):
    # nodes = [lhs, op_literal, rhs]  (binary case only)
    lhs = self.nodes[0].evaluate()
    opr = self.nodes[1].node   # '+' or '-'
    rhs = self.nodes[2].evaluate()
    if opr == "+":
        return lhs + rhs
    if opr == "-":
        return lhs - rhs
    raise ValueError(f"Unknown additive op: {opr!r}")

@method(multiplicative)
def evaluate(self):
    # nodes = [lhs, op_literal, rhs]  (binary case only)
    lhs = self.nodes[0].evaluate()
    opr = self.nodes[1].node   # '*', '/', or 'mod'
    rhs = self.nodes[2].evaluate()
    if opr == "*":
        return lhs * rhs
    if opr == "/":
        return lhs / rhs
    if opr == "mod":
        return lhs % rhs
    raise ValueError(f"Unknown multiplicative op: {opr!r}")

@method(unary)
def evaluate(self):
    # nodes = [op_literal, operand]  (prefix case only)
    opr     = self.nodes[0].node   # '+' or '-'
    operand = self.nodes[1].evaluate()
    if opr == "+":
        return +operand
    if opr == "-":
        return -operand
    raise ValueError(f"Cannot evaluate 'not' in arithmetic context")

@method(group)
def evaluate(self):
    return self.node.evaluate()

@method(identifier)
def evaluate(self):
    raise ValueError(f"Cannot evaluate non-arithmetic identifier: {self.node}")

@method(function_call)
def evaluate(self):
    raise ValueError(f"Cannot evaluate non-arithmetic function call: {self.nodes[0].node}")


# ============================================================
# 7. Public entry point
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


def evaluate_expression(source):
    """Parse and evaluate a pure arithmetic expression."""
    ast = parse_expression(source)
    return ast.evaluate()


# ============================================================
# 8. Tests
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
        # Extra: left-associativity stress tests
        "1 - 2 - 3",        # should be (1-2)-3, not 1-(2-3)
        "8 / 4 / 2",        # should be (8/4)/2 = 1, not 8/(4/2) = 4
        "a or b or c",
        "a and b and c",
        "foo(1, 2, 3, 4, 5)",
    ]

    print("--- Parsing Tests ---")
    for source in tests:
        try:
            ast = parse_expression(source)
            print("OK:", source)
        except Exception as exc:
            print("ERROR:", source, exc)

    print("\n--- Arithmetic Evaluation Tests (via @method) ---")
    arithmetic_tests = [
        ("1 + 2 * 3", 7),
        ("(1 + 2) * 3", 9),
        ("10 - 4 - 2", 4),
        ("8 / 4 / 2", 1.0),
        ("20 / 2 * 5", 50.0),
        ("-5 * +3", -15),
        ("14 mod 4", 2),
        ("((2 + 3) * (4 - 1)) / 3", 5.0),
        ("100 - 50 + 25 - 10", 65),
    ]

    for expr_str, expected in arithmetic_tests:
        val = evaluate_expression(expr_str)
        assert val == expected, f"Expected {expected}, got {val}"
        print(f"  {expr_str} = {val}  (expected {expected}) -> OK")
