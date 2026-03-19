#!/usr/bin/env python3
"""ADASCRIPT-style type annotation parser using hek_parsec combinator framework.

Defines the ``type_annotation`` parser used throughout the Python 3 grammar
(annotated assignments, function parameter/return annotations, type aliases).

ADASCRIPT uses a left-to-right type notation inspired by Go and Odin, where
container prefixes read naturally ("sequence of int" = ``[]int``).  The parser
translates this notation into standard Python annotation strings via to_py().

Syntax reference
================

Primitives
----------
    int  str  float  bool  bytes  None

User-defined types
------------------
    Any identifier that is not a primitive keyword:
        MyClass   SomeType   TreeNode

Sequences (dynamic)
--------------------
    []<type>                        list[<type>]

    []int                           list[int]
    [][]int                         list[list[int]]
    []MyClass                       list[MyClass]

Fixed-size arrays
-----------------
    [<N>]<type>                     tuple[<type>, ...]

    [5]int                          tuple[int, ...]
    [3][]int                        tuple[list[int], ...]

Dictionaries
------------
    {<key_type>}<value_type>        dict[<key_type>, <value_type>]

    {str}int                        dict[str, int]
    {int}[]str                      dict[int, list[str]]

Sets
----
    {}<type>                        set[<type>]

    {}int                           set[int]
    {}str                           set[str]

Optional (nullable)
-------------------
    ?<type>                         <type> | None

    ?int                            int | None
    ?[]int                          list[int] | None
    []?int                          list[int | None]

Tuples
------
    (<type>, <type>, ...)           tuple[<type>, <type>, ...]
    (<type>,)                       tuple[<type>]

    (int, str)                      tuple[int, str]
    (int, str, float)               tuple[int, str, float]

Union types
-----------
    <type> | <type> | ...           <type> | <type> | ...

    int | str                       int | str
    ?int | str                      int | None | str

Callable (function signature)
-----------------------------
    [(<param_types>)]<return_type>  Callable[[<param_types>], <return_type>]

    [(int, str)]bool                Callable[[int, str], bool]
    [(int,)]int                     Callable[[int], int]

Grammar
=======
::

    type_annotation      = union_type | maybe_optional | expression
    union_type           = maybe_optional ('|' maybe_optional)+
    maybe_optional       = optional_type | basic_type
    optional_type        = '?' basic_type
    basic_type           = seq_type | callable_type | array_type
                         | dict_type | set_type | tuple_type
                         | primitive_type | type_name
    seq_type             = '[]' type_annotation
    array_type           = '[' INTEGER ']' type_annotation
    dict_type            = '{' type_annotation '}' type_annotation
    set_type             = '{}' type_annotation
    callable_type        = '[' tuple_type ']' type_annotation
    tuple_type           = empty_tuple_type | singleton_tuple_type | multi_tuple_type
    multi_tuple_type     = '(' type_annotation (',' type_annotation)+ [','] ')'
    singleton_tuple_type = '(' type_annotation ',' ')'
    empty_tuple_type     = '(' ',' ')'
    primitive_type       = 'int' | 'str' | 'float' | 'bool' | 'bytes' | 'None'
    type_name            = IDENTIFIER  (excluding primitives)

The ``expression`` fallback allows standard Python annotation syntax
(e.g. ``list[int]``) to pass through when used inside the full grammar.

Nim Translation
===============

Nim code generation is in ``hek_nim_declarations.py`` (``to_nim()`` methods)::

    Primitives:  str -> string, bytes -> seq[byte], None -> void
    Sequences:   []int -> seq[int]
    Arrays:      [5]int -> array[5, int]
    Dicts:       {str}int -> Table[string, int]
    Sets:        {}int -> HashSet[int]
    Optionals:   ?int -> Option[int]
    Tuples:      (int, str) -> (int, string)
    Callables:   [(int, str)]bool -> proc(a0: int, a1: string): bool

Usage
=====
::

    from hek_py_declarations import type_annotation, parse_type
    from hek_parsec import Input

    # Standalone parsing
    ast = parse_type("[]?int")
    print(ast.to_py())          # list[int | None]
    # from hek_nim_declarations import *  # to enable to_nim()
    # print(ast.to_nim())         # seq[Option[int]]

    # As part of a larger grammar
    ann_assign = IDENTIFIER + COLON + type_annotation
"""

import sys, os
_dir = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(_dir, ".."))
sys.path.insert(0, os.path.join(_dir, "..", "HPYTHON_GRAMMAR"))

from py_declarations import *
import hek_py3_expr  # noqa: F401 — registers expr to_py() methods
from hek_parsec import method

# to_py() methods
###############################################################################


@method(primitive_type)
def to_py(self, prec=None):
    """primitive_type: 'int' | 'str' | 'float' | 'bool' | 'bytes' | 'None' -> Nim: str->string, bytes->seq[byte], None->void"""
    name = self.nodes[0]
    if name == "char":
        return "str"
    return name


@method(type_name)
def to_py(self, prec=None):
    """type_name: IDENTIFIER (type alias or user-defined type) -> Nim: mapped via _PY_TO_NIM if known"""
    return self.nodes[0].to_py()  # delegate to primary expression node


@method(seq_type)
def to_py(self, prec=None):
    """seq_type: '[]' type_annotation -> Nim: seq[T]"""
    return f"list[{self.nodes[0].to_py()}]"


@method(array_type)
def to_py(self, prec=None):
    """array_type: '[' INTEGER ']' type_annotation -> Nim: array[N, T]"""
    return f"tuple[{self.nodes[1].to_py()}, ...]"


@method(openarray_type)
def to_py(self, prec=None):
    """openarray_type: '[*]' type_annotation -> Nim: openArray[T]"""
    return f"Sequence[{self.nodes[1].to_py()}]"


@method(enum_array_type)
def to_py(self, prec=None):
    """enum_array_type: '[' IDENTIFIER ']' type_annotation (enum-indexed array) -> Nim: array[EnumType, T]"""
    idx = self.nodes[0].to_py()
    elem = self.nodes[1].to_py()
    return f"dict[{idx}, {elem}]"


@method(dict_type)
def to_py(self, prec=None):
    """dict_type: '{' type_annotation '}' type_annotation -> Nim: Table[K, V] (imports tables)"""
    key = self.nodes[0].to_py()
    val = self.nodes[1].to_py()
    return f"dict[{key}, {val}]"


@method(set_type)
def to_py(self, prec=None):
    """set_type: '{}' type_annotation -> Nim: set[T] for ordinals; HashSet[T] otherwise"""
    return f"set[{self.nodes[0].to_py()}]"


@method(callable_type)
def to_py(self, prec=None):
    """callable_type: '[' tuple_type ']' type_annotation -> Nim: proc(a0: T, ...): R"""
    # nodes[0] is the tuple_type (params), nodes[1] is the return type
    tup = self.nodes[0]
    ret = self.nodes[1].to_py()
    # Extract individual param types from the tuple
    params = _tuple_elements(tup)
    param_str = ", ".join(params)
    return f"Callable[[{param_str}], {ret}]"


@method(empty_tuple_type)
def to_py(self, prec=None):
    """empty_tuple_type: '(' ',' ')' (empty params) -> Nim: '()'"""
    return "tuple[()]"


@method(singleton_tuple_type)
def to_py(self, prec=None):
    """singleton_tuple_type: '(' type_annotation ',' ')' -> Nim: '(T,)'"""
    return f"tuple[{self.nodes[0].to_py()}]"


@method(multi_tuple_type)
def to_py(self, prec=None):
    """multi_tuple_type: '(' type_annotation (',' type_annotation)+ [','] ')' -> Nim: '(T, U, ...)'"""
    elems = _tuple_elements(self)
    return f"tuple[{', '.join(elems)}]"


def _tuple_elements(tup):
    """Extract type strings from a tuple_type AST node."""
    if type(tup).__name__ == "empty_tuple_type":
        return []
    if type(tup).__name__ == "singleton_tuple_type":
        return [tup.nodes[0].to_py()]
    # multi_tuple_type: first + Several_Times of (COMMA + type_annotation)
    elems = [tup.nodes[0].to_py()]
    st = tup.nodes[1]  # the Several_Times node
    for seq in st.nodes:
        if hasattr(seq, "nodes") and seq.nodes:
            elems.append(seq.nodes[0].to_py())
    return elems


@method(optional_type)
def to_py(self, prec=None):
    """optional_type: '?' type_annotation -> Nim: Option[T] (imports options); ref types stay as-is"""
    return f"{self.nodes[0].to_py()} | None"


@method(union_type)
def to_py(self, prec=None):
    """union_type: maybe_optional ('|' maybe_optional)+ -> Nim: best-effort 'T | U' (Nim uses object variants instead)"""
    # nodes[0] is first maybe_optional, nodes[1] is Several_Times of (VBAR + maybe_optional)
    parts = [self.nodes[0].to_py()]
    st = self.nodes[1]
    for seq in st.nodes:
        if hasattr(seq, "nodes") and seq.nodes:
            parts.append(seq.nodes[0].to_py())
    return " | ".join(parts)



###############################################################################
# Parse helper
###############################################################################


###############################################################################
# Tests
###############################################################################

if __name__ == "__main__":
    print("=" * 60)
    print("ADASCRIPT-style Type Annotation Parser Tests")
    print("=" * 60)

    tests = [
        # --- Primitives ---
        ("int", "int"),
        ("str", "str"),
        ("float", "float"),
        ("bool", "bool"),
        ("bytes", "bytes"),
        ("None", "None"),
        # --- User-defined types ---
        ("MyClass", "MyClass"),
        ("SomeType", "SomeType"),
        # --- Sequence ---
        ("[]int", "list[int]"),
        ("[]str", "list[str]"),
        ("[][]int", "list[list[int]]"),
        # --- Fixed array ---
        ("[5]int", "tuple[int, ...]"),
        ("[*]int", "Sequence[int]"),
        ("[3]str", "tuple[str, ...]"),
        # --- Nested containers ---
        ("[3][]int", "tuple[list[int], ...]"),
        ("[][5]int", "list[tuple[int, ...]]"),
        # --- Dict ---
        ("{str}int", "dict[str, int]"),
        ("{int}str", "dict[int, str]"),
        # --- Set ---
        ("{}int", "set[int]"),
        ("{}str", "set[str]"),
        # --- Optional ---
        ("?int", "int | None"),
        ("?str", "str | None"),
        ("?[]int", "list[int] | None"),
        ("[]?int", "list[int | None]"),
        # --- Tuple ---
        ("(int, str)", "tuple[int, str]"),
        ("(int, str, float)", "tuple[int, str, float]"),
        ("(int,)", "tuple[int]"),
        # --- Union ---
        ("int | str", "int | str"),
        ("int | str | float", "int | str | float"),
        ("?int | str", "int | None | str"),
        # --- Callable ---
        ("[(int, str)]bool", "Callable[[int, str], bool]"),
        ("[(int,)]int", "Callable[[int], int]"),
    ]

    passed = failed = 0
    for code, expected in tests:
        try:
            ast = parse_type(code)
            if ast is None:
                print(f"  FAIL: {code!r} -> parse returned None")
                failed += 1
            else:
                output = ast.to_py()
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
