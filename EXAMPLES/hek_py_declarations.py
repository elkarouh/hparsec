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

Usage
=====
::

    from hek_py_declarations import type_annotation, parse_type
    from hek_parsec import Input

    # Standalone parsing
    ast = parse_type("[]?int")
    print(ast.to_py())          # list[int | None]

    # As part of a larger grammar
    ann_assign = IDENTIFIER + COLON + type_annotation
"""

import tokenize as tkn

from hek_parsec import (
    COMMA,
    IDENTIFIER,
    INTEGER,
    LBRACE,
    LBRACKET,
    LPAREN,
    RBRACE,
    RBRACKET,
    RPAREN,
    VBAR,
    Input,
    expect,
    filt,
    fw,
    ignore,
    literal,
    method,
)
from hek_py3_expr import expression

###############################################################################
# Tokens
###############################################################################

QUESTION = ignore(expect(tkn.OP, "?"))

###############################################################################
# Forward declarations
###############################################################################

type_annotation = fw("type_annotation")
union_type = fw("union_type")
maybe_optional = fw("maybe_optional")
optional_type = fw("optional_type")
basic_type = fw("basic_type")
seq_type = fw("seq_type")
array_type = fw("array_type")
dict_type = fw("dict_type")
set_type = fw("set_type")
callable_type = fw("callable_type")
tuple_type = fw("tuple_type")
multi_tuple_type = fw("multi_tuple_type")
singleton_tuple_type = fw("singleton_tuple_type")
empty_tuple_type = fw("empty_tuple_type")
primitive_type = fw("primitive_type")
type_name = fw("type_name")

###############################################################################
# Grammar rules
###############################################################################

# --- Primitives: int, str, float, bool, bytes, None ---
_PRIMITIVES = {"int", "str", "float", "bool", "bytes", "None"}
primitive_type = filt(lambda s: s in _PRIMITIVES, IDENTIFIER)

# --- User-defined type name (any identifier that is NOT a primitive) ---
type_name = filt(lambda s: s not in _PRIMITIVES, IDENTIFIER)

# --- Tuple types ---
# (int, str, float)  -> tuple[int, str, float]
# (int,)             -> tuple[int]
# (,)                -> tuple[()]
multi_tuple_type = (
    LPAREN + type_annotation + (COMMA + type_annotation)[1:] + COMMA[:] + RPAREN
)
singleton_tuple_type = LPAREN + type_annotation + COMMA + RPAREN
empty_tuple_type = LPAREN + COMMA + RPAREN

tuple_type = empty_tuple_type | singleton_tuple_type | multi_tuple_type

# --- Container types ---
# []int             -> list[int]
seq_type = LBRACKET + RBRACKET + type_annotation

# [5]int            -> tuple[int, ...]
array_type = LBRACKET + INTEGER + RBRACKET + type_annotation

# {str}int          -> dict[str, int]
dict_type = LBRACE + type_annotation + RBRACE + type_annotation

# {}int             -> set[int]
set_type = LBRACE + RBRACE + type_annotation

# [(int, str)]bool  -> Callable[[int, str], bool]
callable_type = LBRACKET + tuple_type + RBRACKET + type_annotation

# --- basic_type: a non-union, non-optional type ---
# Order matters: try container/callable before primitive/name (both start differently)
# callable_type before array_type (both start with '[', but callable has '(' after '[')
basic_type = (
    seq_type
    | callable_type
    | array_type
    | dict_type
    | set_type
    | tuple_type
    | primitive_type
    | type_name
)

# --- Optional: ?int -> int | None ---
optional_type = QUESTION + basic_type
maybe_optional = optional_type | basic_type

# --- Union: int | str -> int | str ---
union_type = maybe_optional + (VBAR + maybe_optional)[1:]

# --- type_annotation: union or single type, with expression fallback ---
type_annotation = union_type | maybe_optional | expression

###############################################################################
# to_py() methods
###############################################################################


@method(primitive_type)
def to_py(self, prec=None):
    return self.nodes[0]  # raw string from literal()


@method(type_name)
def to_py(self, prec=None):
    return self.nodes[0]  # raw string from IDENTIFIER


@method(seq_type)
def to_py(self, prec=None):
    return f"list[{self.nodes[0].to_py()}]"


@method(array_type)
def to_py(self, prec=None):
    return f"tuple[{self.nodes[1].to_py()}, ...]"


@method(dict_type)
def to_py(self, prec=None):
    key = self.nodes[0].to_py()
    val = self.nodes[1].to_py()
    return f"dict[{key}, {val}]"


@method(set_type)
def to_py(self, prec=None):
    return f"set[{self.nodes[0].to_py()}]"


@method(callable_type)
def to_py(self, prec=None):
    # nodes[0] is the tuple_type (params), nodes[1] is the return type
    tup = self.nodes[0]
    ret = self.nodes[1].to_py()
    # Extract individual param types from the tuple
    params = _tuple_elements(tup)
    param_str = ", ".join(params)
    return f"Callable[[{param_str}], {ret}]"


@method(empty_tuple_type)
def to_py(self, prec=None):
    return "tuple[()]"


@method(singleton_tuple_type)
def to_py(self, prec=None):
    return f"tuple[{self.nodes[0].to_py()}]"


@method(multi_tuple_type)
def to_py(self, prec=None):
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
    return f"{self.nodes[0].to_py()} | None"


@method(union_type)
def to_py(self, prec=None):
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


def parse_type(source_code):
    """Parse a type annotation string."""
    inp = Input(source_code)
    result = type_annotation.parse(inp)
    if result is None:
        return None
    return result[0]


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
