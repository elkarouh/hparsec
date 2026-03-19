#!/usr/bin/env python3
"""Nim translation methods for Python 3.14 simple statements.

Adds to_nim() methods to the statement parser classes defined in
hek_py3_stmt.py. Import this module to enable .to_nim() on statement AST nodes.

Usage:
    from hek_nim_stmt import *
    ast = parse_stmt("x = 1")
    print(ast.to_nim())  # var x = 1
"""

import sys, os
_dir = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(_dir, ".."))
sys.path.insert(0, os.path.join(_dir, "..", "HPYTHON_GRAMMAR"))
# (no TO_PYTHON dependency needed)

from hek_parsec import method, ParserState
from py3stmt import *  # noqa: F403 — need all parser rule names
from py3stmt import parse_stmt
import hek_nim_expr  # noqa: F401 — registers expr to_nim() methods
import hek_nim_declarations  # noqa: F401
from hek_nim_expr import _infer_literal_nim_type

###############################################################################
# to_nim() methods
###############################################################################

# Augmented assignment operator map: Python augop -> (nim_op, needs_expansion)
# needs_expansion=True means we must expand x op= y -> x = x nim_op y
_AUGOP_TO_NIM = {
    "+=": ("+=", False),
    "-=": ("-=", False),
    "*=": ("*=", False),
    "/=": ("/=", False),
    "//=": ("div", True),
    "%=": ("mod", True),
    "**=": ("^", True),
    "@=": ("@", True),
    "<<=": ("shl", True),
    ">>=": ("shr", True),
    "&=": ("and", True),
    "|=": ("or", True),
    "^=": ("xor", True),
}

# Python stdlib module -> Nim import mapping
_PY_MODULE_TO_NIM = {
    "sys": "os",           # sys.argv -> paramStr(), sys.exit -> quit()
    "os": "os",
    "os.path": "os",
    "math": "math",
    "json": "json",
    "re": "re",
    "time": "times",       # time.perf_counter -> cpuTime()
    "typing": None,        # typing imports are erased
    "stdlib": "stdlib",    # local stdlib module
}


# --- visible tokens ---
@method(augop)
def to_nim(self):
    """augop: '+=' | '-=' | '*=' | '/=' | '%=' | '&=' | '|=' | '^=' | '<<=' | '>>=' | '**=' | '//='"""
    return self.nodes[0].nodes[0]  # raw op string, translated at aug_assign level


@method(V_EQUAL)
def to_nim(self):
    """V_EQUAL: visible '=' token -> Nim: '='"""
    return "="


@method(V_COLON)
def to_nim(self):
    """V_COLON: visible ':' operator token"""
    return ":"


@method(V_DOT)
def to_nim(self):
    """V_DOT: visible '.' token -> unchanged"""
    return "."


# --- assignment ---
@method(assign_stmt)
def to_nim(self):
    """assign_stmt: star_expressions ('=' star_expressions)+
    Python: a = b = 1  ->  Nim: var a = 1 (chained not supported, just use =)
    """
    parts = [self.nodes[0].to_nim()]
    rhs_node = None
    for node in self.nodes[1:]:
        if not hasattr(node, "nodes") or not node.nodes:
            continue
        for seq in node.nodes:
            if hasattr(seq, "nodes") and len(seq.nodes) >= 2:
                rhs_node = seq.nodes[1]
                parts.append(rhs_node.to_nim())
    # Skip var for dotted assignments (field mutation), indexed assignments,
    # and variables already declared in the current scope
    lhs = parts[0]
    if "." in lhs or "[" in lhs:
        prefix = ""
    elif ParserState.symbol_table.lookup(lhs):
        prefix = ""
    else:
        prefix = "var "
    # Nim's implicit 'result' variable: no var needed inside typed procs
    if lhs == "result" and getattr(ParserState, '_current_return_type', ''):
        prefix = ""
    # Record type in symbol table (after checking for re-declaration)
    name = self.nodes[0].to_nim() if hasattr(self.nodes[0], "to_nim") else None
    if name and rhs_node and ParserState.symbol_table.depth() > 0:
        inferred = _infer_literal_nim_type(rhs_node)
        ParserState.symbol_table.add(name, inferred, "var")
    if prefix == "var " and len(parts) == 2 and parts[1] in ("@[]", "@{}", "initTable()"):
        import sys as _sys
        print(f"Error: '{lhs} = {parts[1]}' needs a type annotation (e.g. '{lhs}: Type = {parts[1]}')", file=_sys.stderr)
    return prefix + " = ".join(parts)


# --- augmented assignment ---
@method(aug_assign_stmt)
def to_nim(self):
    """aug_assign_stmt: star_expressions augop expressions
    Translate augmented ops: //= -> expand to div, etc.
    """
    target = self.nodes[0].to_nim()
    op_node = self.nodes[1]
    py_op = (
        op_node.nodes[0]
        if isinstance(op_node.nodes[0], str)
        else op_node.nodes[0].nodes[0]
    )
    value = self.nodes[2].to_nim()
    nim_op, expand = _AUGOP_TO_NIM.get(py_op, (py_op, False))
    if expand:
        return f"{target} = {target} {nim_op} {value}"
    return f"{target} {nim_op} {value}"


# --- annotated assignment ---
@method(ann_assign_stmt)
def to_nim(self):
    """ann_assign_stmt: IDENTIFIER ':' type_annotation ('=' expression)?
    Python: x: int = 1  ->  Nim: var x: int = 1
    """
    name = self.nodes[0].to_nim()
    annotation = self.nodes[2].to_nim()
    # Record type in symbol table
    if ParserState.symbol_table.depth() > 0:
        ParserState.symbol_table.add(name, annotation, "var")
    # Nim's implicit result variable: skip var and type inside typed procs
    if name == "result" and getattr(ParserState, '_current_return_type', ''):
        kw = ""
        result = f"{name}"  # just 'result', no type annotation needed
    else:
        kw = "var "
        result = f"{kw}{name}: {annotation}"
    for node in self.nodes[3:]:
        if not hasattr(node, "nodes") or not node.nodes:
            continue
        for seq in node.nodes:
            if hasattr(seq, "nodes") and len(seq.nodes) >= 2:
                value = seq.nodes[1].to_nim()
                # For array types, strip @ prefix from list literals
                if annotation.startswith("array[") and value.startswith("@["):
                    value = value[1:]
                # initTable() needs explicit type params
                if value == "initTable()" and "Table[" in annotation:
                    import re as _re2
                    _m = _re2.search(r"Table\[(.+)\]", annotation)
                    if _m:
                        value = f"initTable[{_m.group(1)}]()"
                # array types: {} is unnecessary — arrays are zero-initialized
                if value == "initTable()" and annotation.startswith("array["):
                    value = ""
                # initHashSet() sentinel: resolve to correct Nim set initialiser
                if value == "initHashSet()":
                    import re as _re2
                    if "HashSet[" in annotation:
                        _m = _re2.search(r"HashSet\[(.+)\]", annotation)
                        if _m:
                            value = f"initHashSet[{_m.group(1)}]()"
                        ParserState.nim_imports.add("sets")
                    elif annotation.startswith("set["):
                        value = "{}"  # built-in ordinal set empty literal
                    else:
                        ParserState.nim_imports.add("sets")
                        # bare fallback — no type params available
                if value:
                    result += f" = {value}"
    return result



# --- declaration with keyword (var/let/const) ---

@method(decl_ann_assign_stmt)
def to_nim(self):
    """decl_ann_assign_stmt: decl_keyword IDENTIFIER ':' type_annotation ('=' expression)?"""
    keyword = self.nodes[0].nodes[0]
    name = self.nodes[1].to_nim()
    annotation = self.nodes[3].to_nim()
    if ParserState.symbol_table.depth() > 0:
        ParserState.symbol_table.add(name, annotation, keyword)
    result = f"{keyword} {name}: {annotation}"
    for node in self.nodes[4:]:
        if not hasattr(node, "nodes") or not node.nodes:
            continue
        for seq in node.nodes:
            if hasattr(seq, "nodes") and len(seq.nodes) >= 2:
                value = seq.nodes[1].to_nim()
                # For array types, strip @ prefix from list literals
                if annotation.startswith("array[") and value.startswith("@["):
                    value = value[1:]
                # initTable() needs explicit type params
                if value == "initTable()" and "Table[" in annotation:
                    import re as _re2
                    _m = _re2.search(r"Table\[(.+)\]", annotation)
                    if _m:
                        value = f"initTable[{_m.group(1)}]()"
                # array types: {} is unnecessary — arrays are zero-initialized
                if value == "initTable()" and annotation.startswith("array["):
                    value = ""
                # initHashSet() sentinel: resolve to correct Nim set initialiser
                if value == "initHashSet()":
                    import re as _re2
                    if "HashSet[" in annotation:
                        _m = _re2.search(r"HashSet\[(.+)\]", annotation)
                        if _m:
                            value = f"initHashSet[{_m.group(1)}]()"
                        ParserState.nim_imports.add("sets")
                    elif annotation.startswith("set["):
                        value = "{}"  # built-in ordinal set empty literal
                    else:
                        ParserState.nim_imports.add("sets")
                        # bare fallback — no type params available
                if value:
                    result += f" = {value}"
    return result

# --- return ---
@method(decl_tuple_unpack)
def to_nim(self):
    """decl_tuple_unpack: let/var/const (x, y) = expr -> Nim let/var (x, y) = expr"""
    kw = str(self.nodes[0].node)  # var/let/const
    targets = self.nodes[1].to_nim()  # paren_group
    value = self.nodes[3].to_nim()  # expression (nodes[2] is V_EQUAL)
    return f"{kw} {targets} = {value}"

@method(return_val)
def to_nim(self):
    """return_val: 'return' star_expressions -> Nim: 'return expr'; Option-typed returns wrapped in some()/none()"""
    val = self.nodes[0].to_nim()
    ret_type = getattr(ParserState, "_current_return_type", "")
    if ret_type and "Option[" in ret_type:
        import re as _re
        m = _re.search(r"Option\[(.+?)\]", ret_type)
        if m:
            inner_type = m.group(1)
            if val == "nil":
                return f"return none({inner_type})"
            else:
                return f"return some({val})"
    if val == "nil" and ret_type and "seq[" in ret_type:
        return "return @[]"
    # If return value contains commas (tuple), wrap in parens for Nim
    if "," in val and not val.startswith("("):
        val = f"({val})"
    return f"return {val}"


@method(return_bare)
def to_nim(self):
    """return_bare: 'return' (bare) -> Nim: 'return'"""
    return "return"


@method(return_stmt)
def to_nim(self):
    """return_stmt: return_val | return_bare"""
    return self.nodes[0].to_nim()


# --- pass / break / continue ---
@method(pass_stmt)
def to_nim(self):
    """pass_stmt: 'pass' -> Nim: 'discard'"""
    return "discard"


@method(break_stmt)
def to_nim(self):
    """break_stmt: 'break' -> Nim: 'break'"""
    return "break"


@method(continue_stmt)
def to_nim(self):
    """continue_stmt: 'continue' -> Nim: 'continue'"""
    return "continue"


# --- del ---
@method(del_stmt)
def to_nim(self):
    """del x -> reset(x)"""
    return f"reset({self.nodes[0].to_nim()})"


# --- assert ---
@method(assert_msg)
def to_nim(self):
    """assert_msg: 'assert' expression ',' expression -> Nim: 'assert cond, msg'"""
    return f"assert {self.nodes[0].to_nim()}, {self.nodes[1].to_nim()}"


@method(assert_simple)
def to_nim(self):
    """assert_simple: 'assert' expression -> Nim: 'assert cond'"""
    return f"assert {self.nodes[0].to_nim()}"


@method(assert_stmt)
def to_nim(self):
    """assert_stmt: assert_msg | assert_simple"""
    return self.nodes[0].to_nim()


# --- raise ---
@method(raise_from)
def to_nim(self):
    """raise X from Y -> raise X (Nim has no 'from' clause)"""
    return f"raise {self.nodes[0].to_nim()}"


_PY_EXCEPTIONS = {
    "NotImplementedError": "CatchableError",
    "ValueError": "ValueError",
    "RuntimeError": "CatchableError",
    "TypeError": "CatchableError",
    "IndexError": "IndexDefect",
    "KeyError": "KeyError",
    "Exception": "CatchableError",
}

@method(raise_exc)
def to_nim(self):
    """raise_exc: 'raise' expression -> Nim: 'raise newException(Type, msg)' for known Python exceptions"""
    import re as _re
    val = self.nodes[0].to_nim()
    # Translate Python exception constructors: raise XError("msg") -> raise newException(NimError, "msg")
    m = _re.match(r"(\w+)\((.*)\)$", val)
    if m and m.group(1) in _PY_EXCEPTIONS:
        nim_exc = _PY_EXCEPTIONS[m.group(1)]
        args = m.group(2)
        return f"raise newException({nim_exc}, {args})"
    return f"raise {val}"


@method(raise_bare)
def to_nim(self):
    """raise_bare: 'raise' (re-raise) -> Nim: 'raise'"""
    return "raise"


@method(raise_stmt)
def to_nim(self):
    """raise_stmt: raise_from | raise_exc | raise_bare"""
    return self.nodes[0].to_nim()


# --- global / nonlocal (no Nim equivalent — emit as comment) ---
@method(global_stmt)
def to_nim(self):
    """global_stmt: 'global' IDENTIFIER (',' IDENTIFIER)* -> Nim: emitted as '# global ...' comment (no Nim equivalent)"""
    parts = [self.nodes[0].to_nim()]
    for node in self.nodes[1:]:
        if not hasattr(node, "nodes") or not node.nodes:
            continue
        for seq in node.nodes:
            if hasattr(seq, "nodes") and len(seq.nodes) >= 1:
                parts.append(seq.nodes[0].to_nim())
    return "# global " + ", ".join(parts)


@method(nonlocal_stmt)
def to_nim(self):
    """nonlocal_stmt: 'nonlocal' IDENTIFIER (',' IDENTIFIER)* -> Nim: emitted as '# nonlocal ...' comment"""
    parts = [self.nodes[0].to_nim()]
    for node in self.nodes[1:]:
        if not hasattr(node, "nodes") or not node.nodes:
            continue
        for seq in node.nodes:
            if hasattr(seq, "nodes") and len(seq.nodes) >= 1:
                parts.append(seq.nodes[0].to_nim())
    return "# nonlocal " + ", ".join(parts)


# --- import ---
@method(dotted_name)
def to_nim(self):
    """dotted_name: IDENTIFIER ('.' IDENTIFIER)* -> Nim: joined with '.'"""
    parts = [self.nodes[0].to_nim()]
    for node in self.nodes[1:]:
        if not hasattr(node, "nodes") or not node.nodes:
            continue
        for seq in node.nodes:
            if hasattr(seq, "nodes") and len(seq.nodes) >= 2:
                parts.append(seq.nodes[1].to_nim())
    return ".".join(parts)


@method(import_as)
def to_nim(self):
    """import_as: dotted_name ('.' IDENTIFIER)* ('as' IDENTIFIER)? -> Nim: 'import nim_module' or 'let x = pyImport("mod")'"""
    parts = [self.nodes[0].to_nim()]
    alias = None
    for node in self.nodes[1:]:
        if not hasattr(node, "nodes") or not node.nodes:
            continue
        for seq in node.nodes:
            if not hasattr(seq, "nodes"):
                continue
            if (
                len(seq.nodes) >= 2
                and hasattr(seq.nodes[0], "nodes")
                and seq.nodes[0].nodes
                and seq.nodes[0].nodes[0] == "."
            ):
                parts.append(seq.nodes[1].to_nim())
            elif len(seq.nodes) >= 1:
                alias = seq.nodes[0].to_nim()
    module = ".".join(parts)
    local = alias if alias else parts[-1]
    # Map known Python stdlib modules to Nim imports
    nim_module = _PY_MODULE_TO_NIM.get(module)
    if nim_module is not None:
        return f"import {nim_module}"
    ParserState.nim_imports.add("nimpy")
    return f'let {local} = pyImport("{module}")'  


@method(import_stmt)
def to_nim(self):
    """import_stmt: 'import' import_as (',' import_as)* -> Nim: mapped stdlib imports or pyImport()"""
    parts = [self.nodes[0].to_nim()]
    for node in self.nodes[1:]:
        if not hasattr(node, "nodes") or not node.nodes:
            continue
        for seq in node.nodes:
            if hasattr(seq, "nodes") and len(seq.nodes) >= 1:
                parts.append(seq.nodes[0].to_nim())
    # Deduplicate identical import lines
    seen = set()
    unique = []
    for p in parts:
        if p not in seen:
            seen.add(p)
            unique.append(p)
    # Filter out None/erased imports (e.g., typing)
    unique = [p for p in unique if p is not None]
    return chr(10).join(unique)


# --- from ... import ---
@method(import_name)
def to_nim(self):
    """import_name: IDENTIFIER ('as' IDENTIFIER)? -> Nim: name or 'name as alias'"""
    name = self.nodes[0].to_nim()
    for node in self.nodes[1:]:
        if not hasattr(node, "nodes") or not node.nodes:
            continue
        for seq in node.nodes:
            if hasattr(seq, "nodes") and len(seq.nodes) >= 1:
                alias = seq.nodes[0].to_nim()
                return f"{name} as {alias}"
    return name


@method(import_star)
def to_nim(self):
    """import_star: '*' (from x import *) -> Nim: '*'"""
    return "*"


@method(import_names_paren)
def to_nim(self):
    """import_names_paren: '(' import_names ')' -> Nim: parenthesised import list"""
    def _find_import_names(node):
        names = []
        if node is None:
            return names
        if type(node).__name__ == "import_name":
            names.append(node.to_nim())
        elif hasattr(node, "nodes") and node.nodes:
            for child in node.nodes:
                names.extend(_find_import_names(child))
        return names
    parts = _find_import_names(self)
    return "(" + ", ".join(parts) + ")"


@method(import_names)
def to_nim(self):
    """import_names: import_name (',' import_name)* | import_star -> Nim: Nim import names"""
    first = self.nodes[0].to_nim()
    if first == "*":
        return "*"
    parts = [first]
    for node in self.nodes[1:]:
        if not hasattr(node, "nodes") or not node.nodes:
            continue
        for seq in node.nodes:
            if hasattr(seq, "nodes") and len(seq.nodes) >= 1:
                parts.append(seq.nodes[0].to_nim())
    return ", ".join(parts)


def _dots_to_nim(nodes):
    dots = ""
    for node in nodes:
        if hasattr(node, "nodes"):
            for sub in node.nodes:
                if hasattr(sub, "nodes") and sub.nodes and sub.nodes[0] == ".":
                    dots += "."
    return dots


def _import_names_to_nim(node):
    """Parallel to _import_names_to_py but calls to_nim()."""
    if not hasattr(node, "nodes"):
        return str(node)
    if type(node).__name__ == "import_names_paren":
        return node.to_nim()
    first = node.nodes[0]
    if first == "*" or (
        hasattr(first, "nodes") and first.nodes and first.nodes[0] == "*"
    ):
        return "*"
    first_name_nodes = [first]
    parts = []
    for nd in node.nodes[1:]:
        if type(nd).__name__ == "Several_Times" and nd.nodes:
            for seq in nd.nodes:
                if hasattr(seq, "nodes") and seq.nodes:
                    child = seq.nodes[0]
                    if type(child).__name__ == "import_name":
                        if not parts:
                            parts.append(_import_name_to_nim(first_name_nodes))
                        parts.append(child.to_nim())
                    elif type(child).__name__ == "IDENTIFIER":
                        first_name_nodes.append(nd)
                        break
                    else:
                        first_name_nodes.append(nd)
                        break
        else:
            first_name_nodes.append(nd)
    if not parts:
        parts.append(_import_name_to_nim(first_name_nodes))
    return ", ".join(parts)


def _import_name_to_nim(nodes):
    name = nodes[0].to_nim()
    for nd in nodes[1:]:
        if type(nd).__name__ == "Several_Times" and nd.nodes:
            seq = nd.nodes[0]
            if hasattr(seq, "nodes") and seq.nodes:
                child = seq.nodes[0]
                if type(child).__name__ == "IDENTIFIER":
                    name += f" as {child.to_nim()}"
    return name


@method(from_rel_name)
def to_nim(self):
    """from_rel_name: relative 'from' import with leading dots (e.g. 'from ..pkg import x') -> Nim: pyImport or mapped stdlib"""
    dots = ""
    remaining = []
    for node in self.nodes:
        if type(node).__name__ == "Several_Times":
            for sub in node.nodes:
                if hasattr(sub, "nodes") and sub.nodes and sub.nodes[0] == ".":
                    dots += "."
                else:
                    remaining.append(sub)
        else:
            remaining.append(node)
    source = remaining[0].to_nim() if remaining else ""
    module = dots + source
    names_str = (
        _import_names_to_nim(remaining[-1])
        if len(remaining) > 1
        else remaining[0].to_nim()
        if remaining
        else ""
    )
    if names_str == "*":
        return f"from {module} import *"
    raw = names_str.strip("()")
    items = [n.strip() for n in raw.split(",")]
    lines = []
    for item in items:
        if " as " in item:
            orig, alias = item.split(" as ", 1)
            ParserState.nim_imports.add("nimpy")
            lines.append(f'let {alias.strip()} = pyImport("{module}").{orig.strip()}')
        else:
            ParserState.nim_imports.add("nimpy")
            lines.append(f'let {item} = pyImport("{module}").{item}')
    return chr(10).join(lines)


@method(from_rel_bare)
def to_nim(self):
    """from_rel_bare: bare relative import ('from . import x') -> Nim: pyImport('.').x or stdlib import"""
    dots = ""
    names_node = None
    for node in self.nodes:
        if type(node).__name__ == "Several_Times":
            for sub in node.nodes:
                if hasattr(sub, "nodes") and sub.nodes and sub.nodes[0] == ".":
                    dots += "."
                else:
                    names_node = sub
        elif names_node is None:
            names_node = node
    names_str = _import_names_to_nim(names_node) if names_node else ""
    module = dots
    if names_str == "*":
        return f"from {module} import *"
    raw = names_str.strip("()")
    items = [n.strip() for n in raw.split(",")]
    lines = []
    for item in items:
        if " as " in item:
            orig, alias = item.split(" as ", 1)
            ParserState.nim_imports.add("nimpy")
            lines.append(f'let {alias.strip()} = pyImport("{module}").{orig.strip()}')
        else:
            ParserState.nim_imports.add("nimpy")
            lines.append(f'let {item} = pyImport("{module}").{item}')
    return chr(10).join(lines)


@method(from_abs)
def to_nim(self):
    """from_abs: absolute 'from module import names' -> Nim: mapped stdlib or pyImport("module").name"""
    source_parts = [self.nodes[0].to_nim()]
    names_start = 1
    for i, nd in enumerate(self.nodes[1:], 1):
        if type(nd).__name__ == "Several_Times" and nd.nodes:
            seq = nd.nodes[0]
            if hasattr(seq, "nodes") and len(seq.nodes) >= 2:
                first_child = seq.nodes[0]
                if (
                    hasattr(first_child, "nodes")
                    and first_child.nodes
                    and first_child.nodes[0] == "."
                ):
                    source_parts.append(seq.nodes[1].to_nim())
                    names_start = i + 1
                    continue
        break
    module = ".".join(source_parts)
    if names_start < len(self.nodes):
        names_node = self.nodes[names_start]
        if names_start + 1 < len(self.nodes):
            class _Mock:
                pass
            mock = _Mock()
            mock.nodes = self.nodes[names_start:]
            names_str = _import_names_to_nim(mock)
        else:
            names_str = _import_names_to_nim(names_node)
    else:
        names_str = ""
    # Handle star import
    if names_str == "*":
        return f"from {module} import *"
    # Check if module has a known Nim equivalent
    nim_module = _PY_MODULE_TO_NIM.get(module)
    if nim_module is not None:
        return f"import {nim_module}"
    # Split names and generate one let per name
    # names_str may be "X", "X, Y", "(X, Y)", or "X as A"
    raw = names_str.strip("()")
    items = [n.strip() for n in raw.split(",")]
    lines = []
    for item in items:
        if " as " in item:
            orig, alias = item.split(" as ", 1)
            orig = orig.strip()
            alias = alias.strip()
            ParserState.nim_imports.add("nimpy")
            lines.append(f'let {alias} = pyImport("{module}").{orig}')
        else:
            ParserState.nim_imports.add("nimpy")
            lines.append(f'let {item} = pyImport("{module}").{item}')
    return chr(10).join(lines)


@method(from_stmt)
def to_nim(self):
    """from_stmt: from_rel_name | from_rel_bare | from_abs"""
    return self.nodes[0].to_nim()


# --- type alias ---
@method(enum_def)
def to_nim(self):
    """enum_def: 'enum' enum_member (',' enum_member)*"""
    raw = str(self.nodes[0].node)
    parts = [f"v{raw}" if raw.isdigit() else raw]
    for node in self.nodes[1:]:
        if not hasattr(node, 'nodes') or not node.nodes:
            continue
        for seq in node.nodes:
            if hasattr(seq, 'nodes') and len(seq.nodes) >= 1:
                m = str(seq.nodes[0].node)
                parts.append(f"v{m}" if m.isdigit() else m)
    return "enum " + ", ".join(parts)


@method(subrange_def)
def to_nim(self):
    """subrange_def: INTEGER '..' ['<'] INTEGER -> Nim range[lo..hi] or range[lo..<hi]"""
    lo = str(self.nodes[0].node)
    hi = str(self.nodes[-1].node)
    # Check if exclusive (..<) — look for '<' in Several_Times node from (vop("<"))[:]
    is_exclusive = False
    for n in self.nodes[1:-1]:
        tname = type(n).__name__
        if tname == "Several_Times" and hasattr(n, "nodes") and n.nodes:
            is_exclusive = True
            break
    op = "..<" if is_exclusive else ".."
    return f"range[{lo}{op}{hi}]"



@method(constrained_subrange_def)
def to_nim(self):
    """constrained_subrange_def: IDENTIFIER subrange_def -> Nim range[lo..hi]"""
    return self.nodes[1].to_nim()


@method(nimport_stmt)
def to_nim(self):
    """nimport_stmt: 'nimport' dotted_name (',' dotted_name)* -> Nim import"""
    parts = [self.nodes[0].to_nim()]
    for node in self.nodes[1:]:
        if not hasattr(node, 'nodes') or not node.nodes:
            continue
        for seq in node.nodes:
            if hasattr(seq, 'nodes'):
                for child in seq.nodes:
                    cname = type(child).__name__
                    if cname == "dotted_name":
                        parts.append(child.to_nim())
    return "import " + ", ".join(parts)


@method(type_alias_params)
def to_nim(self):
    """type_alias_params: '[' IDENTIFIER (',' IDENTIFIER)* ']' (generic type parameters) -> Nim: [T, U, ...]"""
    parts = [self.nodes[0].to_nim()]
    for node in self.nodes[1:]:
        if not hasattr(node, "nodes") or not node.nodes:
            continue
        for seq in node.nodes:
            if hasattr(seq, "nodes") and len(seq.nodes) >= 1:
                parts.append(seq.nodes[0].to_nim())
    return f"[{', '.join(parts)}]"


@method(type_stmt)
def to_nim(self):
    """type_stmt: 'type' IDENTIFIER type_alias_params? '=' expression"""
    name = self.nodes[0].to_nim()
    params = ""
    eq_idx = 1
    for i, node in enumerate(self.nodes[1:], 1):
        if type(node).__name__ == "type_alias_params":
            params = node.to_nim()
            eq_idx = i + 1
            break
        elif hasattr(node, "nodes") and node.nodes:
            first = node.nodes[0] if hasattr(node, "nodes") else node
            if type(first).__name__ == "type_alias_params":
                params = first.to_nim()
                eq_idx = i + 1
                break
    # RHS is the last node — works whether V_EQUAL is present ('=') or absent ('is')
    rhs = self.nodes[-1]
    rhs_type = type(rhs).__name__
    if rhs_type == "enum_def":
        ParserState.symbol_table.add(name, "enum", "type")
        # Register First/Last for tick attributes
        # Extract members: first node is first member, rest are in Several_Times groups
        raw0 = str(rhs.nodes[0].node)
        members = [f"v{raw0}" if raw0.isdigit() else raw0]
        for node in rhs.nodes[1:]:
            if hasattr(node, "nodes") and node.nodes:
                for seq in node.nodes:
                    if hasattr(seq, "nodes") and len(seq.nodes) >= 1:
                        m = str(seq.nodes[0].node)
                        members.append(f"v{m}" if m.isdigit() else m)
        if members:
            ParserState.tick_types[name] = {"First": members[0], "Last": members[-1], "members": members}
    elif rhs_type == "subrange_def":
        lo = str(rhs.nodes[0].node)
        hi = str(rhs.nodes[-1].node)
        ParserState.tick_types[name] = {"First": lo, "Last": hi}
    elif rhs_type == "constrained_subrange_def":
        sr = rhs.nodes[1]  # the subrange_def inside
        lo = str(sr.nodes[0].node)
        hi = str(sr.nodes[-1].node)
        ParserState.tick_types[name] = {"First": lo, "Last": hi}
    value = rhs.to_nim()
    # Record type alias so method translation can resolve it
    if rhs_type not in ("enum_def", "subrange_def", "constrained_subrange_def"):
        ParserState.symbol_table.add(name, value, "type")
    return f"type {name}{params} = {value}"


# --- simple_stmt ---
@method(print_stmt)
def to_nim(self):
    """print_stmt: 'print' star_expressions -> Nim: echo star_expressions

    HPython bare print statement. In Nim output, 'print x' becomes 'echo x'.
    Multiple comma-separated arguments are passed directly to echo.
    """
    return f"echo({self.nodes[0].to_nim()})"


# --- simple_stmt ---
@method(simple_stmt)
def to_nim(self):
    """simple_stmt: assign_stmt | aug_assign_stmt | ann_assign_stmt | decl_* | return_stmt | del_stmt | assert_stmt | raise_stmt | pass_stmt | break_stmt | continue_stmt | import_stmt | from_stmt | type_alias_stmt | expr_stmt"""
    return self.nodes[0].to_nim()


# --- stmt_line ---
@method(stmt_line)
def to_nim(self):
    """stmt_line: simple_stmt NL -> Nim: simple statement line"""
    from hek_tokenize import RichNL

    parts = [self.nodes[0].to_nim()]
    newline_node = None

    for node in self.nodes[1:]:
        if hasattr(node, "nodes") and node.nodes:
            inner = node.nodes[0] if len(node.nodes) == 1 else None
            if inner is not None and isinstance(inner, RichNL):
                newline_node = inner
                continue
            for seq in node.nodes:
                if hasattr(seq, "nodes") and len(seq.nodes) >= 1:
                    parts.append(seq.nodes[0].to_nim())
        elif isinstance(node, RichNL):
            newline_node = node

    result = "; ".join(parts)
    # Convert bare string literals (docstrings) to Nim doc comments
    if len(parts) == 1:
        r = parts[0]
        if r and len(r) >= 2 and r[0] == r[-1] and r[0] in ('"', "'"):
            result = '## ' + r[1:-1]
    if newline_node is not None and hasattr(newline_node, "comments") and newline_node.comments:
        for kind, text, ind in newline_node.comments:
            if kind == "comment":
                result += "  " + text
    return result




###############################################################################
# Tests
###############################################################################

if __name__ == "__main__":
    print()
    print("=" * 60)
    print("Python -> Nim Statement Translation Tests")
    print("=" * 60)

    nim_tests = [
        # --- Assignment ---
        ("x = 1", "var x = 1"),
        ("a = b = 1", "var a = b = 1"),
        ("a, b = 1, 2", "var a, b = 1, 2"),
        # --- Augmented assignment (same in Nim) ---
        ("x += 1", "x += 1"),
        ("x -= 1", "x -= 1"),
        ("x *= 2", "x *= 2"),
        ("x /= 2", "x /= 2"),
        # --- Augmented assignment (expanded in Nim) ---
        ("x //= 2", "x = x div 2"),
        ("x %= 3", "x = x mod 3"),
        ("x **= 2", "x = x ^ 2"),
        ("x @= m", "x = x @ m"),
        ("x <<= 1", "x = x shl 1"),
        ("x >>= 1", "x = x shr 1"),
        ("x &= mask", "x = x and mask"),
        ("x |= flag", "x = x or flag"),
        ("x ^= bits", "x = x xor bits"),
        # --- Annotated assignment ---
        ("x: int", "var x: int"),
        ("x: int = 1", "var x: int = 1"),
        ("x: str = 'hello'", "var x: string = 'hello'"),
        # --- Declaration with keyword ---
        ("var x : int", "var x: int"),
        ("let y : int = 8", "let y: int = 8"),
        ("const z : int = 44", "const z: int = 44"),
        # --- return ---
        ("return", "return"),
        ("return x", "return x"),
        ("return x, y", "return x, y"),
        # --- pass -> discard ---
        ("pass", "discard"),
        # --- break / continue (same) ---
        ("break", "break"),
        ("continue", "continue"),
        # --- del -> reset() ---
        ("del x", "reset(x)"),
        # --- assert (same) ---
        ("assert x", "assert x"),
        ("assert x, 'msg'", "assert x, 'msg'"),
        # --- raise ---
        ("raise", "raise"),
        ("raise ValueError", "raise ValueError"),
        ("raise ValueError from exc", "raise ValueError"),  # no 'from' in Nim
        # --- global / nonlocal -> comments ---
        ("global x", "# global x"),
        ("global x, y", "# global x, y"),
        ("nonlocal x", "# nonlocal x"),
        ("nonlocal a, b, c", "# nonlocal a, b, c"),
        # --- import (dotted names use / in Nim) ---
        ("import os", "import os"),
        ("import os.path", "import os"),
        ("import os as o", "import os"),
        ("import os, sys", "import os"),
        # --- from import ---
        ("from os import path", 'import os'),
        ("from os import path as p", 'import os'),
        ("from os import path, getcwd", 'import os'),
        ("from os import *", "from os import *"),
        # --- type alias ---
        ("type Vector = list", "type Vector = list"),
        ("type Color = enum RED, BLUE, YELLOW", "type Color = enum RED, BLUE, YELLOW"),
        # --- expression statement (delegates to expr to_nim) ---
        ("f(x)", "f(x)"),
        ("1 + 2", "1 + 2"),
    ]

    nim_passed = nim_failed = 0
    for code, expected in nim_tests:
        try:
            result = parse_stmt(code)
            if result:
                output = result.to_nim()
                if output == expected:
                    print(f"  PASS: {code!r} -> {output!r}")
                    nim_passed += 1
                else:
                    print(f"  MISMATCH: {code!r}")
                    print(f"    expected: {expected!r}")
                    print(f"    got:      {output!r}")
                    nim_failed += 1
            else:
                print(f"  FAIL: {code!r} -> parse returned None")
                nim_failed += 1
        except Exception as e:
            print(f"  ERROR: {code!r} -> {e}")
            import traceback
            traceback.print_exc()
            nim_failed += 1

    print("=" * 60)
    print(f"Results: {nim_passed} passed, {nim_failed} failed")
    print()
