#!/usr/bin/env python3
"""Python 3.14 source-to-source translator using parser combinators.

Parses Python source code using the hek_parsec combinator framework
and reconstructs it via to_py() methods on each AST node.

Comments and blank lines are preserved by collecting them as 'trivia'
in the tokenizer and attaching them to AST nodes. This approach is
language-agnostic — trivia travels with the AST, not with line numbers.

Usage:
    python3 hek_py3_py2py.py [file.py]       # translate a file
    echo "x = 1" | python3 hek_py3_py2py.py  # translate from stdin
"""

import sys
sys.path.insert(0, "..")

import sys
import token as token_mod
from types import MethodType

from hek_py3_parser import *  # fw() resolves names in calling module's globals
from hek_tokenize import Tokenizer


def InputSkipTrivia(code):
    """Create a token stream that skips COMMENT and NL tokens.

    Comments and blank lines are buffered as 'trivia' and stored in
    stream.trivia keyed by the next real token's position. This lets the
    parser work without seeing comments, while preserving them for
    reconstruction.

    The trick: we monkey-patch get_new_token on this specific Tokenizer
    instance so that all grammar rules (which call get_new_token internally)
    automatically skip trivia tokens.
    """
    gen = Tokenizer(code)
    gen.get_new_token_original = gen.get_new_token
    gen.get_new_token = MethodType(Tokenizer.get_new_token_skip_trivia, gen)
    gen.get_new_token()  # skip ENCODING token
    return gen


def parse_module_with_trivia(code):
    """Parse a full module, attaching trivia (comments/blanks) to each statement.

    Returns:
        stmts: list of AST nodes, each with a .leading_trivia attribute
        trailing_trivia: list of trivia tuples after the last statement
    """
    ParserState.reset()
    stream = InputSkipTrivia(code)
    stmts = []

    while True:
        # Check for end of input
        pos = stream.mark()
        try:
            tok = stream.get_new_token()
        except StopIteration:
            break
        if not tok or tok.type == token_mod.ENDMARKER:
            break
        # The trivia flushed during the peek is at (stream.mark() - 1),
        # the position of the first real token of this statement.
        first_token_pos = stream.mark() - 1
        stream.reset(pos)

        pre_pos = stream.mark()

        result = statement.parse(stream)
        if not result:
            break

        post_pos = stream.mark()
        node = result[0]
        # Leading trivia: only from the first real token position
        node.leading_trivia = stream.trivia.pop(first_token_pos, [])
        # Collect inner trivia (comments inside compound statement bodies).
        # Trivia at the same indent as the header belongs to the NEXT statement
        # (Python's tokenizer emits comments before DEDENT, inside the block).
        inner = []
        spill = []
        header_indent = (
            stream.tokens[first_token_pos][0].start[1]
            if first_token_pos < len(stream.tokens)
            else 0
        )
        for p in sorted(list(stream.trivia.keys())):
            if pre_pos < p < post_pos:
                for item in stream.trivia.pop(p):
                    kind, text, ind = item
                    if kind in ("comment", "blank") and ind <= header_indent:
                        spill.append(item)
                    elif spill:
                        # Once we start spilling, everything after spills too
                        spill.append(item)
                    else:
                        inner.append(item)
        node.inner_trivia = inner
        node._spill_trivia = spill
        stmts.append(node)

    # Collect trailing trivia (comments/blanks after the last statement)
    trailing = list(stream._trivia_buf)
    # Also check any trivia entries left in the dict
    for p in sorted(stream.trivia):
        trailing.extend(stream.trivia[p])

    return stmts, trailing


def translate(code):
    """Parse Python source and reconstruct it via to_py().

    Preserves comments and blank lines from the original source.
    Returns the reconstructed source string with a trailing newline.
    """
    if not code.strip():
        return code

    stmts, trailing = parse_module_with_trivia(code)

    output = []
    pending_spill = []  # spill trivia from previous compound statement
    for stmt in stmts:
        # Emit spill trivia from previous statement (comments at outer indent
        # that Python's tokenizer placed before DEDENT, inside the block)
        for kind, text, indent in pending_spill:
            if kind == "comment":
                output.append(" " * indent + text)
            else:
                output.append("")
        pending_spill = []

        trivia = getattr(stmt, "leading_trivia", [])
        # Split into pre-statement trivia and inline comments
        pre_trivia = [t for t in trivia if t[0] != "inline"]
        inline_trivia = [t for t in trivia if t[0] == "inline"]

        # Emit pre-statement trivia (comments and blank lines)
        for kind, text, indent in pre_trivia:
            if kind == "comment":
                output.append(" " * indent + text)
            else:  # blank
                output.append("")

        # Emit the reconstructed statement
        try:
            output.append(stmt.to_py(0))
        except TypeError:
            output.append(stmt.to_py())

        # Append inline comments to the statement's first line
        # (inline comments within the statement range are on the header line)
        for kind, text, indent in inline_trivia:
            output[-1] += "  " + text

        # Insert inner trivia (comments inside compound statement bodies)
        # Strategy: walk body lines and trivia items sequentially.
        # - "comment"/"blank" trivia goes BEFORE the next body line
        # - "inline" trivia attaches AFTER the previous body line
        inner = getattr(stmt, "inner_trivia", [])
        if inner:
            rendered = output.pop()
            lines = rendered.split("\n")
            header = lines[0]
            body_lines = lines[1:]
            injected = []
            inner_idx = 0
            for bline in body_lines:
                # Insert comment/blank trivia before this body line
                while inner_idx < len(inner) and inner[inner_idx][0] in (
                    "comment",
                    "blank",
                ):
                    kind, text, ind = inner[inner_idx]
                    injected.append(" " * ind + text if kind == "comment" else "")
                    inner_idx += 1
                injected.append(bline)
                # Attach inline trivia to this body line
                while inner_idx < len(inner) and inner[inner_idx][0] == "inline":
                    injected[-1] += "  " + inner[inner_idx][1]
                    inner_idx += 1
            # Any remaining trivia after the last body line
            while inner_idx < len(inner):
                kind, text, ind = inner[inner_idx]
                if kind == "inline":
                    if injected:
                        injected[-1] += "  " + text
                    else:
                        header += "  " + text
                elif kind == "comment":
                    injected.append(" " * ind + text)
                else:
                    injected.append("")
                inner_idx += 1
            output.append(header + "\n" + "\n".join(injected) if injected else header)

        # Capture spill trivia for the next statement
        pending_spill = getattr(stmt, "_spill_trivia", [])

    # Emit any remaining spill from the last statement
    for kind, text, indent in pending_spill:
        if kind == "comment":
            output.append(" " * indent + text)
        else:
            output.append("")

    # Emit trailing trivia
    for kind, text, indent in trailing:
        if kind == "inline":
            if output:
                output[-1] += "  " + text
            else:
                output.append(" " * indent + text)
        elif kind == "comment":
            output.append(" " * indent + text)
        else:
            output.append("")

    result = "\n".join(output)
    if not result.endswith("\n"):
        result += "\n"
    return result


def main():
    if len(sys.argv) > 1:
        with open(sys.argv[1]) as f:
            code = f.read()
    else:
        code = sys.stdin.read()
    print(translate(code), end="")


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
            "match x:\n    case 1:\n        pass\n",
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
    if len(sys.argv) > 1:
        main()
    else:
        run_tests()
