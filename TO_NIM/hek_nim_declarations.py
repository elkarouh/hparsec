#!/usr/bin/env python3
"""Nim translation methods for ADASCRIPT type declarations.

Adds to_nim() methods to the type declaration parser classes defined in
hek_py_declarations.py. Import this module to enable .to_nim() on type AST nodes.

Usage:
    from hek_nim_declarations import *
    ast = parse_type("[]?int")
    print(ast.to_nim())  # seq[Option[int]]
"""

import sys, os
_dir = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(_dir, ".."))
sys.path.insert(0, os.path.join(_dir, "..", "HPYTHON_GRAMMAR"))
# (no TO_PYTHON dependency needed)

from hek_parsec import method, ParserState
from py_declarations import *  # noqa: F403 — need all parser rule names
from py_declarations import parse_type

###############################################################################
# to_nim() methods
###############################################################################

_PY_TO_NIM = {
    "int": "int",
    "str": "string",
    "float": "float",
    "bool": "bool",
    "bytes": "seq[byte]",
    "None": "void",
    "list": "seq",
}

# Nim ordinal types — eligible for built-in set[T]
_NIM_ORDINALS = {
    "int8", "int16",
    "uint8", "uint16",
    "char", "bool", "byte", "enum",
}


def _is_nim_ordinal(nim_type):
    """Return True if nim_type is an ordinal type (eligible for set[T])."""
    if nim_type in _NIM_ORDINALS:
        return True
    # Check symbol table for user-defined enum types
    info = ParserState.symbol_table.lookup(nim_type)
    return info is not None and info.get("type") == "enum"


@method(primitive_type)
def to_nim(self, prec=None):
    """primitive_type: 'int' | 'str' | 'float' | 'bool' | 'bytes' | 'None' -> Nim: str->string, bytes->seq[byte], None->void"""
    name = self.nodes[0]
    return _PY_TO_NIM.get(name, name)


@method(type_name)
def to_nim(self, prec=None):
    """type_name: IDENTIFIER (type alias or user-defined type) -> Nim: mapped via _PY_TO_NIM if known"""
    # Check if the underlying identifier has a known Nim mapping
    node = self.nodes[0]
    if hasattr(node, 'nodes') and node.nodes and isinstance(node.nodes[0], str):
        mapped = _PY_TO_NIM.get(node.nodes[0])
        if mapped:
            return mapped
    result = node.to_nim()
    # Append any trailing nodes (e.g. generic params [T] from subscript trailers)
    for extra in self.nodes[1:]:
        # Several_Times nodes don't have a useful to_nim(); iterate their children
        if hasattr(extra, 'nodes'):
            for child in extra.nodes:
                if hasattr(child, 'to_nim'):
                    result += child.to_nim()
        elif hasattr(extra, 'to_nim'):
            result += extra.to_nim()
    return result


@method(seq_type)
def to_nim(self, prec=None):
    """seq_type: '[]' type_annotation -> Nim: seq[T]"""
    return f"seq[{self.nodes[0].to_nim()}]"


@method(array_type)
def to_nim(self, prec=None):
    """array_type: '[' INTEGER ']' type_annotation -> Nim: array[N, T]"""
    size = self.nodes[0].nodes[0]  # the integer string
    elem = self.nodes[1].to_nim()
    return f"array[{size}, {elem}]"


@method(openarray_type)
def to_nim(self, prec=None):
    """openarray_type: '[*]' type_annotation -> Nim: openArray[T]"""
    elem = self.nodes[1].to_nim()
    return f"openArray[{elem}]"


@method(enum_array_type)
def to_nim(self, prec=None):
    """enum_array_type: '[' IDENTIFIER ']' type_annotation (enum-indexed array) -> Nim: array[EnumType, T]"""
    idx = self.nodes[0].to_nim()
    elem = self.nodes[1].to_nim()
    return f"array[{idx}, {elem}]"


@method(dict_type)
def to_nim(self, prec=None):
    """dict_type: '{' type_annotation '}' type_annotation -> Nim: Table[K, V] (imports tables)"""
    ParserState.nim_imports.add("tables")
    key = self.nodes[0].to_nim()
    val = self.nodes[1].to_nim()
    return f"Table[{key}, {val}]"


@method(set_type)
def to_nim(self, prec=None):
    """set_type: '{}' type_annotation -> Nim: set[T] for ordinals; HashSet[T] otherwise"""
    elem = self.nodes[0].to_nim()
    if _is_nim_ordinal(elem):
        return f"set[{elem}]"
    ParserState.nim_imports.add("sets")
    return f"HashSet[{elem}]"


@method(callable_type)
def to_nim(self, prec=None):
    """callable_type: '[' tuple_type ']' type_annotation -> Nim: proc(a0: T, ...): R"""
    tup = self.nodes[0]
    ret = self.nodes[1].to_nim()
    params = _tuple_elements_nim(tup)
    if params:
        param_str = ", ".join(f"a{i}: {p}" for i, p in enumerate(params))
    else:
        param_str = ""
    if ret == "void":
        return f"proc({param_str})"
    return f"proc({param_str}): {ret}"


@method(empty_tuple_type)
def to_nim(self, prec=None):
    """empty_tuple_type: '(' ',' ')' (empty params) -> Nim: '()'"""
    return "()"


@method(singleton_tuple_type)
def to_nim(self, prec=None):
    """singleton_tuple_type: '(' type_annotation ',' ')' -> Nim: '(T,)'"""
    return f"({self.nodes[0].to_nim()},)"


@method(multi_tuple_type)
def to_nim(self, prec=None):
    """multi_tuple_type: '(' type_annotation (',' type_annotation)+ [','] ')' -> Nim: '(T, U, ...)'"""
    elems = _tuple_elements_nim(self)
    return f"({', '.join(elems)})"


def _tuple_elements_nim(tup):
    """Extract Nim type strings from a tuple_type AST node."""
    if type(tup).__name__ == "empty_tuple_type":
        return []
    if type(tup).__name__ == "singleton_tuple_type":
        return [tup.nodes[0].to_nim()]
    # multi_tuple_type: first + Several_Times of (COMMA + type_annotation)
    elems = [tup.nodes[0].to_nim()]
    st = tup.nodes[1]  # the Several_Times node
    for seq in st.nodes:
        if hasattr(seq, "nodes") and seq.nodes:
            elems.append(seq.nodes[0].to_nim())
    return elems


@method(optional_type)
def to_nim(self, prec=None):
    """optional_type: '?' type_annotation -> Nim: Option[T] (imports options); ref types stay as-is"""
    inner = self.nodes[0].to_nim()
    # For ref object types (classes), the type is already nullable — no Option needed
    sym = ParserState.symbol_table.lookup(inner)
    if sym and sym.get("kind") == "class":
        return inner
    ParserState.nim_imports.add("options")
    return f"Option[{inner}]"


@method(union_type)
def to_nim(self, prec=None):
    """union_type: maybe_optional ('|' maybe_optional)+ -> Nim: best-effort 'T | U' (Nim uses object variants instead)"""
    # Nim doesn't have union types directly; emit as a comment-annotated first type
    parts = [self.nodes[0].to_nim()]
    st = self.nodes[1]
    for seq in st.nodes:
        if hasattr(seq, "nodes") and seq.nodes:
            parts.append(seq.nodes[0].to_nim())
    return " | ".join(parts)  # best-effort; Nim uses object variants instead




###############################################################################
# Tests
###############################################################################

if __name__ == "__main__":
    import hek_nim_expr  # noqa: F401 — registers expr to_nim() for expression fallback
    print()
    print("=" * 60)
    print("ADASCRIPT -> Nim Type Translation Tests")
    print("=" * 60)

    nim_tests = [
        # --- Primitives ---
        ("int", "int"),
        ("str", "string"),
        ("float", "float"),
        ("bool", "bool"),
        ("bytes", "seq[byte]"),
        ("None", "void"),
        # --- User-defined types ---
        ("MyClass", "MyClass"),
        ("SomeType", "SomeType"),
        # --- Sequence ---
        ("[]int", "seq[int]"),
        ("[]str", "seq[string]"),
        ("[][]int", "seq[seq[int]]"),
        # --- Fixed array ---
        ("[5]int", "array[5, int]"),
        ("[*]int", "openArray[int]"),
        ("[3]str", "array[3, string]"),
        # --- Nested containers ---
        ("[3][]int", "array[3, seq[int]]"),
        ("[][5]int", "seq[array[5, int]]"),
        # --- Dict ---
        ("{str}int", "Table[string, int]"),
        ("{int}str", "Table[int, string]"),
        # --- Set ---
        ("{}int", "set[int]"),
        ("{}str", "HashSet[string]"),
        # --- Optional ---
        ("?int", "Option[int]"),
        ("?str", "Option[string]"),
        ("?[]int", "Option[seq[int]]"),
        ("[]?int", "seq[Option[int]]"),
        # --- Tuple ---
        ("(int, str)", "(int, string)"),
        ("(int, str, float)", "(int, string, float)"),
        ("(int,)", "(int,)"),
        # --- Union ---
        ("int | str", "int | string"),
        ("int | str | float", "int | string | float"),
        ("?int | str", "Option[int] | string"),
        # --- Callable ---
        ("[(int, str)]bool", "proc(a0: int, a1: string): bool"),
        ("[(int,)]int", "proc(a0: int): int"),
    ]

    passed = failed = 0
    for code, expected in nim_tests:
        try:
            ast = parse_type(code)
            if ast is None:
                print(f"  FAIL: {code!r} -> parse returned None")
                failed += 1
            else:
                output = ast.to_nim()
                if output == expected:
                    print(f"  PASS: {code!r} -> {output!r}")
                    passed += 1
                else:
                    print(f"  MISMATCH: {code!r}")
                    print(f"    expected: {expected!r}")
                    print(f"    got:      {output!r}")
                    failed += 1
        except Exception as e:
            print(f"  ERROR: {code!r} -> {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print("=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print()
