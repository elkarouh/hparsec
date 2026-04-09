#!/usr/bin/env python3
"""Python 3.14 source-to-source translator using parser combinators.

ARCHITECTURE CHANGE (RichNL approach):
======================================
Instead of reconstructing comment positions after parsing, comments are now
attached directly to NL tokens during tokenization as RichNL objects.
Comments travel naturally with the parse tree, eliminating position arithmetic.

CHANGES MADE:
- hek_tokenize.py: Added RichNL class, bundles COMMENT+NL tokens
- hek_parsec.py: Added expect_type_node() to return token nodes (not strings)
- hek_py3_parser.py: NL = expect_type_node(tkn.NL), added NL.to_py() method
- hek_py3_stmt.py: Fixed import_names_paren to allow NL[:] inside parens
- py2py.py: Simplified parse_module() and translate()

TEST STATUS (as of implementation):
===================================
29 passed, 3 failed

PASSING:
- Simple statements (x = 1, import, from ... import)
- Compound statements (if/elif/else, while, for, try, with, match)
- Functions, classes, decorators, async variants
- Comments inside blocks (indented comments in compound statements)
- Leading comments (comments before first statement)

FAILING:
1. Blank lines between statements - plain NL tokens are skipped, not emitted
   Input:  'x = 1

y = 2
'
   Expected: 'x = 1

y = 2
'
   Got: 'x = 1
y = 2
'

2. Inline comments - COMMENT+NEWLINE (not NL) not handled
   Input:  'x = 1  # inline
y = 2
'
   Expected: 'x = 1  # inline
y = 2
'
   Got: '
' (broken)

3. Multiple blank lines preserved - same as #1
   Input:  '# header

import os

def f():...'
   Expected: '# header

import os

def f():...'
   Got: '# header
import os
def f():...' (blanks lost)

TODO FOR FUTURE WORK:
=====================
1. Handle plain NL tokens (without comments) - emit them as blank lines
2. Handle inline comments - they use NEWLINE token, not NL
   - Tokenizer needs to bundle COMMENT+NEWLINE or handle separately
3. Preserve blank line counts (currently all blanks collapse to single)
4. Fix statement parsing - only parses ~5 statements from hek_py3_expr.py
   - Some grammar rules may still not handle RichNL properly

USAGE:
    python3 py2py.py [file.py]       # translate a file
    echo "x = 1" | python3 py2py.py  # translate from stdin
"""

"""Python 3.14 source-to-source translator using parser combinators.

Parses Python source code using the hek_parsec combinator framework
and reconstructs it via to_py() methods on each AST node.

Comments and blank lines are preserved by collecting them as 'trivia'
in the tokenizer and attaching them to AST nodes. This approach is
language-agnostic — trivia travels with the AST, not with line numbers.

Usage:
    python3 py2py.py [file.py]       # translate a file
    echo "x = 1" | python3 py2py.py  # translate from stdin
"""

import sys, os

_dir = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, os.path.join(_dir, ".."))
sys.path.insert(0, os.path.join(_dir, "..", "ADASCRIPT_GRAMMAR"))

import sys
import token as token_mod

from hek_py3_parser import *  # fw() resolves names in calling module's globals
from hek_tokenize import Tokenizer, RichNL, set_current_tokenizer


def Input(code):
    """Create a token stream for parsing.

    The tokenizer now returns RichNL objects that bundle comments with
    newline tokens. Comments travel naturally with the parse tree,
    eliminating the need for position-based reconstruction.
    """
    gen = Tokenizer(code)
    set_current_tokenizer(gen)
    gen.get_new_token()  # skip ENCODING token
    return gen


def parse_module(code):
    """Parse a full module. Comments are embedded in the parse tree via RichNL."""
    from hek_parsec import ParserState
    ParserState.reset()
    stream = Input(code)
    stmts = []
    leading = []
    import token as token_mod

    # Peek at first token
    first_token = None
    try:
        first_token = stream.get_new_token()
    except StopIteration:
        pass

    if first_token is None or first_token.type == token_mod.ENDMARKER:
        return stmts, leading, []

    # Collect leading RichNL comments
    if isinstance(first_token, RichNL):
        leading.append(first_token)
        while True:
            tok = stream.get_new_token()
            if isinstance(tok, RichNL):
                leading.append(tok)
            elif tok.type == token_mod.NL:
                continue
            else:
                stream.reset(stream.mark() - 1)
                break
    else:
        stream.reset(stream.mark() - 1)

    # Parse statements with inter-statement comments
    while True:
        inter_comments = []

        # Collect RichNL comments before this statement
        while True:
            pos = stream.mark()
            try:
                tok = stream.get_new_token()
            except StopIteration:
                break
            if isinstance(tok, RichNL):
                inter_comments.append(tok)
                continue
            if tok.type == token_mod.NL:
                continue
            stream.reset(pos)
            break

        # Check for end of input
        try:
            tok = stream.get_new_token()
        except StopIteration:
            break
        if not tok or tok.type == token_mod.ENDMARKER:
            break
        stream.reset(pos)

        result = statement.parse(stream)
        if not result:
            import sys
            print(stream.format_error(), file=sys.stderr)
            break

        node = result[0]
        node._leading_comments = inter_comments
        stmts.append(node)

    return stmts, leading, []


def _inject_before_elif_else(rendered, spill_lines):
    """Inject spill_lines before the first elif/else at indent 0 in rendered.

    Returns modified rendered string, or None if no injection point found.
    """
    import re
    lines = rendered.split("\n")
    # Find the first line that starts with 'elif ' or 'else:'
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith(("elif ", "else:")):
            new_lines = lines[:i] + spill_lines + lines[i:]
            return "\n".join(new_lines)
    return None


def translate(code):
    """Parse Python source and reconstruct it via to_py()."""
    if not code.strip():
        return code

    stmts, leading, trailing = parse_module(code)

    output = []

    def emit_richnl(richnl):
        """Emit lines for a RichNL (comments and/or blank lines)."""
        output.extend(richnl.to_lines())

    # Emit leading comments and blank lines
    for richnl in leading:
        emit_richnl(richnl)

    for stmt in stmts:
        # Emit inter-statement comments attached to this statement
        inter = getattr(stmt, '_leading_comments', [])
        for richnl in inter:
            emit_richnl(richnl)

        # Emit the reconstructed statement
        try:
            rendered = stmt.to_py(0)
        except TypeError:
            rendered = stmt.to_py()
        # Compound statement bodies may have absorbed trailing blank lines
        # (blank NL tokens before DEDENT). Strip them from the rendered output
        # and emit them as inter-statement blanks after this statement.
        rendered_lines = rendered.split('\n')
        trailing_blanks = 0
        while rendered_lines and rendered_lines[-1] == '':
            rendered_lines.pop()
            trailing_blanks += 1
        output.append('\n'.join(rendered_lines))
        for _ in range(trailing_blanks):
            output.append('')

    # Emit trailing comments
    for richnl in trailing:
        emit_richnl(richnl)

    # Insert auto-collected imports at the top (after leading comments)
    from hek_parsec import ParserState
    if ParserState.nim_imports:
        # Find the first non-comment, non-blank line
        insert_pos = 0
        for i, line in enumerate(output):
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                insert_pos = i
                break
        for imp in sorted(ParserState.nim_imports):
            output.insert(insert_pos, imp)
            insert_pos += 1

    result = chr(10).join(output)
    if not result.endswith(chr(10)):
        result += chr(10)
    return result
def main(args=None):
    import subprocess
    if args is None:
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument("file", nargs="?")
        parser.add_argument("rest", nargs="*")
        parser.add_argument("-c", action="store_true")
        args = parser.parse_args()
    if args.file:
        with open(args.file) as f:
            code = f.read()
    else:
        code = sys.stdin.read()
    output = translate(code)
    if args.c and args.file:
        base = os.path.splitext(args.file)[0]
        py_file = base + "_gen.py"
        with open(py_file, "w") as f:
            f.write(output)
        print(f"Wrote {py_file}")
        result = subprocess.run([sys.executable, py_file] + (args.rest or []))
        sys.exit(result.returncode)
    else:
        print(output, end="")


###############################################################################
# Tests
###############################################################################


def run_tests():
    print("=" * 60)
    print("Python 3.14 py2py Translator Tests")
    print("=" * 60)

    tests = [
        # --- simple statements ---
        (
            "x = 1\n",
            "x = 1\n",
        ),
        (
            "x = 1\ny = 2\n",
            "x = 1\ny = 2\n",
        ),
        (
            "x += 1\n",
            "x += 1\n",
        ),
        (
            "import os\n",
            "import os\n",
        ),
        (
            "from os import path\n",
            "from os import path\n",
        ),
        (
            "x = 1; y = 2\n",
            "x = 1; y = 2\n",
        ),
        # --- compound statements ---
        (
            "if x:\n    pass\n",
            "if x:\n    pass\n",
        ),
        (
            "if x:\n    a = 1\nelif y:\n    b = 2\nelse:\n    c = 3\n",
            "if x:\n    a = 1\nelif y:\n    b = 2\nelse:\n    c = 3\n",
        ),
        (
            "while x:\n    pass\n",
            "while x:\n    pass\n",
        ),
        (
            "for x in xs:\n    pass\n",
            "for x in xs:\n    pass\n",
        ),
        (
            "try:\n    pass\nexcept ValueError:\n    pass\n",
            "try:\n    pass\nexcept ValueError:\n    pass\n",
        ),
        (
            "try:\n    pass\nfinally:\n    pass\n",
            "try:\n    pass\nfinally:\n    pass\n",
        ),
        (
            "with f():\n    pass\n",
            "with f():\n    pass\n",
        ),
        (
            "def f():\n    pass\n",
            "def f():\n    pass\n",
        ),
        (
            "def f(a, b=1):\n    return a\n",
            "def f(a, b=1):\n    return a\n",
        ),
        (
            "class Foo:\n    pass\n",
            "class Foo:\n    pass\n",
        ),
        (
            "class Foo(Bar):\n    pass\n",
            "class Foo(Bar):\n    pass\n",
        ),
        (
            "@dec\ndef f():\n    pass\n",
            "@dec\ndef f():\n    pass\n",
        ),
        (
            "async def f():\n    pass\n",
            "async def f():\n    pass\n",
        ),
        (
            "case x:\n    when 1:\n        pass\n",
            "match x:\n    case 1:\n        pass\n",
        ),
        # --- mixed programs ---
        (
            "import os\ndef main():\n    return os\n",
            "import os\ndef main():\n    return os\n",
        ),
        (
            "x = 1\nif x:\n    y = 2\n",
            "x = 1\nif x:\n    y = 2\n",
        ),
        (
            "def f():\n    pass\nclass Foo:\n    pass\n",
            "def f():\n    pass\nclass Foo:\n    pass\n",
        ),
        # --- nested ---
        (
            "if x:\n    if y:\n        pass\n",
            "if x:\n    if y:\n        pass\n",
        ),
        (
            "def f():\n    for x in xs:\n        if x:\n            return x\n",
            "def f():\n    for x in xs:\n        if x:\n            return x\n",
        ),
        (
            "class Foo:\n    def bar(self):\n        pass\n",
            "class Foo:\n    def bar(self):\n        pass\n",
        ),
        # --- larger program ---
        (
            "import os\nimport sys\ndef main():\n    x = 1\n    if x:\n        return x\n    return None\n",
            "import os\nimport sys\ndef main():\n    x = 1\n    if x:\n        return x\n    return None\n",
        ),
        # --- comments and blank lines ---
        (
            "# standalone comment\nx = 1\n",
            "# standalone comment\nx = 1\n",
        ),
        (
            "x = 1\n\ny = 2\n",
            "x = 1\n\ny = 2\n",
        ),
        (
            "# comment 1\n# comment 2\nx = 1\n",
            "# comment 1\n# comment 2\nx = 1\n",
        ),
        (
            "x = 1  # inline\ny = 2\n",
            "x = 1  # inline\ny = 2\n",
        ),
        (
            "# header\n\nimport os\n\n# func comment\ndef f():\n    pass\n",
            "# header\n\nimport os\n\n# func comment\ndef f():\n    pass\n",
        ),
        # --- bashisms ---
        (
            "$0\n",
            "import sys\nsys.argv[0]\n",
        ),
        (
            "$1\n",
            "import sys\nsys.argv[1]\n",
        ),
        (
            "$2\n",
            "import sys\nsys.argv[2]\n",
        ),
        (
            "$@\n",
            "import sys\nsys.argv[1:]\n",
        ),
        (
            "$#\n",
            "import sys\nlen(sys.argv) - 1\n",
        ),
        (
            "$HOME\n",
            "import os\nos.environ.get('HOME', '')\n",
        ),
        (
            "name = $1\n",
            "import sys\nname = sys.argv[1]\n",
        ),
        (
            "if $# < 2:\n    pass\n",
            "import sys\nif len(sys.argv) - 1 < 2:\n    pass\n",
        ),
        (
            "for arg in $@:\n    pass\n",
            "import sys\nfor arg in sys.argv[1:]:\n    pass\n",
        ),
    ]

    passed = failed = 0
    for code, expected in tests:
        try:
            output = translate(code)
            if output == expected:
                label = code.splitlines()[0]
                print(f"  PASS: {label!r}...")
                passed += 1
            else:
                label = code.splitlines()[0]
                print(f"  MISMATCH: {label!r}...")
                print(f"    expected: {expected!r}")
                print(f"    got:      {output!r}")
                failed += 1
        except Exception as e:
            label = code.splitlines()[0]
            print(f"  ERROR: {label!r}... -> {e}")
            import traceback

            traceback.print_exc()
            failed += 1

    print("=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    return failed


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Translate Adascript (.ady) to Python")
    parser.add_argument("file", nargs="?", help="source file to translate (reads stdin if omitted)")
    parser.add_argument("rest", nargs="*", help="arguments passed to the compiled program")
    parser.add_argument("-c", action="store_true", help="compile and run the generated Python file")
    parser.add_argument("--test", action="store_true", help="run built-in tests")
    args = parser.parse_args()
    if args.test:
        sys.exit(run_tests())
    else:
        main(args)
