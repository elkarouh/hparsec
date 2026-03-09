#!/usr/bin/env python3
"""Python 3.14 Simple Statement Parser using hek_parsec combinator framework.

Builds on hek_py3_expr.py (expression grammar) to parse simple (non-compound)
Python 3.14 statements. Simple statements fit on one line, can be separated
by ';', and are terminated by NEWLINE.

Statements implemented:
    - Assignment:          x = 1, a = b = 1
    - Augmented assignment: x += 1, x @= m
    - Annotated assignment: x: int = 1
    - return, pass, break, continue
    - del, assert, raise
    - global, nonlocal
    - import, from ... import
    - type alias:          type X = int | str  (3.12+)
    - Expression statement: f(x), x

Usage:
    ast = parse_stmt("x = 1")
    print(ast.to_py())  # x = 1
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import tokenize as tkn

from hek_parsec import (
    COLON,
    COMMA,
    DOT,
    EQUAL,
    IDENTIFIER,
    LBRACE,
    LBRACKET,
    LPAREN,
    NUMBER,
    RBRACE,
    RBRACKET,
    RPAREN,
    SEMICOLON,
    SSTAR,
    STRING,
    Input,
    Parser,
    ParserState,
    expect,
    expect_type,
    expect_type_node,
    expect_nl_or_richnl,
    filt,
    fmap,
    fw,
    ignore,
    literal,
    method,
    nothing,
    shift,
)
from py3expr import *  # noqa: F403 — need all fw() names in namespace
from py_declarations import type_annotation

###############################################################################
# Tokens not in hek_parsec
###############################################################################

NEWLINE = expect_type_node(tkn.NEWLINE)  # preserve RichNL so inline comments travel with stmt
NL = expect_nl_or_richnl()  # Returns RichNL or NL token node

###############################################################################
# Operator helpers (augmented assignment operators — all visible)
###############################################################################

augop = (
    vop("+=")
    | vop("-=")
    | vop("*=")
    | vop("/=")
    | vop("//=")
    | vop("%=")
    | vop("**=")
    | vop("@=")
    | vop("<<=")
    | vop(">>=")
    | vop("&=")
    | vop("|=")
    | vop("^=")
)

# Visible '=' for assignment (EQUAL from hek_parsec is ignored)
V_EQUAL = vop("=")

# Visible ':' for annotation (COLON from hek_parsec is ignored)
V_COLON = vop(":")

# Visible '.' for dotted names (DOT from hek_parsec is ignored)
V_DOT = vop(".")

###############################################################################
# Forward declarations
###############################################################################

assign_stmt = fw("assign_stmt")
aug_assign_stmt = fw("aug_assign_stmt")
ann_assign_stmt = fw("ann_assign_stmt")
decl_keyword = fw("decl_keyword")
decl_ann_assign_stmt = fw("decl_ann_assign_stmt")
return_stmt = fw("return_stmt")
pass_stmt = fw("pass_stmt")
break_stmt = fw("break_stmt")
continue_stmt = fw("continue_stmt")
del_stmt = fw("del_stmt")
assert_stmt = fw("assert_stmt")
raise_stmt = fw("raise_stmt")
global_stmt = fw("global_stmt")
nonlocal_stmt = fw("nonlocal_stmt")
import_stmt = fw("import_stmt")
from_stmt = fw("from_stmt")
type_stmt = fw("type_stmt")
enum_def = fw("enum_def")
simple_stmt = fw("simple_stmt")
stmt_line = fw("stmt_line")

# Re-wrap imported Sequence_Parsers as fw() so they don't get flattened
# when used with '+' in grammar rules below (see ParserMeta.__add__).
_star_expressions = fw("star_expressions")
_expressions = fw("expressions")

# Import sub-rules
dotted_name = fw("dotted_name")
import_as = fw("import_as")
import_name = fw("import_name")
import_names = fw("import_names")
from_rel_name = fw("from_rel_name")
from_rel_bare = fw("from_rel_bare")
from_abs = fw("from_abs")

###############################################################################
# Grammar rules
###############################################################################

# --- Assignment ---
# assign: target ('=' target)* '=' expressions
# We need V_EQUAL (visible) so we can count targets vs value.
# Python allows: a = b = c = 1  (chained) and a, b = 1, 2 (tuple unpack)
assign_stmt = _star_expressions + (V_EQUAL + _star_expressions)[1:]

# --- Augmented assignment ---
# aug_assign: target augop expressions
aug_assign_stmt = _star_expressions + augop + _expressions

# --- Annotated assignment ---
# ann_assign: IDENTIFIER ':' type_annotation ['=' expression]
ann_assign_stmt = IDENTIFIER + V_COLON + type_annotation + (V_EQUAL + expression)[:]

# --- Declaration with keyword (var/let/const) ---
# decl_ann_assign: ("var"|"let"|"const") IDENTIFIER ':' type_annotation ['=' expression]
decl_keyword = literal("var") | literal("let") | literal("const")
decl_ann_assign_stmt = decl_keyword + IDENTIFIER + V_COLON + type_annotation + (V_EQUAL + expression)[:]

# --- return ---
return_val = ikw("return") + _expressions
return_bare = literal("return")
return_stmt = return_val | return_bare

# --- pass / break / continue ---
pass_stmt = literal("pass")
break_stmt = literal("break")
continue_stmt = literal("continue")

# --- del ---
del_stmt = ikw("del") + _star_expressions

# --- assert ---
assert_msg = ikw("assert") + expression + COMMA + expression
assert_simple = ikw("assert") + expression
assert_stmt = assert_msg | assert_simple

# --- raise ---
raise_from = ikw("raise") + expression + ikw("from") + expression
raise_exc = ikw("raise") + expression
raise_bare = literal("raise")
raise_stmt = raise_from | raise_exc | raise_bare

# --- global / nonlocal ---
global_stmt = ikw("global") + IDENTIFIER + (COMMA + IDENTIFIER)[:]
nonlocal_stmt = ikw("nonlocal") + IDENTIFIER + (COMMA + IDENTIFIER)[:]

# --- import ---
dotted_name = IDENTIFIER + (V_DOT + IDENTIFIER)[:]
import_as = dotted_name + (ikw("as") + IDENTIFIER)[:]
import_stmt = ikw("import") + import_as + (COMMA + import_as)[:]

# --- from ... import ---
import_name = IDENTIFIER + (ikw("as") + IDENTIFIER)[:]
import_star = SSTAR
# Parenthesized imports: (name, name) for multi-line imports
import_names_paren = LPAREN_NODE + NL[:] + import_name + (NL[:] + COMMA + NL[:] + import_name)[:] + COMMA[:] + NL[:] + RPAREN
import_names = import_names_paren | import_name + (COMMA + import_name)[:] | import_star

# from_stmt variants (explicit to avoid dotted_name greedily consuming 'import'):
#   from ..pkg import x     -> from_rel_name: dots + dotted_name + import + names
#   from .   import x       -> from_rel_bare: dots + import + names
#   from os  import x       -> from_abs:      dotted_name + import + names
from_rel_name = ikw("from") + V_DOT[1:] + dotted_name + ikw("import") + import_names
from_rel_bare = ikw("from") + V_DOT[1:] + ikw("import") + import_names
from_abs = ikw("from") + dotted_name + ikw("import") + import_names
from_stmt = from_rel_name | from_rel_bare | from_abs

# --- type alias (3.12+) / enum ---
# type_alias_params: [T] or [T, U] etc. (generic type parameters)
type_alias_params = LBRACKET + IDENTIFIER + (COMMA + IDENTIFIER)[:] + RBRACKET
# enum_def: enum IDENT, IDENT, ...
enum_def = ikw("enum") + IDENTIFIER + (COMMA + IDENTIFIER)[:] + COMMA[:]
type_stmt = ikw("type") + IDENTIFIER + type_alias_params[:] + V_EQUAL + (enum_def | expression)

# --- simple_stmt: choice of all statement types ---
# Ordering matters: try more specific forms before general expression.
# aug_assign before assign (both start with expr, but augop is distinctive).
# ann_assign before assign (starts with IDENTIFIER + ':').
# expressions is the fallback (expression statement).
simple_stmt = (
    decl_ann_assign_stmt
    | ann_assign_stmt
    | aug_assign_stmt
    | assign_stmt
    | return_stmt
    | pass_stmt
    | break_stmt
    | continue_stmt
    | del_stmt
    | assert_stmt
    | raise_stmt
    | global_stmt
    | nonlocal_stmt
    | import_stmt
    | from_stmt
    | type_stmt
    | yield_expr
    | expressions
)

# --- stmt_line: semicolon-separated statements on one line ---
stmt_line = simple_stmt + (SEMICOLON + simple_stmt)[:] + SEMICOLON[:] + NEWLINE

###############################################################################


def parse_stmt(code):
    """Parse a Python 3.14 simple statement and return the AST node.

    Parses a single simple_stmt (no NEWLINE required).
    """
    ParserState.reset()
    stream = Input(code)
    result = simple_stmt.parse(stream)
    if not result:
        return None
    return result[0]


def parse_stmt_line(code):
    """Parse a line of semicolon-separated simple statements.

    Expects NEWLINE at end (as produced by tokenizer for complete lines).
    """
    ParserState.reset()
    stream = Input(code)
    result = stmt_line.parse(stream)
    if not result:
        return None
    return result[0]


###############################################################################
# Tests
###############################################################################

