#!/usr/bin/env python3
"""Python 3.14 Compound Statement Parser using hek_parsec combinator framework.

Builds on hek_py3_expr.py (expressions) and hek_py3_stmt.py (simple statements)
to parse compound (block) statements: if, while, for, try, with, match, def, class,
and async variants.

Compound statements contain indented blocks (suites) delimited by INDENT/DEDENT
tokens from the Python tokenizer.

Usage:
    ast = parse_compound("if x:\\n    pass\\n")
    print(ast.to_py())
"""

import sys
sys.path.insert(0, "..")

import tokenize as tkn

from hek_parsec import (
    COLON,
    COMMA,
    expect_type_node,
    DOUBLESTAR,
    EQUAL,
    IDENTIFIER,
    LPAREN,
    RPAREN,
    SEMICOLON,
    SSTAR,
    Input,
    ParserState,
    expect,
    expect_type,
    filt,
    fmap,
    fw,
    ignore,
    literal,
    nothing,
    shift,
)
from py3stmt import *  # noqa: F403 — need all fw() names in namespace
from py_declarations import type_annotation

###############################################################################
# Tokens not in hek_parsec
###############################################################################

INDENT = expect_type(tkn.INDENT)
DEDENT = expect_type(tkn.DEDENT)
# NL now returns RichNL objects that carry their comments
# This allows comments to travel naturally with the parse tree
# Use expect_type_node which matches both regular NL and RichNL (since RichNL.type == tkn.NL)
NL = expect_type_node(tkn.NL)
AT = ignore(expect(tkn.OP, "@"))  # decorator @ — ignored (we keep the expression)

# Visible operators needed for compound statements
V_COLON = vop(":")  # visible colon (prevent flattening in annotations)
V_EQUAL = vop("=")  # visible = (for default params)
V_SLASH = vop("/")  # positional-only param separator
V_ARROW = vop("->")  # return annotation arrow

###############################################################################
# Indentation helper
###############################################################################




###############################################################################
# Forward declarations
###############################################################################

# Block structure
block = fw("block")
statement = fw("statement")

# Compound statements
if_stmt = fw("if_stmt")
elif_clause = fw("elif_clause")
else_clause = fw("else_clause")
while_stmt = fw("while_stmt")
for_target = fw("for_target")
for_stmt = fw("for_stmt")
try_stmt = fw("try_stmt")
except_clause = fw("except_clause")
except_star_clause = fw("except_star_clause")
except_bare = fw("except_bare")
finally_clause = fw("finally_clause")
with_stmt = fw("with_stmt")
with_item = fw("with_item")
match_stmt = fw("match_stmt")
case_clause = fw("case_clause")
pattern = fw("pattern")

# Function definition
func_def = fw("func_def")
async_func_def = fw("async_func_def")
param_list = fw("param_list")
param = fw("param")
param_plain = fw("param_plain")
param_star = fw("param_star")
param_dstar = fw("param_dstar")
param_slash = fw("param_slash")
decorator = fw("decorator")
decorators = fw("decorators")

# Class definition
class_def = fw("class_def")

# Async variants
async_for_stmt = fw("async_for_stmt")
async_with_stmt = fw("async_with_stmt")

# Re-wrap imported Sequence_Parsers as fw() so they don't get flattened
# when used with '+' in grammar rules below (see ParserMeta.__add__).
_star_expressions = fw("star_expressions")

# Top-level
compound_stmt = fw("compound_stmt")

###############################################################################
# Grammar rules
###############################################################################

# --- Block (suite) ---
# Two forms:
#   1. Indented block: NEWLINE INDENT statement+ DEDENT
#   2. Simple suite:   stmt_line (simple stmts on same line with NEWLINE)
# NL tokens (blank lines) can appear inside blocks and must be skipped.

block = NEWLINE + NL[:] + INDENT + NL[:] + (statement + NL[:])[1:] + DEDENT

# statement: compound or simple (stmt_line includes NEWLINE)
statement = compound_stmt | stmt_line

# --- if / elif / else ---
elif_clause = ikw("elif") + named_expression + COLON + block
else_clause = ikw("else") + COLON + block
if_stmt = (
    ikw("if")
    + named_expression
    + COLON
    + block
    + (NL[:] + elif_clause)[:]
    + (NL[:] + else_clause)[:]
)

# --- while ---
while_stmt = ikw("while") + named_expression + COLON + block + (NL[:] + else_clause)[:]

# --- for ---
# For targets: identifiers (possibly tuple-unpacked), NOT full expressions
# (to prevent 'x in xs' being parsed as a comparison)
for_target = IDENTIFIER + (COMMA + IDENTIFIER)[:] + COMMA[:]
for_stmt = (
    ikw("for")
    + for_target
    + ikw("in")
    + _star_expressions
    + COLON
    + block
    + (NL[:] + else_clause)[:]
)

# --- try / except / finally ---
except_clause = ikw("except") + expression + (ikw("as") + IDENTIFIER)[:] + COLON + block
except_star_clause = (
    ikw("except") + SSTAR + expression + (ikw("as") + IDENTIFIER)[:] + COLON + block
)
except_bare = ikw("except") + COLON + block

try_except = (
    ikw("try")
    + COLON
    + block
    + NL[:]
    + (except_clause | except_star_clause | except_bare)
    + (NL[:] + (except_clause | except_star_clause | except_bare))[:]
    + (NL[:] + else_clause)[:]
    + (NL[:] + finally_clause)[:]
)
try_finally = ikw("try") + COLON + block + NL[:] + finally_clause
finally_clause = ikw("finally") + COLON + block

try_stmt = try_except | try_finally

# --- with ---
with_item = expression + (ikw("as") + star_expression)[:]
# Parenthesised with (Python 3.10+): with (ctx as x, ctx2 as y,): ...
with_stmt_paren = (
    ikw("with")
    + LPAREN
    + NL[:]
    + with_item
    + (COMMA + NL[:] + with_item)[:]
    + COMMA[:]
    + NL[:]
    + RPAREN
    + COLON
    + block
)
with_stmt = ikw("with") + with_item + (COMMA + with_item)[:] + COLON + block

# --- match / case patterns ---
# base_pattern: everything except or-pattern (to avoid left recursion)
pattern_literal = NUMBER | STRING | literal("None") | literal("True") | literal("False")
pattern_capture = IDENTIFIER
pattern_wildcard = literal("_")
pattern_group = LPAREN + pattern + RPAREN
pattern_sequence = LBRACKET + pattern + (COMMA + pattern)[:] + COMMA[:] + RBRACKET
pattern_value = (
    IDENTIFIER + (vop(".") + IDENTIFIER)[1:]
)  # qualified name like Status.OK
pattern_mapping = (
    LBRACE
    + (expression + V_COLON + pattern)
    + (COMMA + expression + V_COLON + pattern)[:]
    + COMMA[:]
    + RBRACE
)
# keyword_pattern: NAME '=' pattern  (e.g. Point(x=a, y=b))
keyword_pattern = IDENTIFIER + iop("=") + pattern
# pattern_class_arg: keyword_pattern before positional pattern (both start with IDENTIFIER)
pattern_class_arg = keyword_pattern | pattern
pattern_class = IDENTIFIER + LPAREN + (pattern_class_arg + (COMMA + pattern_class_arg)[:])[:] + RPAREN

# Order: value before capture (value has dots), class before capture (has parens)
# wildcard before capture (both are IDENTIFIER, but _ is special)
# mapping before sequence (both use brackets but { vs [)
base_pattern = (
    pattern_literal
    | pattern_wildcard
    | pattern_group
    | pattern_mapping
    | pattern_sequence
    | pattern_value
    | pattern_class
    | pattern_capture
)

# or-pattern: base ('|' base)+ — uses base_pattern to avoid left recursion
pattern_or = base_pattern + (vop("|") + base_pattern)[1:]

# AS pattern: pattern 'as' IDENTIFIER
pattern_as = base_pattern + ikw("as") + IDENTIFIER

# pattern: or_pattern | as_pattern | base_pattern
pattern = pattern_or | pattern_as | base_pattern

case_guard = ikw("if") + named_expression
case_clause = ikw("case") + pattern + case_guard[:] + COLON + block

match_stmt = (
    ikw("match")
    + expression
    + COLON
    + NEWLINE
    + INDENT
    + NL[:]
    + (case_clause + NL[:])[1:]
    + DEDENT
)

# --- Function parameters ---
# param_plain: name [':' annotation] ['=' default]
param_plain = IDENTIFIER + (V_COLON + type_annotation)[:] + (V_EQUAL + expression)[:]
# param_star: '*' [name [':' annotation]]  — bare * or *args
param_star = SSTAR + (IDENTIFIER + (V_COLON + expression)[:])[:]
# param_dstar: '**' name [':' annotation]
param_dstar = iop("**") + IDENTIFIER + (V_COLON + expression)[:]
# param_slash: '/'  — positional-only separator
param_slash = V_SLASH

param = param_dstar | param_star | param_slash | param_plain
param_list = param + (COMMA + param)[:] + COMMA[:]

# --- Decorators ---
decorator = AT + expression + NEWLINE + NL[:]
decorators = decorator[1:]

# --- Function definition ---
return_annotation = V_ARROW + type_annotation
func_def = (
    decorators[:]
    + ikw("def")
    + IDENTIFIER
    + LPAREN
    + param_list[:]
    + RPAREN
    + return_annotation[:]
    + COLON
    + block
)
async_func_def = (
    decorators[:]
    + ikw("async")
    + ikw("def")
    + IDENTIFIER
    + LPAREN
    + param_list[:]
    + RPAREN
    + return_annotation[:]
    + COLON
    + block
)

# --- Class definition ---
# class_args uses the same argument grammar as call_trailer so that
# keyword arguments like metaclass=Meta are correctly parsed.
class_args = LPAREN + arguments[:] + RPAREN
class_def = decorators[:] + ikw("class") + IDENTIFIER + class_args[:] + COLON + block

# --- Async variants ---
async_for_stmt = (
    ikw("async")
    + ikw("for")
    + for_target
    + ikw("in")
    + _star_expressions
    + COLON
    + block
)
async_with_stmt = (
    ikw("async") + ikw("with") + with_item + (COMMA + with_item)[:] + COLON + block
)

# --- compound_stmt: choice of all compound statement types ---
compound_stmt = (
    if_stmt
    | while_stmt
    | for_stmt
    | try_stmt
    | with_stmt_paren
    | with_stmt
    | match_stmt
    | async_func_def
    | func_def
    | class_def
    | async_for_stmt
    | async_with_stmt
)



###############################################################################
# Public API
###############################################################################


def parse_compound(code):
    """Parse a Python 3.14 compound statement and return the AST node."""
    ParserState.reset()
    stream = Input(code)
    result = compound_stmt.parse(stream)
    if not result:
        return None
    return result[0]


def parse_statement(code):
    """Parse a single Python 3.14 statement (compound or simple)."""
    ParserState.reset()
    stream = Input(code)
    result = statement.parse(stream)
    if not result:
        return None
    return result[0]


def parse_module(code):
    """Parse a complete Python 3.14 module (sequence of statements)."""
    ParserState.reset()
    stream = Input(code)
    module_parser = (NL[:] + (statement + NL[:])[1:])
    result = module_parser.parse(stream)
    if not result:
        return None
    return result[0]
