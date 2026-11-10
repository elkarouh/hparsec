
import re

from hparsec import (
    Grammar,
    ParserState,
    Terminals,
    expect_type,
    filt,
    literal,
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
# 2. Terminals
# ============================================================

reserved = {"and", "or", "not", "mod", "true", "false"}

class ExpressionTerminals(Terminals):
    number = expect_type(TOKEN_TYPES["NUMBER"])
    string = expect_type(TOKEN_TYPES["STRING"])
    boolean = literal("true") | literal("false")
    identifier = filt(
        lambda value: value not in reserved,
        expect_type(TOKEN_TYPES["IDENT"]),
    )

    # Ignored operators & delimiters (UPPERCASE = automatically ignored)
    EQ         = "="
    NE         = "/="
    LT         = "<"
    GT         = ">"
    LE         = "<="
    GE         = ">="
    LPAREN     = "("
    RPAREN     = ")"
    COMMA      = ","
    AND        = "and"
    OR         = "or"
    COMPARE_OP = NE | LE | GE | EQ | LT | GT

    # Visible operator tokens (lowercase = kept in AST for evaluate)
    add_op     = literal("+") | literal("-")
    mul_op     = literal("*") | literal("/") | literal("mod")
    unary_op   = literal("+") | literal("-") | literal("not")


# ============================================================
# 3. Grammar (avoids left-recursivity and therefore faster)
# ============================================================

class ExpressionGrammar(Grammar):
    expression = logical_or
    logical_or = logical_and + (OR + logical_and)[:]
    logical_and = comparison + (AND + comparison)[:]
    comparison = additive + ((COMPARE_OP + additive) | nothing)
    additive = multiplicative + (add_op + multiplicative)[:]
    multiplicative = unary + (mul_op + unary)[:]
    unary = (unary_op + primary) | primary
    group = LPAREN + expression + RPAREN
    primary = number | string | boolean | function_call | identifier | group
    function_call = identifier + LPAREN + (argument_list | nothing) + RPAREN
    argument_list = expression + (COMMA + expression)[:]

    # --------------------------------------------------------
    # AST Evaluation Methods
    # Grouped per-rule via inner class (zero @method decorators)
    # --------------------------------------------------------

    class number:
        """number ::= NUMBER"""
        def evaluate(self):
            val = float(self.node)
            return int(val) if val.is_integer() else val

    class additive:
        """additive ::= multiplicative (add_op multiplicative)*"""
        def evaluate(self):
            val = self.nodes[0].evaluate()
            if len(self.nodes) > 1 and self.nodes[1] is not None:
                for pair in self.nodes[1].nodes:
                    opr = pair.nodes[0].node
                    rhs = pair.nodes[1].evaluate()
                    if opr == "+":
                        val = val + rhs
                    elif opr == "-":
                        val = val - rhs
                    else:
                        raise ValueError(f"Unknown additive op: {opr!r}")
            return val

    class multiplicative:
        """multiplicative ::= unary (mul_op unary)*"""
        def evaluate(self):
            val = self.nodes[0].evaluate()
            if len(self.nodes) > 1 and self.nodes[1] is not None:
                for pair in self.nodes[1].nodes:
                    opr = pair.nodes[0].node
                    rhs = pair.nodes[1].evaluate()
                    if opr == "*":
                        val = val * rhs
                    elif opr == "/":
                        val = val / rhs
                    elif opr == "mod":
                        val = val % rhs
                    else:
                        raise ValueError(f"Unknown multiplicative op: {opr!r}")
            return val

    class unary:
        """unary ::= unary_op primary | primary"""
        def evaluate(self):
            if len(self.nodes) == 2:
                opr = self.nodes[0].node
                operand = self.nodes[1].evaluate()
                if opr == "+":
                    return +operand
                if opr == "-":
                    return -operand
                raise ValueError("Cannot evaluate 'not' in arithmetic context")
            return self.node.evaluate()

    class group:
        """group ::= LPAREN expression RPAREN"""
        def evaluate(self):
            return self.node.evaluate()

    class identifier:
        """identifier ::= IDENT, excluding reserved words"""
        def evaluate(self):
            raise ValueError(f"Cannot evaluate non-arithmetic identifier: {self.node}")

    class function_call:
        """function_call ::= identifier LPAREN (argument_list | nothing) RPAREN"""
        def evaluate(self):
            raise ValueError(f"Cannot evaluate non-arithmetic function call: {self.nodes[0].node}")


# ============================================================
# 4. Public entry point
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
# 5. Tests
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
        # Left-associativity stress tests
        "1 - 2 - 3",        # should be (1-2)-3 = -4, not 1-(2-3) = 2
        "8 / 4 / 2",        # should be (8/4)/2 = 1, not 8/(4/2) = 4
    ]

    print("--- Parsing Tests ---")
    for source in tests:
        try:
            ast = parse_expression(source)
            print("OK:", source)
        except Exception as exc:
            print("ERROR:", source, exc)

    print("\n--- Arithmetic Evaluation Tests ---")
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

