#!/usr/bin/env python3
"""Comprehensive test suite for hek_py2py.py

Run with:
    # Copy this file into the same directory as hek_py2py.py, then:
    python3 test_hek_py2py.py

Each test is labelled PASS, FAIL, or ERROR. FAIL and ERROR entries include
a short bug description so the root cause is immediately obvious.

"""

import sys
import os

# Allow running from any directory that contains the hek_* files.
sys.path.insert(0, os.path.dirname(__file__))

from hek_py2py import translate

###############################################################################
# Test runner
###############################################################################

_passed = _failed = _errors = 0


def test(label, code, expected=None, *, bug=None):
    """Run one round-trip test.

    Args:
        label:    Short human-readable name for the test.
        code:     Python source to translate.
        expected: Expected output; defaults to *code* (identity round-trip).
        bug:      If provided, a string describing the known bug that causes
                  this test to fail.  The test is still executed so we track
                  whether it has been fixed.
    """
    global _passed, _failed, _errors
    if expected is None:
        expected = code
    try:
        got = translate(code)
    except Exception as exc:
        _errors += 1
        status = "ERROR"
        detail = f"    Exception: {exc}"
        if bug:
            detail += f"\n    Known bug: {bug}"
        print(f"  {status}: {label}")
        print(detail)
        return

    if got == expected:
        _passed += 1
        print(f"  PASS: {label}")
    else:
        _failed += 1
        marker = "KNOWN-FAIL" if bug else "FAIL"
        print(f"  {marker}: {label}")
        print(f"    input:    {code!r}")
        print(f"    expected: {expected!r}")
        print(f"    got:      {got!r}")
        if bug:
            print(f"    bug:      {bug}")


def section(title):
    print(f"\n{'─'*60}")
    print(f"  {title}")
    print(f"{'─'*60}")


###############################################################################
# Tests — simple/expression statements
###############################################################################

section("Simple statements — known-good (regression)")

test("assign int", "x = 1\n")
test("assign multi-target", "a = b = 1\n")
test("augmented assign +=", "x += 1\n")
test("augmented assign full",
     "x -= 1\nx *= 2\nx /= 3\nx //= 4\nx %= 5\nx **= 2\n"
     "x &= 0xFF\nx |= 0x01\nx ^= 0x10\nx >>= 1\nx <<= 1\n")
test("annotated assign", "x: int = 1\n")
test("annotated no value", "x: int\n")
test("starred assign", "a, *b, c = xs\n")
test("star on lhs", "*a, b = xs\n")
test("import simple", "import os\n")
test("import multi", "import os, sys\n")
test("import as", "import os as operating_system\n")
test("from import", "from os import path\n")
test("from import multi", "from os import path, getcwd\n")
test("from import as", "from os import path as p\n")
test("from import star", "from os import *\n")
test("from relative", "from . import foo\n")
test("from relative deep", "from ..utils import helper\n")
test("del single", "del x\n")
test("del multi", "del x, y\n")
test("assert bare", "assert x\n")
test("assert message", "assert x, 'msg'\n")
test("raise bare", "raise\n")
test("raise expr", "raise ValueError('oops')\n")
test("raise from", "raise ValueError('x') from e\n")
test("global single", "global x\n")
test("global multi", "global x, y\n")
test("nonlocal", "nonlocal x\n")
test("pass", "pass\n")
test("break", "break\n")
test("continue", "continue\n")
test("return no val", "def f():\n    return\n")
test("semicolon two", "x = 1; y = 2\n")
test("semicolon three", "a = 1; b = 2; c = 3\n")

section("Expressions — known-good (regression)")

test("ternary", "x = a if cond else b\n")
test("bool ops", "x = a and b or c\n")
test("compare chain", "x = a < b < c\n")
test("compare in", "x = a in b\n")
test("compare not in", "x = a not in b\n")
test("compare is", "x = a is b\n")
test("compare is not", "x = a is not b\n")
test("unary not", "x = not y\n")
test("unary neg", "x = -y\n")
test("unary invert", "x = ~y\n")
test("power", "x = a ** b\n")
test("floor div", "x = a // b\n")
test("matmul", "x = a @ b\n")
test("ellipsis", "x = ...\n")
test("bytes literal", "x = b'hello'\n")
test("multiline string", 'x = """hello\nworld"""\n')
test("set literal", "x = {1, 2, 3}\n")
test("dict literal", "x = {'a': 1, 'b': 2}\n")
test("tuple literal", "x = (1, 2, 3)\n")
test("empty tuple", "x = ()\n")
test("single tuple", "x = (1,)\n")
test("slice", "x = a[1:2]\n")
test("slice step", "x = a[::2]\n")
test("slice full", "x = a[1:10:2]\n")
test("subscript", "x = a[b]\n")
test("subscript multi", "x = a[b, c]\n")
test("attribute chain", "x = a.b.c\n")
test("call kwargs", "f(a=1, b=2)\n")
test("call star", "f(*args)\n")
test("call starstar", "f(**kwargs)\n")
test("call mixed", "f(1, *args, key=val, **kw)\n")
test("chained calls", "x = a.b().c().d()\n")
test("nested calls", "x = f(g(h(x)))\n")
test("list comp", "x = [x for x in xs]\n")
test("nested list comp", "x = [x for row in grid for x in row]\n")
test("dict comp", "x = {k: v for k, v in d.items()}\n")
test("set comp", "x = {x for x in xs}\n")
test("lambda no args", "f = lambda: 42\n")
test("lambda one arg", "f = lambda x: x + 1\n")
test("lambda multi", "f = lambda x, y: x + y\n")

###############################################################################
# BUG CATEGORY A — Missing grammar rules
###############################################################################

section("BUG CATEGORY A — Missing grammar rules")

# A1 — f-strings
# Python 3.12+ tokenises f-strings as FSTRING_START / FSTRING_MIDDLE /
# FSTRING_END tokens.  The atom parser in hek_py3_expr.py only handles STRING
# (token type 3), so f-strings are never matched.
test(
    "f-string simple",
    "x = f'hello {name}'\n",
    bug="atom parser only matches STRING (tok_type=3); FSTRING_START (61) / "
        "FSTRING_MIDDLE (62) / FSTRING_END (63) tokens are unknown — "
        "entire statement silently dropped",
)
test(
    "f-string expression",
    "x = f'{a + b}'\n",
    bug="Same FSTRING token issue — any f-string causes a parse failure",
)
test(
    "f-string in function call",
    "print(f'Hello, {name}!')\n",
    bug="Same FSTRING token issue",
)

# A2 — yield / yield from as statements
# simple_stmt lists: ann_assign | aug_assign | assign | return | pass | break |
# continue | del | assert | raise | global | nonlocal | import | from | type |
# expressions.
# yield_expr is never in simple_stmt, so "yield x" inside a function body is
# not parsed.  (bare "yield" happens to work because 'yield' is parsed as an
# IDENTIFIER by the expressions path, but "yield x" fails because the token
# following 'yield' is unexpected.)
test(
    "yield expr as stmt",
    "def f():\n    yield x\n",
    bug="yield_expr not included in simple_stmt; 'yield x' is unparseable "
        "inside a function body — the whole def silently returns empty",
)
test(
    "yield from as stmt",
    "def f():\n    yield from xs\n",
    bug="Same as above — yield_from not in simple_stmt",
)
test(
    "yield bare as stmt",
    "def f():\n    yield\n",
    # bare yield works because 'yield' matches as an IDENTIFIER expression
)

# A3 — lambda with default parameters
# lambda_params = IDENTIFIER + (COMMA + IDENTIFIER)[:] — no support for
# IDENTIFIER '=' expression defaults, *args, **kwargs, or / pos-only markers.
test(
    "lambda with default",
    "f = lambda x=1: x\n",
    bug="lambda_params = IDENTIFIER + (COMMA + IDENTIFIER)[:] — no default "
        "value support; 'x=1' fails to parse, entire statement dropped",
)
test(
    "lambda with multiple defaults",
    "f = lambda x=1, y=2: x + y\n",
    bug="Same lambda_params limitation",
)
test(
    "lambda with *args",
    "g = lambda *args: args\n",
    bug="lambda_params has no *args support",
)

# A4 — walrus operator := inside parenthesised expression
# paren_group = LPAREN + (yield_expr | expressions | named_expression) + RPAREN
# 'expressions' is tried before 'named_expression'.  'expressions' greedily
# matches the identifier 'n' then fails to find ')', but the combinator does
# NOT backtrack — so 'named_expression' (which contains walrus) is never tried.
test(
    "walrus in if condition",
    "if (n := 10) > 5:\n    pass\n",
    bug="paren_group alternatives ordered as (yield_expr | expressions | "
        "named_expression); 'expressions' matches 'n' then the sequence fails "
        "on ':=', but no backtrack occurs — named_expression/walrus never tried",
)
test(
    "walrus in while",
    "while chunk := f.read(8192):\n    process(chunk)\n",
    bug="Same walrus/paren ordering issue",
)

# A5 — type aliases (Python 3.12 soft keyword)
# The 'type' soft-keyword statement is defined in hek_py3_stmt.py (type_stmt)
# but Tokenizer / ParserState interaction causes it to fail in some contexts.
test(
    "type alias simple",
    "type Point = tuple[int, int]\n",
    bug="'type' soft-keyword statement silently fails to parse when used as a "
        "top-level statement (parse returns False, output is empty)",
)
test(
    "type alias generic",
    "type Vector[T] = list[T]\n",
    bug="Generic type alias (type X[T] = ...) not parsed",
)

# A6 — parenthesised with-statement (Python 3.10+)
test(
    "parenthesised with (PEP 617)",
    "with (\n    a() as x,\n    b() as y,\n):\n    pass\n",
    bug="Parenthesised with-statement is not in the with_stmt grammar — "
        "the opening '(' is not consumed, parse fails silently",
)

###############################################################################
# BUG CATEGORY B — Wrong grammar rules (parse succeeds, output is wrong)
###############################################################################

section("BUG CATEGORY B — Wrong grammar rules")

# B1 — generator expression inside function call
# genexpr = named_expression + for_if_clauses.
# call_trailer = LPAREN + arguments[:] + RPAREN.
# 'arguments' handles keyword/star args but does NOT include a leading genexpr
# path.  As a result, "sum(x for x in xs)" is parsed as "sum(x)", silently
# dropping the for-clause.
test(
    "genexpr in function call",
    "x = sum(x for x in xs)\n",
    bug="call_trailer arguments parser does not handle a leading generator "
        "expression; the for-clause is silently dropped — "
        "'sum(x for x in xs)' becomes 'sum(x)'",
)
test(
    "genexpr with condition in call",
    "x = sum(x for x in xs if x > 0)\n",
    bug="Same genexpr-in-call issue; additionally for_if_clause 'if' condition crashes",
)

# B2 — class definition with keyword arguments (e.g. metaclass=)
# class_args = LPAREN + (expression + ...) + RPAREN.
# 'expression' does not parse 'name=value' keyword syntax.  So
# "class Foo(metaclass=Meta):" fails entirely — parse returns False.
test(
    "class with metaclass=",
    "class Foo(metaclass=Meta):\n    pass\n",
    bug="class_args uses 'expression' which cannot parse 'name=value' keyword "
        "arguments; should use the same 'arguments' grammar as call_trailer",
)
test(
    "class with base and metaclass",
    "class Foo(Base, metaclass=Meta):\n    pass\n",
    bug="Same class keyword-arg issue",
)

# B3 — match/case class pattern with keyword sub-patterns
# pattern_class = IDENTIFIER + LPAREN + (pattern + ...)[:] + RPAREN.
# Python's class pattern also allows keyword sub-patterns: Point(x=a, y=b).
# These are not implemented — keyword_pattern (NAME '=' pattern) is absent
# from the grammar, so pattern_class silently fails for keyword patterns.
test(
    "match class pattern with keyword args",
    "match x:\n    case Point(x=a, y=b):\n        pass\n",
    bug="keyword_pattern (NAME '=' pattern) not in grammar; pattern_class "
        "uses 'pattern' only, so 'Point(x=a, y=b)' fails to parse",
)
test(
    "match class pattern mixed",
    "match p:\n    case Point(0, y=b):\n        pass\n",
    bug="Same keyword_pattern gap in pattern_class",
)

###############################################################################
# BUG CATEGORY C — Broken to_py() implementation
###############################################################################

section("BUG CATEGORY C — Broken to_py() raises AttributeError")

# C1 — list/dict/set comprehension with an 'if' guard
# for_if_clause = for_simple + (I_IF + disjunction)[:]
# In to_py(), the code iterates self.nodes[2:] and calls f.to_py() on each
# element.  But nodes[2] is a Several_Times whose children are Sequence_Parser
# objects (each wrapping I_IF + disjunction).  Sequence_Parser has no to_py().
# The fix is: for each seq in node.nodes: seq.nodes[0].to_py()
test(
    "list comp with if guard",
    "x = [x for x in xs if x > 0]\n",
    bug="for_if_clause.to_py() iterates Several_Times children directly; "
        "each child is a Sequence_Parser (I_IF+disjunction) with no to_py(); "
        "fix: iterate seq.nodes[0].to_py() for each seq in the Several_Times",
)
test(
    "list comp double if guard",
    "x = [x for x in xs if x > 0 if x < 100]\n",
    bug="Same for_if_clause to_py() bug",
)
test(
    "dict comp with if guard",
    "d = {k: v for k, v in items if v is not None}\n",
    bug="Same for_if_clause to_py() bug — affects dictcomp too",
)
test(
    "set comp with if guard",
    "s = {x for x in xs if x}\n",
    bug="Same for_if_clause to_py() bug — affects setcomp too",
)
test(
    "nested comp with if",
    "flat = [x for row in grid for x in row if x > 0]\n",
    bug="Same for_if_clause to_py() bug",
)

###############################################################################
# BUG CATEGORY D — Trivia (comment / blank line) placement bugs
###############################################################################

section("BUG CATEGORY D — Trivia / comment placement bugs")

# D1 — blank lines inside compound statement bodies are stripped
# Python's tokenizer emits NL (non-logical newline) tokens for blank lines
# inside function/class bodies.  The Tokenizer buffers these as 'blank' trivia.
# In parse_module_with_trivia, inner_trivia collection uses position ranges
# that don't capture NL tokens between inner statements, so blank lines
# are silently discarded.
test(
    "blank line inside function body",
    "def f():\n    x = 1\n\n    y = 2\n",
    bug="Blank lines (NL tokens) inside compound statement bodies are buffered "
        "as trivia but never attached to inner_trivia — they are silently lost",
)
test(
    "blank lines between class methods",
    "class Stack:\n    def __init__(self):\n        self._items = []\n\n"
    "    def push(self, item):\n        self._items.append(item)\n\n"
    "    def pop(self):\n        return self._items.pop()\n",
    bug="Same blank-line-in-body loss — affects class bodies with multiple methods",
)

# D2 — trailing comment inside a block placed before body lines instead of after
# When a comment appears at the end of a block (before DEDENT) Python's
# tokenizer emits the COMMENT at an indentation level matching the block.
# The spill_trivia heuristic misclassifies it and it is injected BEFORE the
# last body statement rather than after it.
test(
    "comment at end of block before dedent",
    "def f():\n    pass\n    # trailing in block\nx = 1\n",
    bug="Comment before DEDENT that is indented inside the block is emitted "
        "before 'pass' instead of after; spill_trivia indent heuristic wrong",
)

# D3 — comment between if/elif emitted after elif instead of before it
# A comment at the outer indent level between an 'if' block and its 'elif'
# clause is consumed as inner_trivia of the if-statement.  During output it
# is appended after the elif header rather than between if-body and elif.
test(
    "comment between if and elif",
    "if x:\n    pass\n# between\nelif y:\n    pass\n",
    bug="Comment at outer indent between if-body and elif is consumed as "
        "inner_trivia and injected after the elif header instead of before it",
)

# D4 — inline comment on compound statement header attached to first body line
# An inline comment on a 'class Foo:  # comment' header line is stored as
# 'inline' leading_trivia.  The output code appends inline trivia to output[-1]
# *after* the to_py() string has already included body lines, so the comment
# ends up on the last rendered line (inside the body) rather than the header.
test(
    "inline comment on compound header",
    "class Foo:  # my class\n    pass\n",
    bug="Inline comment on compound statement header (class/def/if/for/…) "
        "is appended to output[-1] after to_py(), which by then is the full "
        "block including body lines — comment lands on first body line instead",
)
test(
    "inline comment on def header",
    "def f():  # my func\n    pass\n",
    bug="Same inline-on-header misplacement",
)
test(
    "inline comment on if header",
    "if x:  # check\n    pass\n",
    bug="Same inline-on-header misplacement",
)

# D5 — decorator + blank lines + next function: subsequent statements dropped
# When a decorated function or class follows blank lines after another compound
# statement, the decorator is attached to one parse node but the function/class
# that follows the decorator is dropped if parsing stops early due to the trivia
# flushing logic inside parse_module_with_trivia.
test(
    "decorated function after blank lines",
    "def repeat(n):\n    return n\n\n@repeat(3)\ndef greet(name):\n    pass\n",
    bug="After a compound statement + blank lines + decorator, the decorated "
        "function is silently dropped; trivia flush boundary interacts badly "
        "with the decorator look-ahead in parse_module_with_trivia",
)

###############################################################################
# BUG CATEGORY E — Real-world programs that expose the above bugs
###############################################################################

section("BUG CATEGORY E — Real-world program round-trips")

test("fibonacci", """\
def fib(n):
    if n <= 1:
        return n
    return fib(n - 1) + fib(n - 2)
""")

test(
    "class with blank-separated methods",
    """\
class Stack:
    def __init__(self):
        self._items = []

    def push(self, item):
        self._items.append(item)

    def pop(self):
        return self._items.pop()

    def is_empty(self):
        return len(self._items) == 0
""",
    bug="Blank lines between methods dropped (Bug D1)",
)

test(
    "decorator factory + decorated function",
    """\
def repeat(n):
    def decorator(func):
        def wrapper(*args, **kwargs):
            for _ in range(n):
                func(*args, **kwargs)
        return wrapper
    return decorator

@repeat(3)
def greet(name):
    print(name)
""",
    bug="Decorated function after blank lines dropped (Bug D5); "
        "f-string in print also fails (Bug A1)",
)

test(
    "generator pipeline",
    """\
def evens(xs):
    return list(x for x in xs if x % 2 == 0)
""",
    bug="genexpr-in-call drops for-clause (Bug B1); "
        "for_if_clause 'if' guard crashes (Bug C1)",
)

test(
    "type annotations with Optional",
    """\
from typing import Optional, List

def process(items: List[int], limit: Optional[int] = None) -> List[int]:
    return [x for x in items if limit is None or x < limit]
""",
    bug="list comp with 'if' guard crashes (Bug C1); "
        "blank line between import and def lost (Bug D1)",
)

test(
    "walrus-based file reader",
    """\
def read_chunks(path):
    with open(path, 'rb') as f:
        while chunk := f.read(4096):
            process(chunk)
""",
    bug="walrus operator in while not parsed (Bug A4); "
        "f-string would also fail (Bug A1)",
)

###############################################################################
# Summary
###############################################################################

print(f"\n{'='*60}")
print(f"Results: {_passed} passed, {_failed} failed, {_errors} errors")
print(f"  (FAIL/ERROR includes both known bugs and any regressions)")
print(f"{'='*60}\n")

sys.exit(0 if (_failed + _errors) == 0 else 1)
