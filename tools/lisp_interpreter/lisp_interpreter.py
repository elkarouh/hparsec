"""A Lisp interpreter built on hparsec, equivalent to Peter Norvig's lispy.py.

Supported: numbers, symbols, lists, quote, if, define, set!, lambda, begin, procedure
calls with closures, and the standard procedures of lispy.py (arithmetic, comparisons,
car/cdr/cons/list, map, apply, and so on). Comments start with ';'.

Design: the grammar is EBNF in each rule class's docstring. Every rule class has a
datum() method (the Python value of its source), and expressions have evaluate(env).
A list handles its own special form or application by calling the methods of its
expressions, and nothing walks the tree generically. The environment is hparsec's
SymbolTable: the stack of scopes is the environment chain, and a lambda keeps the
scopes that were open when it was created.

Usage:
    python3 lisp_interpreter.py program.scm   run a file
    python3 lisp_interpreter.py               start a REPL
"""

import functools
import math
import operator as op
import re
import sys

from hparsec import (
    Grammar,
    ParserState,
    Terminals,
    as_node,
    expect_type,
    literal,
    parts,
    SymbolTable,
)


class LispError(Exception):
    """An error in the Lisp program: a syntax error, or a run-time error."""


TOKEN_SPEC = [
    ("LPAREN", r"\("),
    ("RPAREN", r"\)"),
    ("ATOM", r"[^\s()';]+"),
    ("COMMENT", r";[^\n]*"),
    ("SKIP", r"\s+"),
]
TOKEN_RE = re.compile("|".join(f"(?P<{name}>{pattern})" for name, pattern in TOKEN_SPEC))
NUMBER_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")

TOKEN_TYPES = {"NUMBER": 1, "SYMBOL": 2, "LPAREN": 3, "RPAREN": 4}


class Token:
    def __init__(self, type, string):
        self.type = type
        self.string = string

    def __repr__(self):
        return f"Token({self.type!r}, {self.string!r})"


def tokenize(source):
    """Split source into tokens. Numbers are recognized here, symbols are everything else."""
    tokens = []
    pos = 0
    while pos < len(source):
        match = TOKEN_RE.match(source, pos)
        if match is None:
            raise LispError(f"unexpected character {source[pos]!r}")
        pos = match.end()
        kind, text = match.lastgroup, match.group()
        if kind in ("SKIP", "COMMENT"):
            continue
        if kind == "ATOM":
            kind = "NUMBER" if NUMBER_RE.fullmatch(text) else "SYMBOL"
        tokens.append(Token(TOKEN_TYPES[kind], text))
    return tokens


def _number(text):
    return float(text) if "." in text else int(text)


class Procedure:
    """A lambda: its parameter names, its body, and the scopes open where it was created."""

    def __init__(self, params, body, scopes):
        self.params = params
        self.body = body
        self.scopes = scopes

    def __repr__(self):
        return "<procedure>"


def to_string(value):
    if isinstance(value, list):
        return "(" + " ".join(to_string(item) for item in value) + ")"
    if value is True:
        return "#t"
    if value is False:
        return "#f"
    if value is None:
        return "None"
    return str(value)


class Environment:
    """The environment chain, kept in hparsec's SymbolTable.

    The stack's bottom scope holds the standard procedures and the top-level definitions.
    A procedure call pushes one frame with its arguments on top of the scopes that the
    procedure captured. A symbol's "value" holds the Lisp value.
    """

    MAX_CALL_DEPTH = 80

    def __init__(self):
        self.symbols = SymbolTable()
        self.symbols.push_scope("global")
        self.depth = 0
        for name, value in standard_procedures(self).items():
            self.symbols.add(name, kind="builtin", value=value)

    def lookup(self, name):
        symbol = self.symbols.lookup(name)
        if symbol is None:
            raise LispError(f"undefined symbol {name}")
        return symbol["value"]

    def define(self, name, value):
        """define: a new binding in the innermost scope."""
        self.symbols.add(name, kind="var", value=value)

    def assign(self, name, value):
        """set!: change the innermost existing binding of name."""
        symbol = self.symbols.lookup(name)
        if symbol is None:
            raise LispError(f"set!: undefined symbol {name}")
        symbol["value"] = value

    def capture(self):
        return list(self.symbols.stack)

    def apply(self, procedure, args):
        if not isinstance(procedure, Procedure):
            if callable(procedure):
                try:
                    return procedure(*args)
                except (TypeError, IndexError, ValueError, ZeroDivisionError) as exc:
                    raise LispError(f"bad arguments to a procedure: {exc}") from None
            raise LispError(f"not a procedure: {to_string(procedure)}")
        if len(procedure.params) != len(args):
            raise LispError(f"procedure takes {len(procedure.params)} argument(s), got {len(args)}")
        if self.depth >= self.MAX_CALL_DEPTH:
            raise LispError(f"more than {self.MAX_CALL_DEPTH} nested calls")
        frame = {"name": "lambda", "symbols": {
            name: {"type": None, "kind": "param", "value": value}
            for name, value in zip(procedure.params, args)}}
        saved = self.symbols.stack
        self.symbols.stack = procedure.scopes + [frame]
        self.depth += 1
        try:
            return procedure.body.evaluate(self)
        finally:
            self.depth -= 1
            self.symbols.stack = saved


def standard_procedures(env):
    """The procedures of lispy.py. Those that call procedures use env to do it."""
    def begin(*values):
        return values[-1] if values else None

    def car(x):
        return x[0]

    def cdr(x):
        return x[1:]

    def cons(x, y):
        return [x] + y

    def map_(procedure, seq):
        return [env.apply(procedure, [x]) for x in seq]

    def apply_(procedure, args):
        return env.apply(procedure, args)

    def is_procedure(x):
        return isinstance(x, Procedure) or callable(x)

    return {
        "+": lambda *xs: sum(xs), "*": lambda *xs: math.prod(xs),
        "-": lambda x, *ys: -x if not ys else functools.reduce(op.sub, ys, x),
        "/": lambda x, *ys: functools.reduce(op.truediv, ys, x),
        ">": op.gt, "<": op.lt, ">=": op.ge, "<=": op.le, "=": op.eq,
        "abs": abs, "max": max, "min": min, "round": round,
        "append": lambda *lists: sum(lists, []), "apply": apply_, "begin": begin,
        "car": car, "cdr": cdr, "cons": cons, "length": len,
        "list": lambda *x: list(x), "list?": lambda x: isinstance(x, list),
        "map": map_, "not": op.not_, "null?": lambda x: x == [],
        "number?": lambda x: isinstance(x, (int, float)) and not isinstance(x, bool),
        "procedure?": is_procedure, "symbol?": lambda x: isinstance(x, str),
        "eq?": op.is_, "equal?": op.eq,
    }


# ============================================================
# Terminals
# ============================================================

class LispTerminals(Terminals):
    number = expect_type(TOKEN_TYPES["NUMBER"])
    symbol = expect_type(TOKEN_TYPES["SYMBOL"])

    # Uppercase terminals are ignored in the tree
    LPAREN = literal("(")
    RPAREN = literal(")")


# ============================================================
# Grammar
# ============================================================

class LispGrammar(Grammar):
    class __default__:
        """Methods every node has."""
        def parts(self):
            """The node's parts in source order (see hparsec.parts)."""
            return list(parts(self))

    program = expression[:]
    expression = as_node(atom | list_form)
    atom = as_node(number | symbol)
    list_form = LPAREN + expression[:] + RPAREN

    class program:
        """program ::= expression*"""
        def run(self, env):
            results = [item.evaluate(env) for item in self.expression_list]
            return results[-1] if results else None

    class expression:
        """expression ::= atom | list_form"""
        def evaluate(self, env):
            return self.parts()[0].evaluate(env)

        def datum(self):
            return self.parts()[0].datum()

        def symbol_name(self):
            return self.parts()[0].symbol_name()

    class atom:
        """atom ::= number | symbol"""
        def evaluate(self, env):
            if self.number is not None:
                return _number(self.number.node)
            return env.lookup(self.symbol.node)

        def datum(self):
            if self.number is not None:
                return _number(self.number.node)
            return self.symbol.node

        def symbol_name(self):
            return self.symbol.node if self.symbol is not None else None

    class list_form:
        """list_form ::= LPAREN expression* RPAREN"""
        def evaluate(self, env):
            items = self.expression_list
            if not items:
                raise LispError("the empty combination () cannot be evaluated")
            head = items[0].symbol_name()
            if head == "quote":
                return self.quote(items)
            if head == "if":
                return self.if_form(items, env)
            if head == "define":
                return self.define_form(items, env)
            if head == "set!":
                return self.set_form(items, env)
            if head == "lambda":
                return self.lambda_form(items, env)
            if head == "begin":
                return self.begin_form(items, env)
            procedure = items[0].evaluate(env)
            args = [item.evaluate(env) for item in items[1:]]
            return env.apply(procedure, args)

        def datum(self):
            return [item.datum() for item in self.expression_list]

        def symbol_name(self):
            return None

        def quote(self, items):
            self.check_arity(items, 2, "quote")
            return items[1].datum()

        def if_form(self, items, env):
            self.check_arity(items, 3, "if", 4)
            test = items[1].evaluate(env)
            if test:
                return items[2].evaluate(env)
            return items[3].evaluate(env) if len(items) == 4 else None

        def define_form(self, items, env):
            self.check_arity(items, 3, "define")
            name = items[1].symbol_name()
            if name is None:
                raise LispError("define: the name must be a symbol")
            env.define(name, items[2].evaluate(env))
            return None

        def set_form(self, items, env):
            self.check_arity(items, 3, "set!")
            name = items[1].symbol_name()
            if name is None:
                raise LispError("set!: the name must be a symbol")
            env.assign(name, items[2].evaluate(env))
            return None

        def lambda_form(self, items, env):
            self.check_arity(items, 3, "lambda")
            params = items[1].datum()
            if not isinstance(params, list) or not all(isinstance(p, str) for p in params):
                raise LispError("lambda: the parameters must be a list of symbols")
            return Procedure(params, items[2], env.capture())

        def begin_form(self, items, env):
            result = None
            for item in items[1:]:
                result = item.evaluate(env)
            return result

        def check_arity(self, items, least, form, most=None):
            most = least if most is None else most
            if not least <= len(items) <= most:
                raise LispError(f"{form}: wrong number of parts ({len(items) - 1} given)")


# ============================================================
# Entry points
# ============================================================

def parse(source):
    """Parse source into a program node. Raises LispError on a syntax error."""
    ParserState.reset()
    result = program.parse(tokenize(source))
    if not result:
        raise LispError("syntax error")
    ast, stream = result
    if stream.pos != len(stream.tokens):
        raise LispError("syntax error: unbalanced parentheses or an unexpected ')'")
    return ast


def run(source, env=None):
    """Evaluate every expression in source and return the value of the last one."""
    env = Environment() if env is None else env
    try:
        return parse(source).run(env)
    except RecursionError:
        raise LispError("recursion too deep") from None


# ============================================================
# Self-tests and command line
# ============================================================

def repl():
    env = Environment()
    while True:
        try:
            line = input("lisp> ")
        except EOFError:
            print()
            return
        if not line.strip():
            continue
        try:
            value = run(line, env)
        except LispError as exc:
            print(f"error: {exc}")
            continue
        if value is not None:
            print(to_string(value))


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        repl()
        sys.exit(0)
    if args == ["--test"]:
        pass  # the self-tests below run
    elif len(args) == 1:
        with open(args[0], encoding="utf-8") as handle:
            try:
                value = run(handle.read())
            except LispError as exc:
                print(f"error: {exc}", file=sys.stderr)
                sys.exit(1)
        if value is not None:
            print(to_string(value))
        sys.exit(0)
    else:
        sys.exit("usage: lisp_interpreter.py [program.scm | --test]")

    cases = [
        ("(* 2 (+ 3 4))", "14"),
        ("(if (> 1 2) 3 4)", "4"),
        ("(if (< 1 2) 3)", "3"),
        ("(quote (a b c))", "(a b c)"),
        ("(car (quote (a b c)))", "a"),
        ("(cdr (quote (a b c)))", "(b c)"),
        ("(cons 1 (quote (2 3)))", "(1 2 3)"),
        ("(length (list 1 2 3))", "3"),
        ("(begin (define x 1) (set! x (+ x 1)) x)", "2"),
        ("(begin (define r 10) (* r r))", "100"),
        ("(begin (define fact (lambda (n) (if (<= n 1) 1 (* n (fact (- n 1)))))) (fact 10))", "3628800"),
        ("(begin (define make-adder (lambda (n) (lambda (x) (+ x n)))) ((make-adder 3) 4))", "7"),
        ("(map (lambda (x) (* x x)) (list 1 2 3))", "(1 4 9)"),
        ("(apply + (list 1 2 3))", "6"),
        ("(begin (define pi 3.14159) (define area (lambda (r) (* pi (* r r)))) (area 1))", "3.14159"),
        ("(quote (if x (y)))", "(if x (y))"),
        ("(max 3 9 4)", "9"),
        ("(equal? (quote (1 2)) (list 1 2))", "#t"),
        ("(begin (define k 1) (define f (lambda (k) (begin (set! k 5) k))) (f 2) k)", "1"),
        ("(begin ; a comment\n  (+ 1 2)) ; trailing", "3"),
    ]
    for source, expected in cases:
        got = to_string(run(source))
        assert got == expected, f"{source!r}: expected {expected}, got {got}"
        print(f"  {source.splitlines()[0]!r} -> {got}  OK")

    errors = [
        ("(+ 1 2", "syntax error"),
        ("(+ 1 2))", "syntax error"),
        ("(undefined 1)", "undefined symbol undefined"),
        ("((lambda (x) x) 1 2)", "procedure takes 1 argument(s), got 2"),
        ("(set! nope 1)", "set!: undefined symbol nope"),
        ("(define (f x) x)", "define: the name must be a symbol"),
        ("()", "the empty combination"),
        ("(car (quote ()))", "bad arguments to a procedure"),
        ("(begin (define f (lambda (n) (f n))) (f 1))", "more than 80 nested calls"),
    ]
    for source, message in errors:
        try:
            run(source)
        except LispError as exc:
            assert message in str(exc), f"{source!r}: expected {message!r}, got {exc}"
            print(f"  {source!r} -> error: {exc}  OK")
        else:
            raise AssertionError(f"{source!r}: expected an error")

    print("\nAll tests passed.")
