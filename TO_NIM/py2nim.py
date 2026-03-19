#!/usr/bin/env python3
"""Python 3.14 to Nim source-to-source translator using parser combinators.

Parses Python source code using the hek_parsec combinator framework
and translates it to Nim via to_nim() methods on each AST node.

Usage:
    python3 py2nim.py [file.py]       # translate a file
    echo "x = 1" | python3 py2nim.py  # translate from stdin
"""

import sys, os

_dir = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, os.path.join(_dir, ".."))
sys.path.insert(0, os.path.join(_dir, "..", "HPYTHON_GRAMMAR"))


import token as token_mod

from py3compound_stmt import *  # fw() resolves names in calling module's globals
from hek_tokenize import Tokenizer, RichNL, set_current_tokenizer

# Import Nim translation modules to register to_nim() methods
import hek_nim_parser  # noqa: F401 (registers compound stmt to_nim methods)


def Input(code):
    """Create a token stream for parsing."""
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


def _find_first_identifier(node):
    """Find the first IDENTIFIER leaf in an AST subtree."""
    if type(node).__name__ == "IDENTIFIER":
        return node.node if hasattr(node, "node") and isinstance(node.node, str) else str(node.nodes[0])
    if hasattr(node, "nodes"):
        for child in node.nodes:
            result = _find_first_identifier(child)
            if result:
                return result
    return None


def _walk_class_defs(node, hierarchy):
    """Recursively walk AST to find class definitions and their parents."""
    tname = type(node).__name__
    if tname == "class_def":
        cls_name = None
        parent = None
        for child in node.nodes:
            cname = type(child).__name__
            if cname == "IDENTIFIER":
                cls_name = child.node if hasattr(child, "node") and isinstance(child.node, str) else str(child.nodes[0])
            elif cname == "class_args":
                parent = _find_first_identifier(child)
                if parent in (None, "object"):
                    parent = None
            elif cname == "Several_Times":
                for seq in child.nodes:
                    if type(seq).__name__ == "class_args":
                        parent = _find_first_identifier(seq)
                        if parent in (None, "object"):
                            parent = None
        if cls_name:
            hierarchy[cls_name] = parent
    # Recurse into child nodes
    if hasattr(node, "nodes"):
        for child in node.nodes:
            if hasattr(child, "nodes"):
                _walk_class_defs(child, hierarchy)


def _prescan_classes(stmts):
    """Pre-scan parsed statements to find class inheritance relationships.
    Returns a set of class names that need ref object (involved in inheritance)."""
    hierarchy = {}  # class_name -> parent_name or None
    for stmt in stmts:
        _walk_class_defs(stmt, hierarchy)
    # Any class involved in inheritance needs ref
    ref_classes = set()
    for cls, parent in hierarchy.items():
        if parent:
            ref_classes.add(cls)
            ref_classes.add(parent)
            # Walk up the chain to mark all ancestors
            p = hierarchy.get(parent)
            while p:
                ref_classes.add(p)
                p = hierarchy.get(p)
    return ref_classes


def translate(code):
    """Parse Python source and translate to Nim via to_nim()."""
    if not code.strip():
        return code

    from hek_parsec import ParserState
    stmts, leading, trailing = parse_module(code)

    # Pre-scan: identify classes that need ref object (involved in inheritance)
    ParserState._ref_classes = _prescan_classes(stmts)

    ParserState.symbol_table.push_scope("module")
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

        # Emit the translated Nim statement
        try:
            rendered = stmt.to_nim(0)
        except TypeError:
            rendered = stmt.to_nim()
        # Strip trailing blank lines from compound statement bodies
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

    ParserState.symbol_table.pop_scope()

    # Deduplicate import lines (e.g., import sys + import os both -> import os)
    seen_imports = set()
    deduped = []
    for line in output:
        stripped = line.strip()
        if stripped.startswith("import "):
            if stripped in seen_imports:
                continue
            seen_imports.add(stripped)
        deduped.append(line)
    output = deduped

    # Insert collected Nim imports at the top (after any leading comments)
    if ParserState.nim_imports:
        import_line = "import " + ", ".join(sorted(ParserState.nim_imports))
        # Find the first non-comment, non-blank line
        insert_pos = 0
        for i, line in enumerate(output):
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                insert_pos = i
                break
        output.insert(insert_pos, import_line)
        # When nimpy is used, emit a len() helper for PyObject
        if "nimpy" in ParserState.nim_imports:
            helper = 'proc len(o: PyObject): int = pyBuiltinsModule().len(o).to(int)'
            # Insert right after the pyImport lines (find last pyImport line)
            helper_pos = len(output)
            for j in range(len(output) - 1, -1, -1):
                if 'pyImport(' in output[j]:
                    helper_pos = j + 1
                    break
            output.insert(helper_pos, helper)
            # If sys was imported via pyImport, initialize sys.argv from Nim args
            has_sys_import = any('pyImport("sys")' in line for line in output)
            if has_sys_import:
                argv_init = 'discard pyBuiltinsModule().setattr(sys, "argv", @[getAppFilename()] & commandLineParams())'
                output.insert(helper_pos + 1, argv_init)
                ParserState.nim_imports.add("std/cmdline")
                ParserState.nim_imports.add("os")
                # Re-generate the import line with the new module
                for k, line in enumerate(output):
                    if line.startswith("import "):
                        output[k] = "import " + ", ".join(sorted(ParserState.nim_imports))
                        break

    result = chr(10).join(output)
    # Deduplicate top-level type declarations.
    # When a type defined at module level (e.g. `type Cost_T = float`) is also
    # defined inside a function and hoisted, the first definition wins and the
    # duplicate is silently removed.  This only applies to identical names at
    # column 0; mangled names (State_T_2, etc.) are never duplicates.
    seen_types = set()
    deduped_lines = []
    for line in result.split(chr(10)):
        import re as _re_td
        m = _re_td.match(r'^type\s+(\w+)', line)
        if m:
            tname = m.group(1)
            if tname in seen_types:
                continue
            seen_types.add(tname)
        deduped_lines.append(line)
    result = chr(10).join(deduped_lines)
    # Post-process: fix initHashSet() to include type param from annotation
    import re as _re
    result = _re.sub(
        r':\s*HashSet\[(\w+)\]\s*=\s*initHashSet\(\)',
        lambda m: f': HashSet[{m.group(1)}] = initHashSet[{m.group(1)}]()',
        result
    )
    # Post-process: instantiate generic base methods for each concrete subclass.
    # Nim 2.2 can't dispatch generic method[S,D](Base[S,D]) to method(Child).
    import re as _re2

    _subclasses = []
    for m in _re2.finditer(r'type (\w+) = ref object of (\w+)\[([^\]]+)\]', result):
        _subclasses.append((m.group(1), m.group(2), m.group(3)))

    if not _subclasses:
        if not result.endswith(chr(10)):
            result += chr(10)
        return result

    _base_names = set(s[1] for s in _subclasses)
    _child_names = set(s[0] for s in _subclasses)
    _overridden = set()
    for m in _re2.finditer(r'method (\w+)\(self: (\w+)[,)]', result):
        if m.group(2) in _child_names:
            _overridden.add(m.group(1))

    _base_params = {}
    for child, base, params in _subclasses:
        _base_params.setdefault(base, set()).add(params)

    _GENERIC_PAT = _re2.compile(
        r'(method |iterator )(\w+)\[([^\]]+)\]\(self: (\w+)\[([^\]]+)\](.*?)\)(:\s*.+?\s+|\s+)?(\{[.]base[.]\}\s*)?(\s*=\s*)?$'
    )

    lines = result.split(chr(10))
    generic_methods = []  # ordered list of (key, value) tuples
    new_lines = []
    i = 0
    while i < len(lines):
        line = lines[i]
        gm = _GENERIC_PAT.match(line)
        if gm and gm.group(4) in _base_names:
            keyword = gm.group(1).strip()
            method_name = gm.group(2)
            gen_params = gm.group(3)
            base_name = gm.group(4)
            rest_params = gm.group(6)
            return_part = (gm.group(7) or "").rstrip()
            is_impl = gm.group(9) is not None

            body_lines = []
            if is_impl:
                i += 1
                while i < len(lines) and (lines[i].startswith("    ") or lines[i].strip() == ""):
                    body_lines.append(lines[i])
                    i += 1
                while body_lines and body_lines[-1].strip() == "":
                    body_lines.pop()
                gen_list = [p.strip() for p in gen_params.split(",")]
                generic_methods.append(((base_name, method_name), (gen_list, rest_params, return_part, body_lines, keyword)))
            else:
                i += 1
            continue
        new_lines.append(line)
        i += 1

    result_lines = []
    inserted_for = set()
    _emitted_sigs = set()  # track resolved method signatures to avoid redefinition
    # Build type alias resolution map
    _type_aliases = {}
    for m in _re2.finditer(r'^type (\w+) = (\w+)$', result, _re2.MULTILINE):
        _type_aliases[m.group(1)] = m.group(2)
    # Also map tuple types: type X = (a, b)
    for m in _re2.finditer(r'^type (\w+) = (\([^)]+\))$', result, _re2.MULTILINE):
        _type_aliases[m.group(1)] = m.group(2)
    def _resolve_type(t):
        seen = set()
        while t in _type_aliases and t not in seen:
            seen.add(t)
            t = _type_aliases[t]
        return t
    for line in new_lines:
        mm = _re2.match(r'method (\w+)\(self: (\w+)[,)]', line)
        if mm:
            child_name = mm.group(2)
            for cname, bname, params in _subclasses:
                if cname == child_name and (bname, params) not in inserted_for:
                    inserted_for.add((bname, params))
                    concrete_list = [p.strip() for p in params.split(",")]
                    for key, (gen_list, rest_params, return_part, body_lines, orig_kw) in generic_methods:
                        if key[0] != bname:
                            continue
                        subs = dict(zip(gen_list, concrete_list))
                        new_rest = rest_params
                        new_ret = return_part
                        new_body = list(body_lines)
                        for old_p, new_p in subs.items():
                            new_rest = _re2.sub(r'\b' + _re2.escape(old_p) + r'\b', new_p, new_rest)
                            new_ret = _re2.sub(r'\b' + _re2.escape(old_p) + r'\b', new_p, new_ret)
                            new_body = [_re2.sub(r'\b' + _re2.escape(old_p) + r'\b', new_p, bl) for bl in new_body]
                        concrete_base = ", ".join(concrete_list)
                        if key[1] in _overridden:
                            kw = "method"
                            pragma = " {.base.}"
                        elif orig_kw == "iterator":
                            kw = "iterator"
                            pragma = ""
                        else:
                            kw = "proc"
                            pragma = ""
                        sig = f"{kw} {key[1]}(self: {bname}[{concrete_base}]{new_rest}){new_ret}"
                        resolved_parts = [_resolve_type(p.strip()) for p in concrete_base.split(",")]
                        resolved_sig = f"{key[1]}:{','.join(resolved_parts)}"
                        if resolved_sig not in _emitted_sigs:
                            _emitted_sigs.add(resolved_sig)
                            result_lines.append(f"{sig}{pragma} =")
                            for bl in new_body:
                                result_lines.append(bl)
                            result_lines.append("")
                    break
        result_lines.append(line)
    result = chr(10).join(result_lines)

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
        nim_file = base + ".nim"
        with open(nim_file, "w") as f:
            f.write(output)
        print(f"Wrote {nim_file}")
        result = subprocess.run(["nim", "c", "-r", nim_file] + (args.rest or []))
        sys.exit(result.returncode)
    else:
        print(output, end="")


###############################################################################
# Tests
###############################################################################


def run_tests():
    print("=" * 60)
    print("Python 3.14 -> Nim Translator Tests")
    print("=" * 60)

    tests = [
        # --- simple statements ---
        (
            "x = 1\n",
            "var x = 1\n",
        ),
        (
            "x = 1\ny = 2\n",
            "var x = 1\nvar y = 2\n",
        ),
        (
            "x += 1\n",
            "x += 1\n",
        ),
        (
            "x //= 2\n",
            "x = x div 2\n",
        ),
        (
            "import os\n",
            'import os\n',
        ),
        (
            "from os import path\n",
            'import os\n',
        ),
        (
            "pass\n",
            "discard\n",
        ),
        (
            "return x\n",
            "return x\n",
        ),
        (
            "del x\n",
            "reset(x)\n",
        ),
        (
            "global x\n",
            "# global x\n",
        ),
        (
            "assert x\n",
            "assert x\n",
        ),
        (
            "x: int = 1\n",
            "var x: int = 1\n",
        ),
        # --- compound statements ---
        (
            "if x:\n    pass\n",
            "if x:\n    discard\n",
        ),
        (
            "if x:\n    a = 1\nelif y:\n    b = 2\nelse:\n    c = 3\n",
            "if x:\n    var a = 1\nelif y:\n    var b = 2\nelse:\n    var c = 3\n",
        ),
        (
            "while x:\n    pass\n",
            "while x:\n    discard\n",
        ),
        (
            "for x in xs:\n    pass\n",
            "for x in xs:\n    discard\n",
        ),
        (
            "try:\n    pass\nexcept ValueError:\n    pass\n",
            "try:\n    discard\nexcept ValueError:\n    discard\n",
        ),
        (
            "try:\n    pass\nfinally:\n    pass\n",
            "try:\n    discard\nfinally:\n    discard\n",
        ),
        (
            "with f():\n    pass\n",
            "with f():\n    discard\n",
        ),
        (
            "def f():\n    pass\n",
            "proc f() =\n    discard\n",
        ),
        (
            "def f(a, b=1):\n    return a\n",
            "proc f(a: auto, b: auto = 1): auto =\n    return a\n",
        ),
        (
            "def f(a: int) -> str:\n    pass\n",
            "proc f(a: int): string =\n    discard\n",
        ),
        (
            "class Foo:\n    pass\n",
            "type Foo = object of RootObj\nproc newFoo*(): Foo =\n    new(result)\n",
        ),
        (
            "class Foo(Bar):\n    pass\n",
            "type Foo = ref object of Bar\nproc newFoo*(): Foo =\n    new(result)\n",
        ),
        (
            "@dec\ndef f():\n    pass\n",
            "@dec\nproc f() =\n    discard\n",
        ),
        (
            "async def f():\n    pass\n",
            "proc f() {.async.} =\n    discard\n",
        ),
        (
            "case x:\n    when 1:\n        pass\n",
            "case x:\n    of 1:\n        discard\n",
        ),
        # --- mixed programs ---
        (
            "import os\ndef main():\n    return os\n",
            'import os\nproc main(): auto =\n    return os\n',
        ),
        (
            "x = 1\nif x:\n    y = 2\n",
            "var x = 1\nif x:\n    var y = 2\n",
        ),
        (
            "def f():\n    pass\nclass Foo:\n    pass\n",
            "proc f() =\n    discard\ntype Foo = object of RootObj\nproc newFoo*(): Foo =\n    new(result)\n",
        ),
        # --- nested ---
        (
            "if x:\n    if y:\n        pass\n",
            "if x:\n    if y:\n        discard\n",
        ),
        (
            "def f():\n    for x in xs:\n        if x:\n            return x\n",
            "proc f(): auto =\n    for x in xs:\n        if x:\n            return x\n",
        ),
        (
            "class Foo:\n    def bar(self):\n        pass\n",
            "type Foo = object of RootObj\nproc newFoo*(): Foo =\n    new(result)\nproc bar(self: Foo) =\n    discard\n",
        ),
        # --- expressions in statements ---
        (
            "x = 10 // 3\n",
            "var x = 10 div 3\n",
        ),
        (
            "x = a ** 2\n",
            "var x = a ^ 2\n",
        ),
        (
            "x = [1, 2, 3]\n",
            "var x = @[1, 2, 3]\n",
        ),
        # --- array vs seq literal ---
        (
            "var a: []int = [1, 2, 3]\n",
            "var a: seq[int] = @[1, 2, 3]\n",
        ),
        (
            "var a: [3]int = [1, 2, 3]\n",
            "var a: array[3, int] = [1, 2, 3]\n",
        ),
        (
            "x = {1: 2}\n",
            "import tables\nvar x = {1: 2}.toTable\n",
        ),
        (
            "x = None\n",
            "var x = nil\n",
        ),
        (
            "x = True\n",
            "var x = true\n",
        ),
        (
            "x = not y\n",
            "var x = not y\n",
        ),
        # --- comments ---
        (
            "# standalone comment\nx = 1\n",
            "# standalone comment\nvar x = 1\n",
        ),
        (
            "x = 1\n\ny = 2\n",
            "var x = 1\n\nvar y = 2\n",
        ),
        (
            "# comment 1\n# comment 2\nx = 1\n",
            "# comment 1\n# comment 2\nvar x = 1\n",
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
    parser = argparse.ArgumentParser(description="Translate HPython (.hpy) to Nim")
    parser.add_argument("file", nargs="?", help="source file to translate (reads stdin if omitted)")
    parser.add_argument("rest", nargs="*", help="arguments passed to the compiled program")
    parser.add_argument("-c", action="store_true", help="compile and run the generated Nim file")
    parser.add_argument("--test", action="store_true", help="run built-in tests")
    args = parser.parse_args()
    if args.test:
        sys.exit(run_tests())
    else:
        main(args)
