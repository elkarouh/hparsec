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
sys.path.insert(0, os.path.join(_dir, "..", "GRAMMAR"))
sys.path.insert(0, os.path.join(_dir, "..", "TO_PYTHON"))

from hek_parsec import method, ParserState
from hek_py3_stmt import *  # noqa: F403 — need all parser rule names
from hek_py3_stmt import parse_stmt
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


# --- visible tokens ---
@method(augop)
def to_nim(self):
    return self.nodes[0].to_py()  # raw op string, translated at aug_assign level


@method(V_EQUAL)
def to_nim(self):
    return "="


@method(V_COLON)
def to_nim(self):
    return ":"


@method(V_DOT)
def to_nim(self):
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
    # Record type in symbol table
    name = self.nodes[0].to_py() if hasattr(self.nodes[0], "to_py") else None
    if name and rhs_node and ParserState.symbol_table.depth() > 0:
        inferred = _infer_literal_nim_type(rhs_node)
        ParserState.symbol_table.add(name, inferred, "var")
    return "var " + " = ".join(parts)


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
        else op_node.nodes[0].to_py()
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
    result = f"var {name}: {annotation}"
    for node in self.nodes[3:]:
        if not hasattr(node, "nodes") or not node.nodes:
            continue
        for seq in node.nodes:
            if hasattr(seq, "nodes") and len(seq.nodes) >= 2:
                value = seq.nodes[1].to_nim()
                result += f" = {value}"
    return result


# --- return ---
@method(return_val)
def to_nim(self):
    return f"return {self.nodes[0].to_nim()}"


@method(return_bare)
def to_nim(self):
    return "return"


@method(return_stmt)
def to_nim(self):
    return self.nodes[0].to_nim()


# --- pass / break / continue ---
@method(pass_stmt)
def to_nim(self):
    return "discard"


@method(break_stmt)
def to_nim(self):
    return "break"


@method(continue_stmt)
def to_nim(self):
    return "continue"


# --- del ---
@method(del_stmt)
def to_nim(self):
    """del x -> reset(x)"""
    return f"reset({self.nodes[0].to_nim()})"


# --- assert ---
@method(assert_msg)
def to_nim(self):
    return f"assert {self.nodes[0].to_nim()}, {self.nodes[1].to_nim()}"


@method(assert_simple)
def to_nim(self):
    return f"assert {self.nodes[0].to_nim()}"


@method(assert_stmt)
def to_nim(self):
    return self.nodes[0].to_nim()


# --- raise ---
@method(raise_from)
def to_nim(self):
    """raise X from Y -> raise X (Nim has no 'from' clause)"""
    return f"raise {self.nodes[0].to_nim()}"


@method(raise_exc)
def to_nim(self):
    return f"raise {self.nodes[0].to_nim()}"


@method(raise_bare)
def to_nim(self):
    return "raise"


@method(raise_stmt)
def to_nim(self):
    return self.nodes[0].to_nim()


# --- global / nonlocal (no Nim equivalent — emit as comment) ---
@method(global_stmt)
def to_nim(self):
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
    parts = [self.nodes[0].to_nim()]
    for node in self.nodes[1:]:
        if not hasattr(node, "nodes") or not node.nodes:
            continue
        for seq in node.nodes:
            if hasattr(seq, "nodes") and len(seq.nodes) >= 2:
                parts.append(seq.nodes[1].to_nim())
    return "/".join(parts)


@method(import_as)
def to_nim(self):
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
    name = "/".join(parts)
    if alias:
        return f"{name} as {alias}"
    return name


@method(import_stmt)
def to_nim(self):
    parts = [self.nodes[0].to_nim()]
    for node in self.nodes[1:]:
        if not hasattr(node, "nodes") or not node.nodes:
            continue
        for seq in node.nodes:
            if hasattr(seq, "nodes") and len(seq.nodes) >= 1:
                parts.append(seq.nodes[0].to_nim())
    return "import " + ", ".join(parts)


# --- from ... import ---
@method(import_name)
def to_nim(self):
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
    return "*"


@method(import_names_paren)
def to_nim(self):
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
    names = (
        _import_names_to_nim(remaining[-1])
        if len(remaining) > 1
        else remaining[0].to_nim()
        if remaining
        else ""
    )
    return f"from {dots}{source} import {names}"


@method(from_rel_bare)
def to_nim(self):
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
    names = _import_names_to_nim(names_node) if names_node else ""
    return f"from {dots} import {names}"


@method(from_abs)
def to_nim(self):
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
    source = "/".join(source_parts)
    if names_start < len(self.nodes):
        names_node = self.nodes[names_start]
        if names_start + 1 < len(self.nodes):
            class _Mock:
                pass
            mock = _Mock()
            mock.nodes = self.nodes[names_start:]
            names = _import_names_to_nim(mock)
        else:
            names = _import_names_to_nim(names_node)
    else:
        names = ""
    return f"from {source} import {names}"


@method(from_stmt)
def to_nim(self):
    return self.nodes[0].to_nim()


# --- type alias ---
@method(enum_def)
def to_nim(self):
    """enum_def: 'enum' IDENTIFIER (',') IDENTIFIER)*"""
    parts = [self.nodes[0].to_nim()]
    for node in self.nodes[1:]:
        if not hasattr(node, 'nodes') or not node.nodes:
            continue
        for seq in node.nodes:
            if hasattr(seq, 'nodes') and len(seq.nodes) >= 1:
                parts.append(seq.nodes[0].to_nim())
    return "enum " + ", ".join(parts)


@method(type_alias_params)
def to_nim(self):
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
    value = self.nodes[eq_idx + 1].to_nim()
    return f"type {name}{params} = {value}"


# --- simple_stmt ---
@method(simple_stmt)
def to_nim(self):
    return self.nodes[0].to_nim()


# --- stmt_line ---
@method(stmt_line)
def to_nim(self):
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
        ("import os.path", "import os/path"),
        ("import os as o", "import os as o"),
        ("import os, sys", "import os, sys"),
        # --- from import ---
        ("from os import path", "from os import path"),
        ("from os import path as p", "from os import path as p"),
        ("from os import path, getcwd", "from os import path, getcwd"),
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
