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
    DOUBLESTAR,
    EQUAL,
    IDENTIFIER,
    LPAREN,
    RPAREN,
    SEMICOLON,
    SSTAR,
    Input,
    Parser,
    ParserState,
    expect,
    expect_type,
    filt,
    fmap,
    fw,
    ignore,
    literal,
    method,
    nothing,
    shift,
)
from hek_py3_stmt import *  # noqa: F403 — need all fw() names in namespace
from hek_py_declarations import type_annotation

###############################################################################
# Tokens not in hek_parsec
###############################################################################

INDENT = expect_type(tkn.INDENT)
DEDENT = expect_type(tkn.DEDENT)
NL = ignore(expect_type(tkn.NL))  # blank lines — always ignored
AT = ignore(expect(tkn.OP, "@"))  # decorator @ — ignored (we keep the expression)

# Visible operators needed for compound statements
V_COLON = vop(":")  # visible colon (prevent flattening in annotations)
V_EQUAL = vop("=")  # visible = (for default params)
V_SLASH = vop("/")  # positional-only param separator
V_ARROW = vop("->")  # return annotation arrow

###############################################################################
# Indentation helper
###############################################################################

INDENT_STR = "    "


def _ind(level):
    """Return indentation string for the given nesting level."""
    return INDENT_STR * level


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

block = NEWLINE + INDENT + NL[:] + (statement + NL[:])[1:] + DEDENT

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
    + star_expressions
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
pattern_class = IDENTIFIER + LPAREN + (pattern + (COMMA + pattern)[:])[:] + RPAREN

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
param_star = SSTAR + (IDENTIFIER + (V_COLON + type_annotation)[:])[:]
# param_dstar: '**' name [':' annotation]
param_dstar = iop("**") + IDENTIFIER + (V_COLON + type_annotation)[:]
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
class_args = LPAREN + (expression + (COMMA + expression)[:] + COMMA[:])[:] + RPAREN
class_def = decorators[:] + ikw("class") + IDENTIFIER + class_args[:] + COLON + block

# --- Async variants ---
async_for_stmt = (
    ikw("async")
    + ikw("for")
    + for_target
    + ikw("in")
    + star_expressions
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
    | with_stmt
    | match_stmt
    | async_func_def
    | func_def
    | class_def
    | async_for_stmt
    | async_with_stmt
)

###############################################################################
# to_py() methods
###############################################################################


# --- block ---
@method(block)
def to_py(self, indent=0):
    """block: NEWLINE INDENT NL* (statement NL*)+ DEDENT"""
    lines = []
    for node in self.nodes:
        tname = type(node).__name__
        # Skip NEWLINE/INDENT/DEDENT Fmap nodes (string values like '\n', '    ', '')
        if tname == "Fmap":
            continue
        if tname == "Several_Times":
            for seq in node.nodes:
                # Each seq is either:
                #   - a statement node directly (when NL[:] matched 0 times)
                #   - a Sequence_Parser [statement, Several_Times([None])]
                #     (when NL[:] matched, producing NL ignored nodes)
                inner = seq
                if type(seq).__name__ == "Sequence_Parser" and hasattr(seq, "nodes"):
                    # Extract the statement (first non-None, non-Several_Times child)
                    for child in seq.nodes:
                        if (
                            child is not None
                            and type(child).__name__ != "Several_Times"
                        ):
                            inner = child
                            break
                if inner is not None and hasattr(inner, "to_py"):
                    try:
                        lines.append(inner.to_py(indent))
                    except TypeError:
                        lines.append(_ind(indent) + inner.to_py())
        elif hasattr(node, "to_py"):
            try:
                lines.append(node.to_py(indent))
            except TypeError:
                lines.append(_ind(indent) + node.to_py())
    return "\n".join(lines)


@method(statement)
def to_py(self, indent=0):
    """statement: compound_stmt | stmt_line"""
    inner = self.nodes[0]
    try:
        return inner.to_py(indent)
    except TypeError:
        return _ind(indent) + inner.to_py()


# --- if / elif / else ---
@method(elif_clause)
def to_py(self, indent=0):
    """elif_clause: 'elif' named_expression ':' block"""
    cond = self.nodes[0].to_py()
    body = self.nodes[1].to_py(indent + 1)
    return f"{_ind(indent)}elif {cond}:\n{body}"


@method(else_clause)
def to_py(self, indent=0):
    """else_clause: 'else' ':' block"""
    body = self.nodes[0].to_py(indent + 1)
    return f"{_ind(indent)}else:\n{body}"


@method(if_stmt)
def to_py(self, indent=0):
    """if_stmt: 'if' named_expression ':' block ('elif' ...)* ('else' ...)?"""
    cond = self.nodes[0].to_py()
    body = self.nodes[1].to_py(indent + 1)
    result = f"{_ind(indent)}if {cond}:\n{body}"
    # Process remaining nodes (elif/else clauses from Several_Times)
    for node in self.nodes[2:]:
        if not hasattr(node, "nodes") or not node.nodes:
            continue
        for seq in node.nodes:
            if hasattr(seq, "nodes") and seq.nodes:
                clause = seq.nodes[0] if hasattr(seq.nodes[0], "to_py") else seq
            else:
                clause = seq
            if hasattr(clause, "to_py"):
                try:
                    result += "\n" + clause.to_py(indent)
                except TypeError:
                    result += "\n" + _ind(indent) + clause.to_py()
    return result


# --- while ---
@method(while_stmt)
def to_py(self, indent=0):
    """while_stmt: 'while' named_expression ':' block ('else' ':' block)?"""
    cond = self.nodes[0].to_py()
    body = self.nodes[1].to_py(indent + 1)
    result = f"{_ind(indent)}while {cond}:\n{body}"
    for node in self.nodes[2:]:
        if not hasattr(node, "nodes") or not node.nodes:
            continue
        for seq in node.nodes:
            clause = (
                seq.nodes[0]
                if hasattr(seq, "nodes")
                and seq.nodes
                and hasattr(seq.nodes[0], "to_py")
                else seq
            )
            if hasattr(clause, "to_py"):
                try:
                    result += "\n" + clause.to_py(indent)
                except TypeError:
                    pass
    return result


# --- for ---
@method(for_target)
def to_py(self):
    """for_target: IDENTIFIER (',' IDENTIFIER)* ','?"""
    parts = [self.nodes[0].to_py()]
    for node in self.nodes[1:]:
        if type(node).__name__ == "Several_Times" and node.nodes:
            for seq in node.nodes:
                if hasattr(seq, "nodes") and seq.nodes:
                    parts.append(seq.nodes[0].to_py())
    return ", ".join(parts)


@method(for_stmt)
def to_py(self, indent=0):
    """for_stmt: 'for' for_target 'in' star_expressions ':' block ('else' ...)?"""
    target = self.nodes[0].to_py()
    iterable = self.nodes[1].to_py()
    body = self.nodes[2].to_py(indent + 1)
    result = f"{_ind(indent)}for {target} in {iterable}:\n{body}"
    for node in self.nodes[3:]:
        if not hasattr(node, "nodes") or not node.nodes:
            continue
        for seq in node.nodes:
            clause = (
                seq.nodes[0]
                if hasattr(seq, "nodes")
                and seq.nodes
                and hasattr(seq.nodes[0], "to_py")
                else seq
            )
            if hasattr(clause, "to_py"):
                try:
                    result += "\n" + clause.to_py(indent)
                except TypeError:
                    pass
    return result


# --- try / except / finally ---
@method(except_clause)
def to_py(self, indent=0):
    """except_clause: 'except' expression ('as' IDENTIFIER)? ':' block"""
    exc = self.nodes[0].to_py()
    result = f"except {exc}"
    # Check for 'as' alias
    for node in self.nodes[1:]:
        if type(node).__name__ == "Several_Times" and node.nodes:
            for seq in node.nodes:
                if hasattr(seq, "nodes") and seq.nodes:
                    result += f" as {seq.nodes[0].to_py()}"
            continue
        if hasattr(node, "to_py"):
            # This is the block
            try:
                body = node.to_py(indent + 1)
            except TypeError:
                body = _ind(indent + 1) + node.to_py()
            return f"{_ind(indent)}{result}:\n{body}"
    return f"{_ind(indent)}{result}:"


@method(except_star_clause)
def to_py(self, indent=0):
    """except_star_clause: 'except' '*' expression ('as' IDENTIFIER)? ':' block"""
    # SSTAR is visible, so nodes[0] is '*', nodes[1] is expression
    exc = self.nodes[1].to_py()
    result = f"except* {exc}"
    for node in self.nodes[2:]:
        if type(node).__name__ == "Several_Times" and node.nodes:
            for seq in node.nodes:
                if hasattr(seq, "nodes") and seq.nodes:
                    result += f" as {seq.nodes[0].to_py()}"
            continue
        if hasattr(node, "to_py"):
            try:
                body = node.to_py(indent + 1)
            except TypeError:
                body = _ind(indent + 1) + node.to_py()
            return f"{_ind(indent)}{result}:\n{body}"
    return f"{_ind(indent)}{result}:"


@method(except_bare)
def to_py(self, indent=0):
    """except_bare: 'except' ':' block"""
    body = self.nodes[0].to_py(indent + 1)
    return f"{_ind(indent)}except:\n{body}"


@method(finally_clause)
def to_py(self, indent=0):
    """finally_clause: 'finally' ':' block"""
    body = self.nodes[0].to_py(indent + 1)
    return f"{_ind(indent)}finally:\n{body}"


def _extract_clauses(nodes, indent):
    """Extract except/else/finally clauses from flattened Several_Times nodes."""
    parts = []
    for node in nodes:
        if not hasattr(node, "nodes"):
            if hasattr(node, "to_py"):
                try:
                    parts.append(node.to_py(indent))
                except TypeError:
                    parts.append(_ind(indent) + node.to_py())
            continue
        if type(node).__name__ == "Several_Times":
            for seq in node.nodes:
                if hasattr(seq, "nodes") and seq.nodes:
                    inner = seq.nodes[0] if len(seq.nodes) == 1 else seq
                    if hasattr(inner, "to_py"):
                        try:
                            parts.append(inner.to_py(indent))
                        except TypeError:
                            parts.append(_ind(indent) + inner.to_py())
                elif hasattr(seq, "to_py"):
                    try:
                        parts.append(seq.to_py(indent))
                    except TypeError:
                        parts.append(_ind(indent) + seq.to_py())
        elif hasattr(node, "to_py"):
            try:
                parts.append(node.to_py(indent))
            except TypeError:
                parts.append(_ind(indent) + node.to_py())
    return parts


@method(try_except)
def to_py(self, indent=0):
    """try_except: 'try' ':' block (except_clause | except_star | except_bare)+
    ('else' ':' block)? ('finally' ':' block)?"""
    body = self.nodes[0].to_py(indent + 1)
    result = f"{_ind(indent)}try:\n{body}"
    # First except clause is nodes[1]
    try:
        result += "\n" + self.nodes[1].to_py(indent)
    except TypeError:
        result += "\n" + _ind(indent) + self.nodes[1].to_py()
    # Remaining clauses
    clauses = _extract_clauses(self.nodes[2:], indent)
    for c in clauses:
        result += "\n" + c
    return result


@method(try_finally)
def to_py(self, indent=0):
    """try_finally: 'try' ':' block 'finally' ':' block"""
    body = self.nodes[0].to_py(indent + 1)
    fin = self.nodes[1].to_py(indent)
    return f"{_ind(indent)}try:\n{body}\n{fin}"


@method(try_stmt)
def to_py(self, indent=0):
    """try_stmt: try_except | try_finally"""
    return self.nodes[0].to_py(indent)


# --- with ---
@method(with_item)
def to_py(self):
    """with_item: expression ('as' star_expression)?"""
    expr = self.nodes[0].to_py()
    for node in self.nodes[1:]:
        if type(node).__name__ == "Several_Times" and node.nodes:
            for seq in node.nodes:
                if hasattr(seq, "nodes") and seq.nodes:
                    return f"{expr} as {seq.nodes[0].to_py()}"
    return expr


@method(with_stmt)
def to_py(self, indent=0):
    """with_stmt: 'with' with_item (',' with_item)* ':' block"""
    items = [self.nodes[0].to_py()]
    # Find block (last node with to_py that takes indent)
    block_node = None
    for node in self.nodes[1:]:
        if type(node).__name__ == "Several_Times":
            for seq in node.nodes:
                if hasattr(seq, "nodes") and seq.nodes:
                    item = seq.nodes[0]
                    if hasattr(item, "to_py"):
                        items.append(item.to_py())
        elif hasattr(node, "to_py"):
            block_node = node
    body = ""
    if block_node:
        try:
            body = block_node.to_py(indent + 1)
        except TypeError:
            body = _ind(indent + 1) + block_node.to_py()
    return f"{_ind(indent)}with {', '.join(items)}:\n{body}"


# --- match / case ---
@method(pattern_literal)
def to_py(self):
    """pattern_literal: NUMBER | STRING | 'None' | 'True' | 'False'"""
    return (
        self.nodes[0].to_py() if hasattr(self.nodes[0], "to_py") else str(self.nodes[0])
    )


@method(pattern_capture)
def to_py(self):
    """pattern_capture: IDENTIFIER"""
    return (
        self.nodes[0].to_py() if hasattr(self.nodes[0], "to_py") else str(self.nodes[0])
    )


@method(pattern_wildcard)
def to_py(self):
    """pattern_wildcard: '_'"""
    return "_"


@method(pattern_group)
def to_py(self):
    """pattern_group: '(' pattern ')'"""
    return f"({self.nodes[0].to_py()})"


@method(pattern_sequence)
def to_py(self):
    """pattern_sequence: '[' pattern (',' pattern)* ','? ']'"""
    parts = [self.nodes[0].to_py()]
    for node in self.nodes[1:]:
        if type(node).__name__ == "Several_Times" and node.nodes:
            for seq in node.nodes:
                if hasattr(seq, "nodes") and seq.nodes:
                    parts.append(seq.nodes[0].to_py())
    return f"[{', '.join(parts)}]"


@method(pattern_or)
def to_py(self):
    """pattern_or: pattern ('|' pattern)+"""
    # Similar to binop — base + Several_Times[(op, pattern)]
    parts = [self.nodes[0].to_py()]
    for node in self.nodes[1:]:
        if type(node).__name__ == "Several_Times" and node.nodes:
            for seq in node.nodes:
                if hasattr(seq, "nodes") and len(seq.nodes) >= 2:
                    parts.append(seq.nodes[1].to_py())
    return " | ".join(parts)


@method(pattern_value)
def to_py(self):
    """pattern_value: IDENTIFIER ('.' IDENTIFIER)+"""
    parts = [self.nodes[0].to_py()]
    for node in self.nodes[1:]:
        if type(node).__name__ == "Several_Times" and node.nodes:
            for seq in node.nodes:
                if hasattr(seq, "nodes") and len(seq.nodes) >= 2:
                    parts.append(seq.nodes[1].to_py())
    return ".".join(parts)


@method(pattern_class)
def to_py(self):
    """pattern_class: IDENTIFIER '(' (pattern (',' pattern)*)? ')'"""
    name = self.nodes[0].to_py()
    # Patterns inside parens
    patterns = []
    for node in self.nodes[1:]:
        if type(node).__name__ == "Several_Times" and node.nodes:
            for seq in node.nodes:
                if hasattr(seq, "nodes"):
                    # Inner structure: [pattern, Several_Times[(pattern)...]]
                    patterns.append(seq.nodes[0].to_py())
                    for inner in seq.nodes[1:]:
                        if type(inner).__name__ == "Several_Times" and inner.nodes:
                            for sub in inner.nodes:
                                if hasattr(sub, "nodes") and sub.nodes:
                                    patterns.append(sub.nodes[0].to_py())
                elif hasattr(seq, "to_py"):
                    patterns.append(seq.to_py())
    return f"{name}({', '.join(patterns)})"


@method(pattern_mapping)
def to_py(self):
    """pattern_mapping: '{' (expression ':' pattern) (',' expression ':' pattern)* ','? '}'"""
    pairs = []

    def _extract_pair(nodes):
        """Extract key: value from [expr, Fmap(':'), pattern] sequence."""
        key = val = None
        for n in nodes:
            tname = type(n).__name__
            if (
                tname == "Fmap"
                and hasattr(n, "nodes")
                and n.nodes
                and n.nodes[0] == ":"
            ):
                continue
            elif key is None and hasattr(n, "to_py"):
                key = n.to_py()
            elif hasattr(n, "to_py"):
                val = n.to_py()
        if key and val:
            pairs.append(f"{key}: {val}")

    for child in self.nodes:
        tname = type(child).__name__
        if tname == "Sequence_Parser" and hasattr(child, "nodes"):
            _extract_pair(child.nodes)
        elif tname == "Several_Times":
            for seq in child.nodes:
                if hasattr(seq, "nodes"):
                    _extract_pair(seq.nodes)
    return "{" + ", ".join(pairs) + "}"


@method(base_pattern)
def to_py(self):
    """base_pattern: literal | wildcard | group | mapping | sequence | value | class | capture"""
    return self.nodes[0].to_py()


@method(pattern_as)
def to_py(self):
    """pattern_as: base_pattern 'as' IDENTIFIER"""
    pat = self.nodes[0].to_py()
    name = self.nodes[1].to_py()
    return f"{pat} as {name}"


@method(pattern)
def to_py(self):
    """pattern: or_pattern | as_pattern | base_pattern"""
    return self.nodes[0].to_py()


@method(case_guard)
def to_py(self):
    """case_guard: 'if' named_expression"""
    return f" if {self.nodes[0].to_py()}"


@method(case_clause)
def to_py(self, indent=0):
    """case_clause: 'case' pattern ('if' guard)? ':' block"""
    pat = self.nodes[0].to_py()
    guard = ""
    block_node = None
    for node in self.nodes[1:]:
        if type(node).__name__ == "Several_Times" and node.nodes:
            for seq in node.nodes:
                if hasattr(seq, "to_py"):
                    guard = seq.to_py()
        elif hasattr(node, "to_py"):
            block_node = node
    body = ""
    if block_node:
        try:
            body = block_node.to_py(indent + 1)
        except TypeError:
            body = _ind(indent + 1) + block_node.to_py()
    return f"{_ind(indent)}case {pat}{guard}:\n{body}"


@method(match_stmt)
def to_py(self, indent=0):
    """match_stmt: 'match' expression ':' NEWLINE INDENT (case_clause)+ DEDENT"""
    subject = self.nodes[0].to_py()
    result = f"{_ind(indent)}match {subject}:"
    # Case clauses are in the Several_Times node.
    # Each case is a Sequence_Parser [pattern, block] or [pattern, Several_Times(guard), block]
    # due to case_clause being flattened.
    for node in self.nodes[1:]:
        tname = type(node).__name__
        if tname == "case_clause":
            result += "\n" + node.to_py(indent + 1)
        elif tname == "Several_Times":
            for seq in node.nodes:
                stname = type(seq).__name__
                if stname == "case_clause":
                    result += "\n" + seq.to_py(indent + 1)
                elif stname == "Sequence_Parser" and hasattr(seq, "nodes"):
                    result += "\n" + _case_from_seq(seq, indent + 1)
    return result


def _case_from_seq(seq, indent):
    """Reconstruct a case clause from a flattened Sequence_Parser [pattern, guard?, block]."""
    pat = ""
    guard = ""
    body = ""
    for child in seq.nodes:
        tname = type(child).__name__
        if tname == "block":
            body = child.to_py(indent + 1)
        elif tname == "Several_Times":
            # case_guard[:] contents
            for inner in child.nodes:
                if hasattr(inner, "to_py"):
                    guard = inner.to_py()
        elif tname == "case_guard":
            guard = child.to_py()
        else:
            # pattern node
            pat = child.to_py()
    return f"{_ind(indent)}case {pat}{guard}:\n{body}"


# --- Function parameters ---
@method(param_plain)
def to_py(self):
    """param_plain: IDENTIFIER (':' expression)? ('=' expression)?"""
    name = self.nodes[0].to_py()
    annotation = ""
    default = ""
    for node in self.nodes[1:]:
        if type(node).__name__ == "Several_Times" and node.nodes:
            for seq in node.nodes:
                if hasattr(seq, "nodes") and len(seq.nodes) >= 2:
                    op = seq.nodes[0]
                    val = seq.nodes[1].to_py()
                    if hasattr(op, "nodes") and op.nodes:
                        if op.nodes[0] == ":":
                            annotation = f": {val}"
                        elif op.nodes[0] == "=":
                            default = f"={val}"
    return f"{name}{annotation}{default}"


@method(param_star)
def to_py(self):
    """param_star: '*' (IDENTIFIER (':' expression)?)?"""
    # SSTAR is visible, nodes[0] is '*'
    result = "*"
    for node in self.nodes[1:]:
        if type(node).__name__ == "Several_Times" and node.nodes:
            for seq in node.nodes:
                if hasattr(seq, "nodes"):
                    # First child is IDENTIFIER
                    result += seq.nodes[0].to_py()
                    # Check for annotation
                    for inner in seq.nodes[1:]:
                        if type(inner).__name__ == "Several_Times" and inner.nodes:
                            for ann in inner.nodes:
                                if hasattr(ann, "nodes") and len(ann.nodes) >= 2:
                                    result += f": {ann.nodes[1].to_py()}"
                elif hasattr(seq, "to_py"):
                    val = seq.to_py()
                    if val != "*":
                        result += val
    return result


@method(param_dstar)
def to_py(self):
    """param_dstar: '**' IDENTIFIER (':' expression)?"""
    name = self.nodes[0].to_py()
    annotation = ""
    for node in self.nodes[1:]:
        if type(node).__name__ == "Several_Times" and node.nodes:
            for seq in node.nodes:
                if hasattr(seq, "nodes") and len(seq.nodes) >= 2:
                    annotation = f": {seq.nodes[1].to_py()}"
    return f"**{name}{annotation}"


@method(param_slash)
def to_py(self):
    """param_slash: '/'"""
    return "/"


@method(param)
def to_py(self):
    """param: param_dstar | param_star | param_slash | param_plain"""
    return self.nodes[0].to_py()


@method(param_list)
def to_py(self):
    """param_list: param (',' param)* ','?"""
    parts = [self.nodes[0].to_py()]
    for node in self.nodes[1:]:
        if type(node).__name__ == "Several_Times" and node.nodes:
            for seq in node.nodes:
                if hasattr(seq, "nodes") and seq.nodes:
                    parts.append(seq.nodes[0].to_py())
    return ", ".join(parts)


# --- Decorators ---
@method(decorator)
def to_py(self, indent=0):
    """decorator: '@' expression NEWLINE"""
    return f"{_ind(indent)}@{self.nodes[0].to_py()}"


@method(decorators)
def to_py(self, indent=0):
    """decorators: decorator+"""
    lines = []
    for node in self.nodes:
        if hasattr(node, "to_py"):
            try:
                lines.append(node.to_py(indent))
            except TypeError:
                lines.append(_ind(indent) + "@" + node.to_py())
    return "\n".join(lines)


# --- return_annotation ---
@method(return_annotation)
def to_py(self):
    """return_annotation: '->' expression"""
    # V_ARROW is visible, so nodes = [V_ARROW, expression]
    return f" -> {self.nodes[1].to_py()}"


# --- Function definition ---
@method(func_def)
def to_py(self, indent=0):
    """func_def: decorators? 'def' IDENTIFIER '(' param_list? ')' ('->' expr)? ':' block"""
    # Walk through nodes: decorators(optional), name, params(optional), annotation(optional), block
    decos = ""
    name = ""
    params = ""
    ret_ann = ""
    body = ""

    for node in self.nodes:
        tname = type(node).__name__
        if tname == "decorators":
            decos = node.to_py(indent) + "\n"
        elif tname == "Several_Times":
            for seq in node.nodes:
                stname = type(seq).__name__
                if stname == "decorators":
                    decos = seq.to_py(indent) + "\n"
                elif stname == "decorator":
                    decos += seq.to_py(indent) + "\n"
                elif stname == "param_list":
                    params = seq.to_py()
                elif stname == "return_annotation":
                    ret_ann = seq.to_py()
                elif stname in (
                    "param_plain",
                    "param_star",
                    "param_dstar",
                    "param_slash",
                ):
                    params = seq.to_py()
        elif tname == "IDENTIFIER":
            name = node.to_py()
        elif tname == "block":
            body = node.to_py(indent + 1)
        elif tname == "param_list":
            params = node.to_py()
        elif tname == "return_annotation":
            ret_ann = node.to_py()

    return f"{decos}{_ind(indent)}def {name}({params}){ret_ann}:\n{body}"


@method(async_func_def)
def to_py(self, indent=0):
    """async_func_def: decorators? 'async' 'def' IDENTIFIER '(' params? ')' ('->' expr)? ':' block"""
    decos = ""
    name = ""
    params = ""
    ret_ann = ""
    body = ""

    for node in self.nodes:
        tname = type(node).__name__
        if tname == "decorators":
            decos = node.to_py(indent) + "\n"
        elif tname == "Several_Times":
            for seq in node.nodes:
                stname = type(seq).__name__
                if stname == "decorators":
                    decos = seq.to_py(indent) + "\n"
                elif stname == "decorator":
                    decos += seq.to_py(indent) + "\n"
                elif stname == "param_list":
                    params = seq.to_py()
                elif stname == "return_annotation":
                    ret_ann = seq.to_py()
                elif stname in (
                    "param_plain",
                    "param_star",
                    "param_dstar",
                    "param_slash",
                ):
                    params = seq.to_py()
        elif tname == "IDENTIFIER":
            name = node.to_py()
        elif tname == "block":
            body = node.to_py(indent + 1)
        elif tname == "param_list":
            params = node.to_py()
        elif tname == "return_annotation":
            ret_ann = node.to_py()

    return f"{decos}{_ind(indent)}async def {name}({params}){ret_ann}:\n{body}"


# --- Class definition ---
def _collect_bases(node):
    """Recursively collect base class expressions from flattened class_args nodes."""
    parts = []
    if not hasattr(node, "nodes"):
        return parts
    for child in node.nodes:
        tname = type(child).__name__
        if tname == "Several_Times":
            for inner in child.nodes:
                parts.extend(_collect_bases(inner))
        elif tname == "Sequence_Parser":
            # A sequence may contain expression + Several_Times of more expressions
            for inner in node.nodes:
                parts.extend(_collect_bases(inner))
            break  # Already processed all children of this node
        elif hasattr(child, "to_py"):
            parts.append(child.to_py())
    return parts


@method(class_def)
def to_py(self, indent=0):
    """class_def: decorators? 'class' IDENTIFIER ('(' args ')')? ':' block"""
    decos = ""
    name = ""
    bases = ""
    body = ""

    for node in self.nodes:
        tname = type(node).__name__
        if tname == "decorators":
            decos = node.to_py(indent) + "\n"
        elif tname == "Several_Times":
            for seq in node.nodes:
                stname = type(seq).__name__
                if stname == "decorator":
                    decos += seq.to_py(indent) + "\n"
                elif stname == "decorators":
                    decos = seq.to_py(indent) + "\n"
                else:
                    # class_args content
                    base_parts = _collect_bases(seq)
                    if base_parts:
                        bases = f"({', '.join(base_parts)})"
        elif tname == "IDENTIFIER":
            name = node.to_py()
        elif tname == "block":
            body = node.to_py(indent + 1)

    return f"{decos}{_ind(indent)}class {name}{bases}:\n{body}"


# --- Async for / with ---
@method(async_for_stmt)
def to_py(self, indent=0):
    """async_for_stmt: 'async' 'for' targets 'in' exprs ':' block"""
    target = self.nodes[0].to_py()
    iterable = self.nodes[1].to_py()
    body = self.nodes[2].to_py(indent + 1)
    return f"{_ind(indent)}async for {target} in {iterable}:\n{body}"


@method(async_with_stmt)
def to_py(self, indent=0):
    """async_with_stmt: 'async' 'with' with_item (',' with_item)* ':' block"""
    items = [self.nodes[0].to_py()]
    block_node = None
    for node in self.nodes[1:]:
        if type(node).__name__ == "Several_Times":
            for seq in node.nodes:
                if hasattr(seq, "nodes") and seq.nodes:
                    item = seq.nodes[0]
                    if hasattr(item, "to_py"):
                        items.append(item.to_py())
        elif hasattr(node, "to_py"):
            block_node = node
    body = ""
    if block_node:
        try:
            body = block_node.to_py(indent + 1)
        except TypeError:
            body = _ind(indent + 1) + block_node.to_py()
    return f"{_ind(indent)}async with {', '.join(items)}:\n{body}"


# --- compound_stmt ---
@method(compound_stmt)
def to_py(self, indent=0):
    """compound_stmt: if | while | for | try | with | match | def | class | async..."""
    return self.nodes[0].to_py(indent)


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
    """Parse any statement (simple or compound)."""
    ParserState.reset()
    stream = Input(code)
    result = statement.parse(stream)
    if not result:
        return None
    return result[0]


def parse_module(code):
    """Parse a full module (sequence of statements)."""
    ParserState.reset()
    stream = Input(code)
    stmts = []
    while True:
        # Skip NL tokens between top-level statements
        while True:
            mark = stream.mark()
            tok = stream.get_new_token()
            if not tok or tok.type == tkn.ENDMARKER:
                stream.reset(mark)
                break
            if tok.type == tkn.NL:
                continue
            stream.reset(mark)
            break
        # Try to parse a statement
        result = statement.parse(stream)
        if not result:
            break
        stmts.append(result[0])
    return stmts


###############################################################################
# Tests
###############################################################################

if __name__ == "__main__":
    print("=" * 60)
    print("Python 3.14 Compound Statement Parser Tests")
    print("=" * 60)

    tests = [
        # --- if / elif / else ---
        (
            "if x:\n    pass\n",
            "if x:\n    pass",
        ),
        (
            "if x:\n    y = 1\n",
            "if x:\n    y = 1",
        ),
        (
            "if x:\n    y = 1\n    z = 2\n",
            "if x:\n    y = 1\n    z = 2",
        ),
        (
            "if x:\n    a = 1\nelif y:\n    b = 2\n",
            "if x:\n    a = 1\nelif y:\n    b = 2",
        ),
        (
            "if x:\n    a = 1\nelif y:\n    b = 2\nelse:\n    c = 3\n",
            "if x:\n    a = 1\nelif y:\n    b = 2\nelse:\n    c = 3",
        ),
        # Simple suite (if True: pass) not yet supported — requires block Choice
        # --- while ---
        (
            "while x:\n    pass\n",
            "while x:\n    pass",
        ),
        (
            "while x:\n    y = 1\n    break\n",
            "while x:\n    y = 1\n    break",
        ),
        # --- for ---
        (
            "for x in xs:\n    pass\n",
            "for x in xs:\n    pass",
        ),
        (
            "for i in range:\n    x = i\n",
            "for i in range:\n    x = i",
        ),
        # --- try / except / finally ---
        (
            "try:\n    pass\nexcept:\n    pass\n",
            "try:\n    pass\nexcept:\n    pass",
        ),
        (
            "try:\n    x = 1\nexcept ValueError:\n    pass\n",
            "try:\n    x = 1\nexcept ValueError:\n    pass",
        ),
        (
            "try:\n    x = 1\nexcept ValueError as e:\n    pass\n",
            "try:\n    x = 1\nexcept ValueError as e:\n    pass",
        ),
        (
            "try:\n    x = 1\nfinally:\n    y = 2\n",
            "try:\n    x = 1\nfinally:\n    y = 2",
        ),
        # --- with ---
        (
            "with f():\n    pass\n",
            "with f():\n    pass",
        ),
        (
            "with f() as x:\n    pass\n",
            "with f() as x:\n    pass",
        ),
        # --- def ---
        (
            "def f():\n    pass\n",
            "def f():\n    pass",
        ),
        (
            "def f(a, b):\n    return a\n",
            "def f(a, b):\n    return a",
        ),
        (
            "def f(a, b=1):\n    pass\n",
            "def f(a, b=1):\n    pass",
        ),
        (
            "def f(*args):\n    pass\n",
            "def f(*args):\n    pass",
        ),
        (
            "def f(**kwargs):\n    pass\n",
            "def f(**kwargs):\n    pass",
        ),
        (
            "def f(a, *, b):\n    pass\n",
            "def f(a, *, b):\n    pass",
        ),
        (
            "def f(a, /, b):\n    pass\n",
            "def f(a, /, b):\n    pass",
        ),
        (
            "def f(a: int) -> str:\n    pass\n",
            "def f(a: int) -> str:\n    pass",
        ),
        # --- class ---
        (
            "class Foo:\n    pass\n",
            "class Foo:\n    pass",
        ),
        (
            "class Foo(Bar):\n    pass\n",
            "class Foo(Bar):\n    pass",
        ),
        (
            "class Foo(Bar, Baz):\n    pass\n",
            "class Foo(Bar, Baz):\n    pass",
        ),
        # --- decorator ---
        (
            "@dec\ndef f():\n    pass\n",
            "@dec\ndef f():\n    pass",
        ),
        (
            "@dec\nclass Foo:\n    pass\n",
            "@dec\nclass Foo:\n    pass",
        ),
        # --- async ---
        (
            "async def f():\n    pass\n",
            "async def f():\n    pass",
        ),
        # --- nested ---
        (
            "if x:\n    if y:\n        pass\n",
            "if x:\n    if y:\n        pass",
        ),
        (
            "def f():\n    for x in xs:\n        if x:\n            return x\n",
            "def f():\n    for x in xs:\n        if x:\n            return x",
        ),
        # --- for/while else ---
        (
            "for x in xs:\n    pass\nelse:\n    pass\n",
            "for x in xs:\n    pass\nelse:\n    pass",
        ),
        (
            "while x:\n    pass\nelse:\n    pass\n",
            "while x:\n    pass\nelse:\n    pass",
        ),
        # --- multiple except ---
        (
            "try:\n    pass\nexcept ValueError:\n    pass\nexcept TypeError:\n    pass\n",
            "try:\n    pass\nexcept ValueError:\n    pass\nexcept TypeError:\n    pass",
        ),
        # --- try/except/else/finally ---
        (
            "try:\n    pass\nexcept ValueError:\n    pass\nelse:\n    pass\nfinally:\n    pass\n",
            "try:\n    pass\nexcept ValueError:\n    pass\nelse:\n    pass\nfinally:\n    pass",
        ),
        # --- except* (exception groups) ---
        (
            "try:\n    pass\nexcept* ValueError:\n    pass\n",
            "try:\n    pass\nexcept* ValueError:\n    pass",
        ),
        # --- match / case ---
        (
            "match x:\n    case 1:\n        pass\n",
            "match x:\n    case 1:\n        pass",
        ),
        (
            "match x:\n    case _:\n        pass\n",
            "match x:\n    case _:\n        pass",
        ),
        (
            "match x:\n    case 1:\n        a = 1\n    case 2:\n        b = 2\n",
            "match x:\n    case 1:\n        a = 1\n    case 2:\n        b = 2",
        ),
        (
            "match x:\n    case y if y > 0:\n        pass\n",
            "match x:\n    case y if y > 0:\n        pass",
        ),
        (
            "match x:\n    case 1 | 2:\n        pass\n",
            "match x:\n    case 1 | 2:\n        pass",
        ),
        (
            'match x:\n    case "hello":\n        pass\n',
            'match x:\n    case "hello":\n        pass',
        ),
        (
            "match x:\n    case [1, 2]:\n        pass\n",
            "match x:\n    case [1, 2]:\n        pass",
        ),
        (
            "match x:\n    case Status.OK:\n        pass\n",
            "match x:\n    case Status.OK:\n        pass",
        ),
        (
            "match x:\n    case Point(1, 2):\n        pass\n",
            "match x:\n    case Point(1, 2):\n        pass",
        ),
        (
            "match x:\n    case y as z:\n        pass\n",
            "match x:\n    case y as z:\n        pass",
        ),
        (
            'match x:\n    case {"a": 1}:\n        pass\n',
            'match x:\n    case {"a": 1}:\n        pass',
        ),
        (
            'match x:\n    case {"a": 1, "b": 2}:\n        pass\n',
            'match x:\n    case {"a": 1, "b": 2}:\n        pass',
        ),
    ]

    passed = failed = 0
    for code, expected in tests:
        try:
            result = parse_compound(code)
            if result:
                output = result.to_py()
                if output == expected:
                    print(f"  PASS: {code.splitlines()[0]!r}...")
                    passed += 1
                else:
                    print(f"  MISMATCH: {code.splitlines()[0]!r}...")
                    print(f"    expected: {expected!r}")
                    print(f"    got:      {output!r}")
                    failed += 1
            else:
                print(f"  FAIL: {code.splitlines()[0]!r}... -> parse returned None")
                failed += 1
        except Exception as e:
            print(f"  ERROR: {code.splitlines()[0]!r}... -> {e}")
            import traceback

            traceback.print_exc()
            failed += 1

    print("=" * 60)
    print(f"Results: {passed} passed, {failed} failed")

    # --- parse_module tests ---
    print()
    print("=" * 60)
    print("parse_module Tests")
    print("=" * 60)

    module_tests = [
        # Simple statements only
        (
            "x = 1\ny = 2\n",
            ["x = 1", "y = 2"],
        ),
        # Mixed simple + compound
        (
            "x = 1\nif x:\n    pass\n",
            ["x = 1", "if x:\n    pass"],
        ),
        # Multiple compound
        (
            "def f():\n    pass\nclass Foo:\n    pass\n",
            ["def f():\n    pass", "class Foo:\n    pass"],
        ),
        # Import + function
        (
            "import os\ndef main():\n    return os\n",
            ["import os", "def main():\n    return os"],
        ),
    ]

    mp = mf = 0
    for code, expected_parts in module_tests:
        try:
            stmts = parse_module(code)
            outputs = []
            for s in stmts:
                try:
                    outputs.append(s.to_py())
                except TypeError:
                    outputs.append(s.to_py())
            if outputs == expected_parts:
                print(f"  PASS: {code.splitlines()[0]!r}... ({len(stmts)} stmts)")
                mp += 1
            else:
                print(f"  MISMATCH: {code.splitlines()[0]!r}...")
                print(f"    expected: {expected_parts!r}")
                print(f"    got:      {outputs!r}")
                mf += 1
        except Exception as e:
            print(f"  ERROR: {code.splitlines()[0]!r}... -> {e}")
            import traceback

            traceback.print_exc()
            mf += 1

    print("=" * 60)
    print(f"Results: {mp} passed, {mf} failed")
