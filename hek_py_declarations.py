#!/usr/bin/env python3
"""Odin-style Declaration Parser using hek_parsec combinator framework.

Odin declaration syntax:
    - Variable:      name : type
    - Initialized:   name : type = value
    - Multiple:      (name1, name2 : type)
    - Constant:      name :: value
    - Type alias:    name :: type
    - Auto type:     name = value  (type inferred)

Usage:
    ast = parse_decl("x : int")
    print(ast.to_py())  # x : int
"""

import tokenize as tkn

from hek_parsec import (
    COLON,
    COMMA,
    EQUAL,
    IDENTIFIER,
    LPAREN,
    RPAREN,
    Input,
    Parser,
    ParserState,
    expect,
    expect_type,
    fw,
    ignore,
    literal,
    method,
)
from hek_py3_expr import *  # noqa: F403 — need all fw() names in namespace

###############################################################################
# Tokens not in hek_parsec
###############################################################################

NEWLINE = expect_type(tkn.NEWLINE)

# Visible '::' for Odin-style constant/type declaration (two consecutive colons)
V_DOUBLECOLON = vop(":") + vop(":")

# Visible ':' for type annotation
V_COLON = vop(":")

# Visible '=' for assignment
V_EQUAL = vop("=")

###############################################################################
# Forward declarations
###############################################################################

declaration = fw("declaration")
var_decl = fw("var_decl")
const_decl = fw("const_decl")
type_decl = fw("type_decl")
decl_list = fw("decl_list")
decl_target = fw("decl_target")

###############################################################################
# Grammar rules
###############################################################################

# --- decl_target: single identifier or parenthesized list ---
# Single: x : int
# Multi:  (x, y, z : int)
decl_target_single = IDENTIFIER
decl_target_multi = LPAREN + IDENTIFIER + (COMMA + IDENTIFIER)[1:] + RPAREN
decl_target = decl_target_multi | decl_target_single

# --- Variable declaration: target : type ---
# x : int
# (x, y) : int
var_decl = decl_target + V_COLON + type_annotation

# --- Initialized variable: target : type = expr ---
# x : int = 1
# (x, y) : int = get_vals()
var_decl_init = decl_target + V_COLON + type_annotation + V_EQUAL + expression

# --- Constant declaration: target :: expr ---
# MAX_SIZE :: 100
# PI :: 3.14159
const_decl = decl_target + V_DOUBLECOLON + expression

# --- Type declaration: target :: type_expr ---
# MyInt :: int
# Vec2 :: struct { x, y : float }
type_decl = decl_target + V_DOUBLECOLON + type_annotation

# --- Auto-typed variable (type inference): target = expr ---
# x = 1  (type inferred as int)
auto_decl = decl_target + V_EQUAL + expression

# --- declaration: choice of all declaration forms ---
# Ordering matters: try more specific forms first
declaration = var_decl_init | var_decl | const_decl | type_decl | auto_decl

# --- decl_list: one or more declarations (newline separated) ---
decl_list = declaration + (NEWLINE + declaration)[1:]

###############################################################################
# AST to Python code generation
###############################################################################


@method(decl_target_multi)
def to_py(self):
    """decl_target_multi: '(' IDENTIFIER (',' IDENTIFIER)+ ')'"""
    names = [self.nodes[0].to_py()]
    for node in self.nodes[1:]:
        if hasattr(node, "nodes") and node.nodes:
            for seq in node.nodes:
                if hasattr(seq, "nodes") and seq.nodes:
                    names.append(seq.nodes[0].to_py())
    return ", ".join(names)


@method(var_decl)
def to_py(self):
    """var_decl: decl_target ':' type_annotation"""
    target = self.nodes[0].to_py()
    typ = self.nodes[2].to_py()
    return f"{target} : {typ}"


@method(var_decl_init)
def to_py(self):
    """var_decl_init: decl_target ':' type_annotation '=' expression"""
    target = self.nodes[0].to_py()
    typ = self.nodes[2].to_py()
    val = self.nodes[4].to_py()
    return f"{target} : {typ} = {val}"


@method(const_decl)
def to_py(self):
    """const_decl: decl_target '::' expression"""
    target = self.nodes[0].to_py()
    val = self.nodes[2].to_py()
    return f"{target} :: {val}"


@method(type_decl)
def to_py(self):
    """type_decl: decl_target '::' type_annotation"""
    target = self.nodes[0].to_py()
    typ = self.nodes[2].to_py()
    return f"{target} :: {typ}"


@method(auto_decl)
def to_py(self):
    """auto_decl: decl_target '=' expression"""
    target = self.nodes[0].to_py()
    val = self.nodes[2].to_py()
    return f"{target} = {val}"


@method(declaration)
def to_py(self):
    """declaration: var_decl_init | var_decl | const_decl | type_decl | auto_decl"""
    return self.nodes[0].to_py()


@method(decl_list)
def to_py(self):
    """decl_list: declaration (NEWLINE declaration)*"""
    lines = [self.nodes[0].to_py()]
    for node in self.nodes[1:]:
        if hasattr(node, "nodes") and node.nodes:
            lines.append(node.nodes[0].to_py())
    return "\n".join(lines)


###############################################################################
# Parse functions
###############################################################################


def parse_decl(source_code):
    """Parse a single Odin-style declaration."""
    inp = Input(source_code)
    result = declaration.parse(inp)
    if result is None:
        return None
    return result[0]


def parse_decls(source_code):
    """Parse multiple Odin-style declarations (newline separated)."""
    inp = Input(source_code)
    result = decl_list.parse(inp)
    if result is None:
        return None
    return result[0]


###############################################################################
# Tests
###############################################################################

if __name__ == "__main__":
    print("=" * 60)
    print("Odin-style Declaration Parser Tests")
    print("=" * 60)

    test_cases = [
        # Variable declarations
        ("x : int", "x : int"),
        ("name : str", "name : str"),
        ("count : int", "count : int"),
        # Initialized variables
        ("x : int = 1", "x : int = 1"),
        ("name : str = 'hello'", "name : str = 'hello'"),
        ("pi : float = 3.14", "pi : float = 3.14"),
        # Multiple targets
        ("(x, y) : int", "x, y : int"),
        ("(a, b, c) : int = 0", "a, b, c : int = 0"),
        # Constant declarations
        ("MAX :: 100", "MAX :: 100"),
        ("PI :: 3.14159", "PI :: 3.14159"),
        ("NAME :: 'test'", "NAME :: 'test'"),
        # Type declarations
        ("MyInt :: int", "MyInt :: int"),
        ("Vec2 :: float", "Vec2 :: float"),
        # Auto-typed (inferred)
        ("x = 1", "x = 1"),
        ("name = 'hello'", "name = 'hello'"),
        # Expression with operators
        ("x : int = 1 + 2", "x : int = 1 + 2"),
        ("y : int = a * b", "y : int = a * b"),
    ]

    passed = 0
    failed = 0

    for code, expected in test_cases:
        try:
            ast = parse_decl(code)
            if ast is None:
                print(f"  FAIL: {code!r} -> parse returned None")
                failed += 1
            else:
                output = ast.to_py()
                if output == expected:
                    print(f"  PASS: {code!r} -> {output!r}")
                    passed += 1
                else:
                    print(f"  FAIL: {code!r} -> {output!r} (expected {expected!r})")
                    failed += 1
        except Exception as e:
            print(f"  ERROR: {code!r} -> {e}")
            failed += 1

    print("=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
