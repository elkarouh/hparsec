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
sys.path.insert(0, os.path.join(_dir, "..", "ADASCRIPT_GRAMMAR"))


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

    # Remove blank lines that were left behind by erased import statements
    # (mapped stdlib imports return None/'' from to_nim() and leave orphan blanks).
    # Strategy: collapse runs of more than one consecutive blank line at the top
    # of the output, and remove isolated blank lines that replaced a single statement.
    # Simpler and safer: strip leading blank lines entirely before inserting imports.
    while output and output[0] == '':
        output.pop(0)

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
        if ParserState.nim_pragmas:
            pragma_lines = [f"{{.{p}.}}" for p in sorted(ParserState.nim_pragmas)]
            for j, pl in enumerate(pragma_lines):
                output.insert(insert_pos + 1 + j, pl)
        # When nimpy is used, emit a len() helper for PyObject — but only
        # if the output actually calls len() somewhere (as a function, not method)
        # and has pyImport'd modules that could return PyObject values.
        if "nimpy" in ParserState.nim_imports:
            has_py_imports = any('pyImport(' in line for line in output)
            needs_len_helper = has_py_imports and any(
                'len(' in line and 'proc len' not in line
                for line in output
            )
            if needs_len_helper:
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
                helper_pos = len(output)
                for j in range(len(output) - 1, -1, -1):
                    if 'pyImport(' in output[j] or 'proc len(' in output[j]:
                        helper_pos = j + 1
                        break
                argv_init = 'discard pyBuiltinsModule().setattr(sys, "argv", @[getAppFilename()] & commandLineParams())'
                output.insert(helper_pos, argv_init)
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
    # Post-process: rewrite regex match/search variable pattern.
    # Python:  var m: Option[auto] = str.match(RE) / if m: / m.group(N) / m.captures[N]
    # Nim:     var m: RegexMatch    / if str.match(RE, m): / m.captures[N-1]
    import re as _re_rm
    def _fix_regex_match_var(text):
        lines = text.split(chr(10))
        out = []
        i = 0
        _regex_match_vars = {}  # var_name -> n_captures
        while i < len(lines):
            line = lines[i]
            # Detect re-assignment: NAME = STR.(match|find)(REGEX) for known regex match vars
            _ra = _re_rm.match(
                r'^(\s*)(\w+)\s*=\s*(\S.*)\.(match|find)\((\w+)\)\s*$',
                line
            )
            if _ra:
                ra_indent, ra_var, ra_str, ra_method, ra_regex = (
                    _ra.group(1), _ra.group(2), _ra.group(3),
                    _ra.group(4), _ra.group(5)
                )
                if ra_var in _regex_match_vars:
                    nim_method = "match" if ra_method == "match" else "find"
                    # Rewrite next `if VAR:` or `if not VAR:` line
                    if i + 1 < len(lines):
                        next_line = lines[i + 1]
                        _if_m = _re_rm.match(r'^(\s*)if\s+(not\s+)?' + ra_var + r':\s*$', next_line)
                        if _if_m:
                            negated = bool(_if_m.group(2))
                            call = f"{ra_str}.{nim_method}({ra_regex}, {ra_var})"
                            if nim_method == "find":
                                cond = f"{call} < 0" if negated else f"{call} >= 0"
                            else:
                                cond = f"not {call}" if negated else call
                            out.append(f"{_if_m.group(1)}if {cond}:")
                            i += 2
                            while i < len(lines) and (lines[i].startswith(_if_m.group(1) + "    ") or lines[i].strip() == ""):
                                bl = lines[i]
                                bl = _re_rm.sub(
                                    ra_var + r'\.group\((\d+)\)',
                                    lambda g: f"{ra_var}[{int(g.group(1)) - 1}]",
                                    bl
                                )
                                out.append(bl)
                                i += 1
                            continue
            # Detect: (indent)var NAME: Option[auto] = STR.(match|find)(REGEX)
            _m = _re_rm.match(
                r'^(\s*)(var\s+(\w+):\s*Option\[auto\]\s*=\s*(\S.*)\.(match|find)\((\w+)\))(\s*)$',
                line
            )
            if _m:
                indent, _, var_name, str_expr, method, regex_var = (
                    _m.group(1), _m.group(2), _m.group(3),
                    _m.group(4), _m.group(5), _m.group(6)
                )
                nim_method = "match" if method == "match" else "find"
                # Determine how many capture groups are used (scan ahead)
                max_group = 0
                for _scan_line in lines[i:i+50]:
                    for _g in _re_rm.findall(var_name + r'\.group\((\d+)\)', _scan_line):
                        max_group = max(max_group, int(_g))
                n_captures = max(max_group, 1)
                # Track var_name -> n_captures so re-assignments can be rewritten too
                _regex_match_vars[var_name] = n_captures
                out.append(f"{indent}var {var_name}: array[{n_captures}, string]")
                # Rewrite next `if VAR_NAME:` line
                if i + 1 < len(lines):
                    next_line = lines[i + 1]
                    _if_m = _re_rm.match(r'^(\s*)if\s+' + var_name + r':\s*$', next_line)
                    if _if_m:
                        out.append(f"{_if_m.group(1)}if {str_expr}.{nim_method}({regex_var}, {var_name}):")
                        i += 2
                        # Rewrite m.group(N) -> m[N-1] in the block
                        while i < len(lines) and (lines[i].startswith(_if_m.group(1) + "    ") or lines[i].strip() == ""):
                            bl = lines[i]
                            bl = _re_rm.sub(
                                var_name + r'\.group\((\d+)\)',
                                lambda g: f"{var_name}[{int(g.group(1)) - 1}]",
                                bl
                            )
                            out.append(bl)
                            i += 1
                        continue
                i += 1
                continue
            out.append(line)
            i += 1
        return chr(10).join(out), _regex_match_vars
    result, _regex_match_vars = _fix_regex_match_var(result)
    # Second pass: rewrite any remaining VAR.group(N) for known regex match vars
    for _rmv in _regex_match_vars:
        import re as _re_rmv
        result = _re_rmv.sub(
            _rmv + r'\.group\((\d+)\)',
            lambda g, v=_rmv: f"{v}[{int(g.group(1)) - 1}]",
            result
        )

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
            "proc f(a: auto, b: auto = 1) =\n    return a\n",
        ),
        (
            "def f(a: int) -> str:\n    pass\n",
            "proc f(a: int): string =\n    discard\n",
        ),
        (
            "class Foo:\n    pass\n",
            "type Foo = object of RootObj\nproc newFoo*(): Foo =\n    result = Foo()\n",
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
            'import os\nproc main() =\n    return os\n',
        ),
        (
            "x = 1\nif x:\n    y = 2\n",
            "var x = 1\nif x:\n    var y = 2\n",
        ),
        (
            "def f():\n    pass\nclass Foo:\n    pass\n",
            "proc f() =\n    discard\ntype Foo = object of RootObj\nproc newFoo*(): Foo =\n    result = Foo()\n",
        ),
        # --- nested ---
        (
            "if x:\n    if y:\n        pass\n",
            "if x:\n    if y:\n        discard\n",
        ),
        (
            "def f():\n    for x in xs:\n        if x:\n            return x\n",
            "proc f() =\n    for x in xs:\n        if x:\n            return x\n",
        ),
        (
            "class Foo:\n    def bar(self):\n        pass\n",
            "type Foo = object of RootObj\nproc newFoo*(): Foo =\n    result = Foo()\nproc bar(self: Foo) =\n    discard\n",
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
        # --- bashisms ---
        (
            "$0\n",
            "import os\ngetAppFilename()\n",
        ),
        (
            "$1\n",
            "import os\n(if paramCount() >= 1: paramStr(1) else: \"\")\n",
        ),
        (
            "$2\n",
            "import os\n(if paramCount() >= 2: paramStr(2) else: \"\")\n",
        ),
        (
            "$@\n",
            "import os\ncommandLineParams()\n",
        ),
        (
            "$#\n",
            "import os\nparamCount()\n",
        ),
        (
            "$HOME\n",
            "import os\ngetEnv(\"HOME\")\n",
        ),
        (
            "name = $1\n",
            "import os\nvar name = (if paramCount() >= 1: paramStr(1) else: \"\")\n",
        ),
        (
            "if $# < 2:\n    pass\n",
            "import os\nif paramCount() < 2:\n    discard\n",
        ),
        (
            "for arg in $@:\n    pass\n",
            "import os\nfor arg in commandLineParams():\n    discard\n",
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


def main(argv=None):
    """Entry point with nim-style argument parsing.

    Mirrors the nim compiler's own CLI so muscle memory transfers directly::

        nim  c        [-r] [nim-flags] file.nim  [-- prog-args]
        py2nim  c     [-r] [nim-flags] file.ady  [-- prog-args]

    Subcommands (anything that nim accepts: c, cpp, js, check, doc, …) are
    passed straight through to the nim compiler.  All unrecognised flags (those
    starting with ``-``) are also forwarded to nim unchanged.

    Modes
    -----
    py2nim                          read stdin, print Nim to stdout
    py2nim -t file.ady              transpile → write .nim to cache, stop
    py2nim file.ady                 shebang default: compile + run (= c -r)
    py2nim c file.ady               transpile → compile (artifacts in cache)
    py2nim c -r file.ady            transpile → compile → run
    py2nim c -r file.ady -- a b     same, pass a b as program arguments
    py2nim --test                   run built-in self-tests

    Cache layout
    ------------
    All generated artifacts go to ``~/.cache/hparsec/`` so source directories
    stay clean.  Each script gets its own subdirectory keyed by a SHA-1 hash
    of its absolute path (inspired by nimbang / rdmd)::

        ~/.cache/hparsec/cache-<HASH>/script.nim     ← transpiled source
        ~/.cache/hparsec/cache-<HASH>/.script        ← compiled binary
        ~/.cache/hparsec/cache-<HASH>/nimcache/      ← nim object cache

    Subsequent runs are fast: if neither the source nor the compiled binary
    have changed, py2nim skips all transpilation and compilation and directly
    execs the cached binary.

    Shebang usage
    -------------
    Because the Linux kernel only passes a single token after ``/usr/bin/env``
    in a shebang line, ``#!/usr/bin/env py2nim c -r`` is illegal.  Use::

        #!/usr/bin/env py2nim

    When py2nim is invoked with a ``.ady`` file and no subcommand it defaults
    to ``c -r``, so the three-tier up-to-date check and direct binary execution
    all work transparently.

    Per-file compiler options (#ady2nim-args)
    ----------------------------------------
    Add a ``#ady2nim-args`` directive as the **second line** of the file to set
    per-file nim compiler options (inspired by nimbang)::

        #!/usr/bin/env py2nim
        #ady2nim-args c -d:release

    The directive is split on whitespace.  If the first token is a nim
    subcommand (``c``, ``cpp``, …) it sets the default subcommand for that
    file; remaining tokens are forwarded to the nim compiler.  Flags given
    explicitly on the command line always override the directive.

    Up-to-date check (three tiers, like make)
    -----------------------------------------
    When a binary-producing subcommand (c, cpp, …) is given, py2nim runs
    three mtime comparisons before doing any work:

    1. **.nim older than .ady** → re-transpile, then continue to tier 2.
    2. **executable older than .nim** → skip transpilation, re-compile.
    3. **both up to date** → skip everything; with ``-r`` just exec the
       existing binary directly without invoking nim at all.

    Non-binary subcommands (check, doc, …) stop after tier 1 and always
    invoke nim (they produce no persistent executable to compare).
    """
    import subprocess

    if argv is None:
        argv = sys.argv[1:]

    # ------------------------------------------------------------------ #
    # 1.  Intercept --test before any other parsing                       #
    # ------------------------------------------------------------------ #
    if "--test" in argv:
        sys.exit(run_tests())

    # ------------------------------------------------------------------ #
    # 2.  nim-style manual argument parsing                               #
    #                                                                     #
    #   py2nim [subcommand] [flags...] [file.ady] [-- prog-args...]      #
    #                                                                     #
    #   We don't use argparse here because argparse doesn't handle        #
    #   nim-style --flag:value pairs (the colon is unusual) and we want  #
    #   to forward unknown flags verbatim without error.                  #
    # ------------------------------------------------------------------ #
    NIM_COMMANDS = {
        "c", "cc", "cpp", "objc", "js", "e",
        "check", "doc", "doc2", "rst2html", "rst2tex",
        "jsondoc", "ctags", "buildindex", "genDepend",
        "dump", "secret", "nop",
    }

    subcommand = None   # nim subcommand (c, cpp, js, …) if given
    run = False         # -r / --run
    transpile_only = False  # -t / --transpile: write/print .nim, stop there
    ady_file = None     # the .ady source file
    nim_flags = []      # flags forwarded verbatim to nim
    prog_args = []      # program arguments (after --)

    i = 0
    after_dashdash = False

    while i < len(argv):
        arg = argv[i]

        if after_dashdash:
            prog_args.append(arg)

        elif arg == "--":
            after_dashdash = True

        elif i == 0 and arg in NIM_COMMANDS:
            subcommand = arg

        elif arg in ("-r", "--run"):
            run = True

        elif arg in ("-t", "--transpile"):
            transpile_only = True

        elif ady_file is None and arg.startswith("-"):
            # Unknown flag before the .ady file — forward to nim unchanged
            # (handles -d:, -o:, --verbosity:, --gc:, --opt:, etc.)
            nim_flags.append(arg)

        elif ady_file is None:
            ady_file = arg

        else:
            # Any arg (flag or positional) after the .ady file goes to the program
            prog_args.append(arg)

        i += 1

    # ------------------------------------------------------------------ #
    # 2b. Shebang default: no subcommand + .ady file → c -r              #
    #                                                                     #
    #   The Linux kernel only passes a single token after /usr/bin/env   #
    #   in a shebang line, so '#!/usr/bin/env py2nim c -r' is illegal.  #
    #   Instead, write '#!/usr/bin/env py2nim' and rely on this default: #
    #   when py2nim is called with a .ady file but no subcommand (and    #
    #   -t was not given), it behaves exactly as if 'c -r' had been      #
    #   specified.                                                        #
    #                                                                     #
    #   To transpile only (print .nim to stdout), use -t / --transpile.  #
    # ------------------------------------------------------------------ #
    if ady_file and subcommand is None and not transpile_only and ady_file.endswith(".ady"):
        subcommand = "c"
        run = True

    # ------------------------------------------------------------------ #
    # 3.  Read source                                                     #
    # ------------------------------------------------------------------ #
    if ady_file:
        with open(ady_file) as f:
            code = f.read()
    else:
        code = sys.stdin.read()

    # ------------------------------------------------------------------ #
    # 3b. Parse optional #ady2nim-args directive (nimbang-style)          #
    #                                                                     #
    #   If the second non-empty line of the .ady file starts with        #
    #   "#ady2nim-args", the rest of that line is split into tokens and   #
    #   prepended to nim_flags (explicit CLI flags still take priority). #
    #                                                                     #
    #   Example:                                                          #
    #     #!/usr/bin/env py2nim                                           #
    #     #ady2nim-args c -d:release                                       #
    # ------------------------------------------------------------------ #
    _ADY2NIM_ARGS_PREFIX = "#ady2nim-args "
    if ady_file:
        lines = code.splitlines()
        # Skip the shebang (line 0), look at line 1
        if len(lines) > 1 and lines[1].startswith(_ADY2NIM_ARGS_PREFIX):
            directive_tokens = lines[1][len(_ADY2NIM_ARGS_PREFIX):].split()
            # First token may be a subcommand (c, cpp, …); remaining are flags
            if directive_tokens:
                first = directive_tokens[0]
                if first in NIM_COMMANDS:
                    if subcommand is None:
                        subcommand = first
                    directive_tokens = directive_tokens[1:]  # always consume it
                # Prepend so explicit CLI flags override the directive
                nim_flags = directive_tokens + nim_flags

    # ------------------------------------------------------------------ #
    # 4.  Resolve cache paths (nimbang-style)                            #
    #                                                                     #
    #   All generated artifacts go to ~/.cache/hparsec/ so the source   #
    #   directory stays clean.  A hash of the absolute .ady path gives  #
    #   each script its own isolated subdirectory, just like nimbang.   #
    #                                                                     #
    #   Layout inside the cache:                                          #
    #     ~/.cache/hparsec/<HASH>/script.nim    ← transpiled source     #
    #     ~/.cache/hparsec/<HASH>/.script       ← compiled binary       #
    #     ~/.cache/hparsec/<HASH>/nimcache/     ← nim object cache      #
    # ------------------------------------------------------------------ #
    def _cache_paths(ady_path):
        """Return (cache_dir, nim_file, exe_file, nimcache_dir) for *ady_path*."""
        import hashlib
        abs_path = os.path.realpath(ady_path)
        digest   = hashlib.sha1(abs_path.encode()).hexdigest()[:16].upper()
        base_dir = os.path.join(os.path.expanduser("~"), ".cache", "hparsec")
        cache_dir = os.path.join(base_dir, "cache-" + digest)
        stem     = os.path.splitext(os.path.basename(ady_path))[0]
        ext      = ".exe" if sys.platform == "win32" else ""
        nim_file  = os.path.join(cache_dir, stem + ".nim")
        exe_file  = os.path.join(cache_dir, "." + stem + ext)
        nimcache  = os.path.join(cache_dir, "nimcache")
        return cache_dir, nim_file, exe_file, nimcache

    # ------------------------------------------------------------------ #
    # 5.  Three-tier up-to-date check then build/run                     #
    #                                                                     #
    #   tier 1 — transpile:  .nim older than .ady  (or .nim missing)    #
    #   tier 2 — compile:    exe  older than .nim  (or exe  missing)     #
    #   tier 3 — run:        nothing to do, just exec the existing exe   #
    #                                                                     #
    #   Compilation-only subcommands (check, doc, …) have no executable, #
    #   so the exe check is skipped for them.                             #
    # ------------------------------------------------------------------ #
    if ady_file and subcommand:
        cache_dir, nim_file, exe_file, nimcache_dir = _cache_paths(ady_file)
        os.makedirs(cache_dir, exist_ok=True)

        # Install stdlib.nim into the cache dir so `import stdlib` works.
        import shutil as _shutil
        _stdlib_src = os.path.join(_dir, "stdlib.nim")
        _stdlib_dst = os.path.join(cache_dir, "stdlib.nim")
        if os.path.exists(_stdlib_src):
            if not os.path.exists(_stdlib_dst) or \
               os.path.getmtime(_stdlib_src) > os.path.getmtime(_stdlib_dst):
                _shutil.copy2(_stdlib_src, _stdlib_dst)

        ady_mtime = os.path.getmtime(ady_file)
        nim_mtime = os.path.getmtime(nim_file) if os.path.exists(nim_file) else 0
        exe_mtime = os.path.getmtime(exe_file) if os.path.exists(exe_file) else 0

        # Transpiler source files: if any are newer than the .nim, retranspile.
        transpiler_mtime = max(
            os.path.getmtime(p)
            for p in [
                os.path.join(_dir, f)
                for f in os.listdir(_dir)
                if f.endswith(".py")
            ]
        )

        # --- tier 1: transpile? ---
        need_transpile = nim_mtime < max(ady_mtime, transpiler_mtime)
        if need_transpile:
            nim_output = translate(code)
            with open(nim_file, "w") as f:
                f.write(nim_output)
            # Refresh mtime after write so tier-2 comparison is accurate
            nim_mtime = os.path.getmtime(nim_file)
            print(f"# transpiled → {nim_file}", file=sys.stderr)
        else:
            print(f"# up to date: {nim_file}", file=sys.stderr)

        # --- tier 2: compile? ---
        # Only meaningful for binary-producing subcommands.
        # If -r is not set and the exe is already up to date, skip nim entirely.
        BINARY_COMMANDS = {"c", "cc", "cpp", "objc"}
        produces_binary = subcommand in BINARY_COMMANDS

        # If we re-transpiled, always recompile regardless of exe mtime.
        need_compile = need_transpile or (exe_mtime < nim_mtime)

        if produces_binary and not run:
            if not need_compile:
                print(f"# up to date: {exe_file}", file=sys.stderr)
                sys.exit(0)

        if produces_binary and run:
            if not need_compile:
                print(f"# up to date: {exe_file}", file=sys.stderr)
                cmd = [exe_file] + prog_args
                result = subprocess.run(cmd)
                sys.exit(result.returncode)

        # --- tier 3: invoke nim ---
        cmd = ["nim", subcommand] + nim_flags
        cmd += [f"--nimcache:{nimcache_dir}", f"--out:{exe_file}"]
        if run and not prog_args:
            # Let nim handle -r directly (no separate exec needed)
            cmd.append("-r")
        cmd.append(nim_file)

        print(f"# nim {' '.join(cmd[1:])}", file=sys.stderr)
        result = subprocess.run(cmd)
        if result.returncode != 0:
            sys.exit(result.returncode)

        # After successful compile, exec the binary with prog_args (or if -r
        # was requested with prog_args, which nim can't forward via --out).
        if produces_binary and (prog_args or run):
            exec_cmd = [exe_file] + prog_args
            result = subprocess.run(exec_cmd)
        sys.exit(result.returncode)

    else:
        # No subcommand (or -t/--transpile explicitly given):
        # transpile and either write .nim or print to stdout.
        nim_output = translate(code)
        if ady_file and transpile_only:
            # -t with a file: write the .nim into the cache directory
            cache_dir, nim_file, _exe, _nc = _cache_paths(ady_file)
            os.makedirs(cache_dir, exist_ok=True)
            with open(nim_file, "w") as f:
                f.write(nim_output)
            print(f"# transpiled → {nim_file}", file=sys.stderr)
        else:
            print(nim_output, end="")


if __name__ == "__main__":
    main()
