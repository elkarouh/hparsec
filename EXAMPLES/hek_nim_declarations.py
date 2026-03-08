#!/usr/bin/env python3
"""Nim translation methods for ADASCRIPT type declarations.

Adds to_nim() methods to the type declaration parser classes defined in
hek_py_declarations.py. Import this module to enable .to_nim() on type AST nodes.

Usage:
    from hek_nim_declarations import *
    ast = parse_type("[]?int")
    print(ast.to_nim())  # seq[Option[int]]
"""

import sys
sys.path.insert(0, "..")

from hek_parsec import method
from hek_py_declarations import *  # noqa: F403 — need all parser rule names
from hek_py_declarations import parse_type

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
}


@method(primitive_type)
def to_nim(self, prec=None):
    name = self.nodes[0]
    return _PY_TO_NIM.get(name, name)


@method(type_name)
def to_nim(self, prec=None):
    # User-defined types pass through unchanged
    return self.to_py()


@method(seq_type)
def to_nim(self, prec=None):
    return f"seq[{self.nodes[0].to_nim()}]"


@method(array_type)
def to_nim(self, prec=None):
    size = self.nodes[0].nodes[0]  # the integer string
    elem = self.nodes[1].to_nim()
    return f"array[{size}, {elem}]"


@method(dict_type)
def to_nim(self, prec=None):
    key = self.nodes[0].to_nim()
    val = self.nodes[1].to_nim()
    return f"Table[{key}, {val}]"


@method(set_type)
def to_nim(self, prec=None):
    return f"HashSet[{self.nodes[0].to_nim()}]"


@method(callable_type)
def to_nim(self, prec=None):
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
    return "()"


@method(singleton_tuple_type)
def to_nim(self, prec=None):
    return f"({self.nodes[0].to_nim()},)"


@method(multi_tuple_type)
def to_nim(self, prec=None):
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
    return f"Option[{self.nodes[0].to_nim()}]"


@method(union_type)
def to_nim(self, prec=None):
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
    print("=" * 60)
    print("ADASCRIPT -> Nim Type Translation Tests")
    print("=" * 60)


# --- Nim translation tests ---
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
    ("[3]str", "array[3, string]"),
    # --- Nested containers ---
    ("[3][]int", "array[3, seq[int]]"),
    ("[][5]int", "seq[array[5, int]]"),
    # --- Dict ---
    ("{str}int", "Table[string, int]"),
    ("{int}str", "Table[int, string]"),
    # --- Set ---
    ("{}int", "HashSet[int]"),
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
