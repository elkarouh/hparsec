"""A small BASIC interpreter built on hparsec: a proof of concept.

Supported: LET assignment, PRINT, single-line functions (DEF FN ... = expression),
function calls (FN name(args)), numbers, strings, + - * /, unary minus, parentheses
and ' comments. Variables are global; a function body sees its parameters and the
global variables.

Design: every grammar rule is a class whose docstring gives its EBNF rule. A rule's
run() (statements) or evaluate() (expressions) handles only that node and reads its
children from self.nodes (self.node is the first one).

Usage:
    python3 basic_interpreter.py program.bas
"""

import re
import sys

from hparsec import (
    Grammar,
    ParserState,
    Terminals,
    expect_type,
    literal,
    nothing,
    SymbolTable,
)

KEYWORDS = {"LET", "PRINT", "DEF", "FN"}

TOKEN_SPEC = [
    ("NUMBER",  r"\d+(?:\.\d+)?"),
    ("STRING",  r'"[^"\n]*"'),
    ("IDENT",   r"[A-Za-z][A-Za-z0-9_]*"),
    ("OP",      r"[-+*/=(),]"),
    ("NEWLINE", r"\n"),
    ("COMMENT", r"'[^\n]*"),
    ("SKIP",    r"[ \t\r]+"),
]
TOKEN_RE = re.compile("|".join(f"(?P<{name}>{pattern})" for name, pattern in TOKEN_SPEC))

TOKEN_TYPES = {"NUMBER": 1, "STRING": 2, "IDENT": 3, "KEYWORD": 4, "OP": 5, "NEWLINE": 6}


class BasicError(Exception):
    """An error in the BASIC program: a syntax error, or a run-time error."""


class Token:
    def __init__(self, type, string, line):
        self.type = type
        self.string = string
        self.line = line

    def __repr__(self):
        return f"Token({self.type!r}, {self.string!r}, line {self.line})"


def tokenize(source):
    """Split source into tokens. Keywords are upper-cased; comments are dropped."""
    tokens = []
    line = 1
    pos = 0
    while pos < len(source):
        match = TOKEN_RE.match(source, pos)
        if match is None:
            raise BasicError(f"line {line}: unexpected character {source[pos]!r}")
        kind, text = match.lastgroup, match.group()
        pos = match.end()
        if kind in ("SKIP", "COMMENT"):
            continue
        if kind == "NEWLINE":
            tokens.append(Token(TOKEN_TYPES["NEWLINE"], "\n", line))
            line += 1
        elif kind == "IDENT" and text.upper() in KEYWORDS:
            tokens.append(Token(TOKEN_TYPES["KEYWORD"], text.upper(), line))
        else:
            tokens.append(Token(TOKEN_TYPES[kind], text, line))
    if not tokens or tokens[-1].type != TOKEN_TYPES["NEWLINE"]:
        tokens.append(Token(TOKEN_TYPES["NEWLINE"], "\n", line))
    return tokens


def _number(text):
    return float(text) if "." in text else int(text)


def _text(value):
    """How PRINT shows a value: whole numbers without a decimal point."""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


class Environment:
    """The state of one run, kept in hparsec's SymbolTable.

    The table's stack holds the globals scope, and while a function body runs, one
    frame for its parameters on top of it. Variables have kind "var" (LET) or "param"
    (a function parameter), and functions have kind "func". A symbol's "value" holds
    the variable's value, or (parameters, body) for a function.
    """

    MAX_CALL_DEPTH = 50

    def __init__(self):
        self.symbols = SymbolTable()
        self.symbols.push_scope("globals")
        self.output = []
        self.depth = 0

    def set(self, name, value):
        """LET: assign a global variable."""
        self.symbols.add(name, kind="var", value=value)

    def get(self, name):
        symbol = self.symbols.lookup(name)
        if symbol is None or symbol["kind"] not in ("var", "param"):
            raise BasicError(f"undefined variable {name}")
        return symbol["value"]

    def define(self, name, params, body):
        """DEF FN: functions live in the same table under the key FN:name."""
        self.symbols.add(f"FN:{name}", kind="func", value=(params, body))

    def call(self, name, args):
        symbol = self.symbols.lookup(f"FN:{name}")
        if symbol is None:
            raise BasicError(f"undefined function FN {name}")
        params, body = symbol["value"]
        if len(params) != len(args):
            raise BasicError(f"FN {name} takes {len(params)} argument(s), got {len(args)}")
        if self.depth >= self.MAX_CALL_DEPTH:
            raise BasicError(f"FN {name}: more than {self.MAX_CALL_DEPTH} nested calls (recursion is not supported)")
        # The body sees the globals and its own parameters only, not the caller's frame.
        saved = self.symbols.stack
        frame = {"name": f"FN {name}", "symbols": {
            param: {"type": None, "kind": "param", "value": value} for param, value in zip(params, args)}}
        self.symbols.stack = [saved[0], frame]
        self.depth += 1
        try:
            return body.evaluate(self)
        finally:
            self.depth -= 1
            self.symbols.stack = saved


def _arithmetic(left, op, right):
    try:
        if op == "+":
            return left + right
        if op == "-":
            return left - right
        if op == "*":
            return left * right
        if op == "/":
            return left / right
    except ZeroDivisionError:
        raise BasicError("division by zero") from None
    except TypeError:
        raise BasicError(f"cannot apply {op} to {left!r} and {right!r}") from None
    raise BasicError(f"unknown operator {op!r}")


# ============================================================
# Terminals
# ============================================================

class BasicTerminals(Terminals):
    number = expect_type(TOKEN_TYPES["NUMBER"])
    string = expect_type(TOKEN_TYPES["STRING"])
    identifier = expect_type(TOKEN_TYPES["IDENT"])

    # Uppercase terminals are ignored in the tree
    LET = literal("LET")
    PRINT = literal("PRINT")
    DEF = literal("DEF")
    FN = literal("FN")
    NEWLINE = expect_type(TOKEN_TYPES["NEWLINE"])
    EQ = literal("=")
    LPAREN = literal("(")
    RPAREN = literal(")")
    COMMA = literal(",")

    # Lowercase operators are kept in the tree
    add_op = literal("+") | literal("-")
    mul_op = literal("*") | literal("/")
    unary_op = literal("-")


# ============================================================
# Grammar
# ============================================================

class BasicGrammar(Grammar):
    program = line[:]
    line = (statement | nothing) + NEWLINE
    statement = let_stmt | print_stmt | def_stmt
    let_stmt = LET + identifier + EQ + expression
    print_stmt = PRINT + (arguments | nothing)
    def_stmt = DEF + FN + identifier + LPAREN + (parameters | nothing) + RPAREN + EQ + expression
    parameters = identifier + (COMMA + identifier)[:]
    arguments = expression + (COMMA + expression)[:]
    expression = term + (add_op + term)[:]
    term = factor + (mul_op + factor)[:]
    factor = negation | primary
    negation = unary_op + factor
    primary = number | string | fn_call | identifier | group
    group = LPAREN + expression + RPAREN
    fn_call = FN + identifier + LPAREN + (arguments | nothing) + RPAREN

    # statement, factor and primary are choices: the node is the alternative that
    # matched, so they need no methods of their own.

    class program:
        """program ::= line*"""
        def run(self, env):
            for line in self.nodes:
                line.run(env)

    class line:
        """line ::= (statement | nothing) NEWLINE"""
        def run(self, env):
            for statement in self.nodes:
                statement.run(env)

    class let_stmt:
        """let_stmt ::= LET identifier EQ expression"""
        def run(self, env):
            name, value = self.nodes
            env.set(name.node, value.evaluate(env))

    class print_stmt:
        """print_stmt ::= PRINT (arguments | nothing)"""
        def run(self, env):
            arg_list=[]
            if self.nodes:
                arg_list = self.nodes[0].values(env)                       
            env.output.append(" ".join(_text(arg) for arg in arg_list))

    class def_stmt:
        """def_stmt ::= DEF FN identifier LPAREN (parameters | nothing) RPAREN EQ expression"""
        def run(self, env):
            name, *parameters, body = self.nodes
            param_list= parameters[0].names() if parameters else []
            env.define(name.node, param_list, body)

    class parameters:
        """parameters ::= identifier (COMMA identifier)*"""
        def names(self):
            first_param_node = self.nodes[0]  
            other_params_list=[]
            if self.nodes[1:]:
                other_params_node=self.nodes[1]                  
                other_params_list = [other_param.node.node for other_param in other_params_node.nodes]
            return [first_param_node.node] + other_params_list

    class arguments:
        """arguments ::= expression (COMMA expression)*"""
        def values(self, env):
            first_arg_node = self.nodes[0]
            other_args_list = []
            if self.nodes[1:]:
                other_args_node=self.nodes[1]
                other_args_list = [other_arg.node.evaluate(env) for other_arg in other_args_node.nodes]
            return [first_arg_node.evaluate(env)] + other_args_list

    class expression:
        """expression ::= term (add_op term)*"""
        def evaluate(self, env):
            value = self.nodes[0].evaluate(env)
            for more in self.nodes[1:]:
                for pair in more.nodes:
                    operator, operand = pair.nodes
                    left, op, right = value, operator.node, operand.evaluate(env)
                    try:
                        if op == "+":
                            value = left + right
                        elif op == "-":
                            value = left - right
                        else:
                            raise BasicError(f"unknown operator {op!r}")
                    except TypeError:
                        raise BasicError(f"cannot apply {op} to {left!r} and {right!r}") from None
            return value

    class term:
        """term ::= factor (mul_op factor)*"""
        def evaluate(self, env):
            value = self.nodes[0].evaluate(env)
            for more in self.nodes[1:]:
                for pair in more.nodes:
                    operator, operand = pair.nodes
                    left, op, right = value, operator.node, operand.evaluate(env)
                    try:
                        if op == "*":
                            value = left * right
                        elif op == "/":
                            value = left / right
                        else:
                            raise BasicError(f"unknown operator {op!r}")
                    except ZeroDivisionError:
                        raise BasicError("division by zero") from None
                    except TypeError:
                        raise BasicError(f"cannot apply {op} to {left!r} and {right!r}") from None
            return value

    class negation:
        """negation ::= unary_op factor"""
        def evaluate(self, env):
            return -self.nodes[1].evaluate(env)

    class number:
        def evaluate(self, env):
            return _number(self.node)

    class string:
        def evaluate(self, env):
            return self.node[1:-1]

    class identifier:
        def evaluate(self, env):
            return env.get(self.node)

    class group:
        """group ::= LPAREN expression RPAREN"""
        def evaluate(self, env):
            return self.node.evaluate(env)

    class fn_call:
        """fn_call ::= FN identifier LPAREN (arguments | nothing) RPAREN"""
        def evaluate(self, env):
            name = self.nodes[0]
            arg_list=[]
            if self.nodes[1:]:
                arg_list = self.nodes[1].values(env)
            return env.call(name.node, arg_list)


# ============================================================
# Entry points
# ============================================================

def run(source):
    """Run a BASIC program and return its output lines."""
    ParserState.reset()
    result = program.parse(tokenize(source))
    if not result:
        raise BasicError("syntax error")
    ast, stream = result
    if stream.pos != len(stream.tokens):
        token = stream.tokens[stream.pos]
        raise BasicError(f"syntax error at {token.string!r} on line {token.line}")
    env = Environment()
    ast.run(env)
    return env.output


# ============================================================
# Self-tests
# ============================================================

if __name__ == "__main__":
    if len(sys.argv) > 1:
        with open(sys.argv[1], encoding="utf-8") as handle:
            try:
                output = run(handle.read())
            except BasicError as exc:
                print(f"error: {exc}", file=sys.stderr)
                sys.exit(1)
        print("\n".join(output))
        sys.exit(0)

    cases = [
        ('LET X = 2\nPRINT X * 3\n', ["6"]),
        ('PRINT 1 + 2 * 3\n', ["7"]),
        ('PRINT (1 + 2) * 3\n', ["9"]),
        ('PRINT -2 * 3\n', ["-6"]),
        ('PRINT 8 / 4 / 2\n', ["1"]),
        ('PRINT 10 - 4 - 2\n', ["4"]),
        ('PRINT "hello"\n', ["hello"]),
        ('LET S = "a"\nPRINT S\n', ["a"]),
        ('PRINT 1, 2, 3\n', ["1 2 3"]),
        ("' a comment\nLET X = 1 ' trailing\nPRINT X\n", ["1"]),
        ('PRINT\n', [""]),
        ('DEF FN SQ(X) = X * X\nPRINT FN SQ(4) + 1\n', ["17"]),
        ('LET A = 10\nDEF FN ADDA(X) = X + A\nPRINT FN ADDA(5)\n', ["15"]),
        ('DEF FN AVG(A, B) = (A + B) / 2\nPRINT FN AVG(3, 8)\n', ["5.5"]),
        ('DEF FN SQ(X) = X * X\nDEF FN HYP2(A, B) = FN SQ(A) + FN SQ(B)\nPRINT FN HYP2(3, 4)\n', ["25"]),
        ('LET X = 3\nDEF FN F(X) = X + 1\nPRINT FN F(10), X\n', ["11 3"]),
        ('\n\nLET X = 1\n\nPRINT X\n', ["1"]),
    ]
    for source, expected in cases:
        got = run(source)
        assert got == expected, f"{source!r}: expected {expected}, got {got}"
        print(f"  {source.strip()!r} -> {got}  OK")

    errors = [
        ('PRINT Y\n', "undefined variable Y"),
        ('PRINT FN NOPE(1)\n', "undefined function FN NOPE"),
        ('DEF FN F(X) = X\nPRINT FN F(1, 2)\n', "FN F takes 1 argument(s), got 2"),
        ('PRINT 1 / 0\n', "division by zero"),
        ('LET = 3\n', "syntax error"),
        ('PRINT 1 +\n', "syntax error"),
        ('PRINT 1 @ 2\n', "unexpected character"),
        ('DEF FN F(X) = FN F(X)\nPRINT FN F(1)\n', "recursion is not supported"),
        ('DEF FN G() = X\nDEF FN F(X) = FN G()\nPRINT FN F(5)\n', "undefined variable X"),
    ]
    for source, message in errors:
        try:
            run(source)
        except BasicError as exc:
            assert message in str(exc), f"{source!r}: expected {message!r}, got {exc}"
            print(f"  {source.strip()!r} -> error: {exc}  OK")
        else:
            raise AssertionError(f"{source!r}: expected an error")

    print("\nAll tests passed.")
