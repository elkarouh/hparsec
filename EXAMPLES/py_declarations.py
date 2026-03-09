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

import sys
sys.path.insert(0, "..")

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
from py3expr import expression

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

# --- User-defined type name: any non-primitive identifier, including subscripts
# e.g. MyClass, List[int], Optional[str], Dict[str, int]
# We use the full Python primary expression so subscript trailers are consumed.
from py3expr import primary as _primary
type_name = filt(
    lambda node: (
        # Accept primary expressions that start with a non-primitive identifier
        hasattr(node, 'nodes') and node.nodes
        and hasattr(node.nodes[0], 'nodes') and node.nodes[0].nodes
        and isinstance(node.nodes[0].nodes[0], str)
        and node.nodes[0].nodes[0] not in _PRIMITIVES
    ),
    _primary
)

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


def parse_type(source_code):
    """Parse a type annotation string."""
    inp = Input(source_code)
    result = type_annotation.parse(inp)
    if result is None:
        return None
    return result[0]


