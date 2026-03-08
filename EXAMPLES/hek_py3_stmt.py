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

import sys
sys.path.insert(0, "..")

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
from hek_py3_expr import *  # noqa: F403 — need all fw() names in namespace
from hek_py3_expr import _get_bracket_start
from hek_py_declarations import type_annotation

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
simple_stmt = fw("simple_stmt")
stmt_line = fw("stmt_line")

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
assign_stmt = star_expressions + (V_EQUAL + star_expressions)[1:]

# --- Augmented assignment ---
# aug_assign: target augop expressions
aug_assign_stmt = star_expressions + augop + expressions

# --- Annotated assignment ---
# ann_assign: IDENTIFIER ':' type_annotation ['=' expression]
ann_assign_stmt = IDENTIFIER + V_COLON + type_annotation + (V_EQUAL + expression)[:]

# --- return ---
return_val = ikw("return") + expressions
return_bare = literal("return")
return_stmt = return_val | return_bare

# --- pass / break / continue ---
pass_stmt = literal("pass")
break_stmt = literal("break")
continue_stmt = literal("continue")

# --- del ---
del_stmt = ikw("del") + star_expressions

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

# --- type alias (3.12+) ---
# type_alias_params: [T] or [T, U] etc. (generic type parameters)
type_alias_params = LBRACKET + IDENTIFIER + (COMMA + IDENTIFIER)[:] + RBRACKET
type_stmt = ikw("type") + IDENTIFIER + type_alias_params[:] + V_EQUAL + expression

# --- simple_stmt: choice of all statement types ---
# Ordering matters: try more specific forms before general expression.
# aug_assign before assign (both start with expr, but augop is distinctive).
# ann_assign before assign (starts with IDENTIFIER + ':').
# expressions is the fallback (expression statement).
simple_stmt = (
    ann_assign_stmt
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
# to_py() methods
###############################################################################


# --- augop ---
@method(augop)
def to_py(self):
    """augop: '+=' | '-=' | '*=' | '/=' | '//=' | '%=' | '**='
    | '@=' | '<<=' | '>>=' | '&=' | '|=' | '^='"""
    return self.nodes[0].to_py()


# --- visible tokens ---
@method(V_EQUAL)
def to_py(self):
    """V_EQUAL: '='"""
    return "="


@method(V_COLON)
def to_py(self):
    """V_COLON: ':'"""
    return ":"


@method(V_DOT)
def to_py(self):
    """V_DOT: '.'"""
    return "."


# --- assignment ---
@method(assign_stmt)
def to_py(self):
    """assign_stmt: star_expressions ('=' star_expressions)+"""
    # nodes: [target1, Several_Times[(=, target2), (=, target3), ...]]
    # The last (=, expr) pair is the value; everything before is a target.
    parts = [self.nodes[0].to_py()]
    for node in self.nodes[1:]:
        if not hasattr(node, "nodes") or not node.nodes:
            continue
        for seq in node.nodes:
            if hasattr(seq, "nodes") and len(seq.nodes) >= 2:
                parts.append(seq.nodes[1].to_py())
    return " = ".join(parts)


# --- augmented assignment ---
@method(aug_assign_stmt)
def to_py(self):
    """aug_assign_stmt: star_expressions augop expressions"""
    target = self.nodes[0].to_py()
    # augop is an Fmap whose nodes[0] is a plain string like '+='
    op_node = self.nodes[1]
    op = (
        op_node.nodes[0]
        if isinstance(op_node.nodes[0], str)
        else op_node.nodes[0].to_py()
    )
    value = self.nodes[2].to_py()
    return f"{target} {op} {value}"


# --- annotated assignment ---
@method(ann_assign_stmt)
def to_py(self):
    """ann_assign_stmt: IDENTIFIER ':' expression ('=' expression)?"""
    name = self.nodes[0].to_py()
    # nodes[1] is V_COLON, nodes[2] is the type annotation
    annotation = self.nodes[2].to_py()
    result = f"{name}: {annotation}"
    # Check for optional '= value' part
    for node in self.nodes[3:]:
        if not hasattr(node, "nodes") or not node.nodes:
            continue
        for seq in node.nodes:
            if hasattr(seq, "nodes") and len(seq.nodes) >= 2:
                value = seq.nodes[1].to_py()
                result += f" = {value}"
    return result


# --- return ---
@method(return_val)
def to_py(self):
    """return_val: 'return' expressions"""
    return f"return {self.nodes[0].to_py()}"


@method(return_bare)
def to_py(self):
    """return_bare: 'return'"""
    return "return"


@method(return_stmt)
def to_py(self):
    """return_stmt: return_val | return_bare"""
    return self.nodes[0].to_py()


# --- pass / break / continue ---
@method(pass_stmt)
def to_py(self):
    """pass_stmt: 'pass'"""
    return "pass"


@method(break_stmt)
def to_py(self):
    """break_stmt: 'break'"""
    return "break"


@method(continue_stmt)
def to_py(self):
    """continue_stmt: 'continue'"""
    return "continue"


# --- del ---
@method(del_stmt)
def to_py(self):
    """del_stmt: 'del' star_expressions"""
    return f"del {self.nodes[0].to_py()}"


# --- assert ---
@method(assert_msg)
def to_py(self):
    """assert_msg: 'assert' expression ',' expression"""
    return f"assert {self.nodes[0].to_py()}, {self.nodes[1].to_py()}"


@method(assert_simple)
def to_py(self):
    """assert_simple: 'assert' expression"""
    return f"assert {self.nodes[0].to_py()}"


@method(assert_stmt)
def to_py(self):
    """assert_stmt: assert_msg | assert_simple"""
    return self.nodes[0].to_py()


# --- raise ---
@method(raise_from)
def to_py(self):
    """raise_from: 'raise' expression 'from' expression"""
    return f"raise {self.nodes[0].to_py()} from {self.nodes[1].to_py()}"


@method(raise_exc)
def to_py(self):
    """raise_exc: 'raise' expression"""
    return f"raise {self.nodes[0].to_py()}"


@method(raise_bare)
def to_py(self):
    """raise_bare: 'raise'"""
    return "raise"


@method(raise_stmt)
def to_py(self):
    """raise_stmt: raise_from | raise_exc | raise_bare"""
    return self.nodes[0].to_py()


# --- global / nonlocal ---
@method(global_stmt)
def to_py(self):
    """global_stmt: 'global' IDENTIFIER (',' IDENTIFIER)*"""
    parts = [self.nodes[0].to_py()]
    for node in self.nodes[1:]:
        if not hasattr(node, "nodes") or not node.nodes:
            continue
        for seq in node.nodes:
            if hasattr(seq, "nodes") and len(seq.nodes) >= 1:
                parts.append(seq.nodes[0].to_py())
    return "global " + ", ".join(parts)


@method(nonlocal_stmt)
def to_py(self):
    """nonlocal_stmt: 'nonlocal' IDENTIFIER (',' IDENTIFIER)*"""
    parts = [self.nodes[0].to_py()]
    for node in self.nodes[1:]:
        if not hasattr(node, "nodes") or not node.nodes:
            continue
        for seq in node.nodes:
            if hasattr(seq, "nodes") and len(seq.nodes) >= 1:
                parts.append(seq.nodes[0].to_py())
    return "nonlocal " + ", ".join(parts)


# --- import ---
@method(dotted_name)
def to_py(self):
    """dotted_name: IDENTIFIER ('.' IDENTIFIER)*"""
    parts = [self.nodes[0].to_py()]
    for node in self.nodes[1:]:
        if not hasattr(node, "nodes") or not node.nodes:
            continue
        for seq in node.nodes:
            if hasattr(seq, "nodes") and len(seq.nodes) >= 2:
                # seq is (V_DOT, IDENTIFIER)
                parts.append(seq.nodes[1].to_py())
    return ".".join(parts)


@method(import_as)
def to_py(self):
    """import_as: dotted_name ('as' IDENTIFIER)?

    Flattened: [IDENTIFIER, Several_Times[(V_DOT, IDENT)...maybe (IDENT)]]
    The Several_Times contains BOTH dotted_name tails and the optional 'as' alias.
    Distinguish by checking for V_DOT in each seq.
    """
    parts = [self.nodes[0].to_py()]
    alias = None
    for node in self.nodes[1:]:
        if not hasattr(node, "nodes") or not node.nodes:
            continue
        for seq in node.nodes:
            if not hasattr(seq, "nodes"):
                continue
            # Check if this seq starts with V_DOT -> dotted_name part
            if (
                len(seq.nodes) >= 2
                and hasattr(seq.nodes[0], "nodes")
                and seq.nodes[0].nodes
                and seq.nodes[0].nodes[0] == "."
            ):
                parts.append(seq.nodes[1].to_py())
            elif len(seq.nodes) >= 1:
                # 'as' alias (ikw('as') is ignored, leaving just IDENTIFIER)
                alias = seq.nodes[0].to_py()
    name = ".".join(parts)
    if alias:
        return f"{name} as {alias}"
    return name


@method(import_stmt)
def to_py(self):
    """import_stmt: 'import' import_as (',' import_as)*"""
    parts = [self.nodes[0].to_py()]
    for node in self.nodes[1:]:
        if not hasattr(node, "nodes") or not node.nodes:
            continue
        for seq in node.nodes:
            if hasattr(seq, "nodes") and len(seq.nodes) >= 1:
                parts.append(seq.nodes[0].to_py())
    return "import " + ", ".join(parts)


# --- from ... import ---
@method(import_name)
def to_py(self):
    """import_name: IDENTIFIER ('as' IDENTIFIER)?"""
    name = self.nodes[0].to_py()
    for node in self.nodes[1:]:
        if not hasattr(node, "nodes") or not node.nodes:
            continue
        for seq in node.nodes:
            if hasattr(seq, "nodes") and len(seq.nodes) >= 1:
                alias = seq.nodes[0].to_py()
                return f"{name} as {alias}"
    return name


@method(import_star)
def to_py(self):
    """import_star: '*'"""
    return "*"


@method(import_names_paren)
def to_py(self):
    """import_names_paren with NL support."""
    from hek_tokenize import get_multiline_brackets
    pos = _get_bracket_start(self.nodes[0])
    ml = get_multiline_brackets()
    if pos and pos in ml:
        return ml[pos]

    def _find_import_names(node):
        names = []
        if node is None:
            return names
        if type(node).__name__ == 'import_name':
            names.append(node.to_py())
        elif hasattr(node, 'nodes') and node.nodes:
            for child in node.nodes:
                names.extend(_find_import_names(child))
        return names

    parts = _find_import_names(self)
    return '(' + ', '.join(parts) + ')'

@method(import_names)
def to_py(self):
    """import_names: import_name (',' import_name)* | '*'"""
    # If it's a star import, nodes[0] is import_star
    first = self.nodes[0].to_py()
    if first == "*":
        return "*"
    parts = [first]
    for node in self.nodes[1:]:
        if not hasattr(node, "nodes") or not node.nodes:
            continue
        for seq in node.nodes:
            if hasattr(seq, "nodes") and len(seq.nodes) >= 1:
                parts.append(seq.nodes[0].to_py())
    return ", ".join(parts)


def _dots_to_py(nodes):
    """Extract leading dots from Several_Times of V_DOT nodes."""
    dots = ""
    for node in nodes:
        if hasattr(node, "nodes"):
            for sub in node.nodes:
                if hasattr(sub, "nodes") and sub.nodes and sub.nodes[0] == ".":
                    dots += "."
    return dots


def _import_name_to_py(nodes):
    """Render one import_name from a list of flattened nodes.

    An import_name is IDENTIFIER optionally followed by 'as' IDENTIFIER.
    After flattening: [IDENTIFIER, optional Several_Times[(IDENTIFIER)]]
    where the Several_Times holds the alias (ikw('as') was ignored).
    """
    name = nodes[0].to_py()
    for nd in nodes[1:]:
        if type(nd).__name__ == "Several_Times" and nd.nodes:
            seq = nd.nodes[0]
            if hasattr(seq, "nodes") and seq.nodes:
                child = seq.nodes[0]
                # If child is a raw IDENTIFIER (not import_name), it's an 'as' alias
                if type(child).__name__ == "IDENTIFIER":
                    name += f" as {child.to_py()}"
    return name


def _import_names_to_py(node):
    """Render import_names from a possibly flattened node.

    Flattened structure for import_names = import_name (',' import_name)* | '*':
      - '*': SSTAR(nodes=['*'])
      - 'path': [IDENTIFIER('path')]
      - 'path as p': [IDENTIFIER('path'), Several_Times[(IDENTIFIER('p'))]]
      - 'path, getcwd': [IDENTIFIER('path'), Several_Times[(import_name)]]
      - 'a as b, c as d': [IDENT('a'), ST[(IDENT('b'))], ST[(import_name('c','d'))]]

    The first Several_Times whose child wraps a raw IDENTIFIER is an 'as' alias.
    A Several_Times whose child wraps an import_name is a comma-separated next name.
    """
    if not hasattr(node, "nodes"):
        return str(node)
    # Check for parenthesized import (node itself is import_names_paren)
    if type(node).__name__ == "import_names_paren":
        return node.to_py()
    # Check for star import
    first = node.nodes[0]
    if first == "*" or (
        hasattr(first, "nodes") and first.nodes and first.nodes[0] == "*"
    ):
        return "*"

    # Collect import name parts
    # First import_name is built from leading nodes until we hit a comma-sep Several_Times
    first_name_nodes = [first]
    parts = []
    for nd in node.nodes[1:]:
        if type(nd).__name__ == "Several_Times" and nd.nodes:
            # Several_Times may contain multiple comma-separated items
            for seq in nd.nodes:
                if hasattr(seq, "nodes") and seq.nodes:
                    child = seq.nodes[0]
                    if type(child).__name__ == "import_name":
                        # Comma-separated: finish the first name, add this one
                        if not parts:
                            parts.append(_import_name_to_py(first_name_nodes))
                        parts.append(child.to_py())
                    elif type(child).__name__ == "IDENTIFIER":
                        # 'as' alias for the current first name
                        first_name_nodes.append(nd)
                        break  # only one alias per Several_Times
                    else:
                        first_name_nodes.append(nd)
                        break
        else:
            first_name_nodes.append(nd)

    if not parts:
        parts.append(_import_name_to_py(first_name_nodes))
    return ", ".join(parts)


@method(from_rel_name)
def to_py(self):
    """from_rel_name: 'from' '.'+ dotted_name 'import' import_names"""
    # nodes: [Several_Times(dots), dotted_name, import_names]
    # But flattening may merge dotted_name into the node list.
    # Find dots first, then dotted_name, then import_names.
    dots = ""
    remaining = []
    for node in self.nodes:
        if type(node).__name__ == "Several_Times":
            # Check if this is dots or import_names parts
            for sub in node.nodes:
                if hasattr(sub, "nodes") and sub.nodes and sub.nodes[0] == ".":
                    dots += "."
                else:
                    remaining.append(sub)
        else:
            remaining.append(node)
    # remaining should be [dotted_name_parts..., import_names_parts...]
    # dotted_name starts with IDENTIFIER
    source = remaining[0].to_py() if remaining else ""
    names = (
        _import_names_to_py(remaining[-1])
        if len(remaining) > 1
        else remaining[0].to_py()
        if remaining
        else ""
    )
    return f"from {dots}{source} import {names}"


@method(from_rel_bare)
def to_py(self):
    """from_rel_bare: 'from' '.'+ 'import' import_names"""
    # nodes: [Several_Times(dots), import_names]
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
    names = _import_names_to_py(names_node) if names_node else ""
    return f"from {dots} import {names}"


@method(from_abs)
def to_py(self):
    """from_abs: 'from' dotted_name 'import' import_names

    Flattened nodes: dotted_name may flatten to [IDENTIFIER, Several_Times...]
    followed by import_names nodes. The dotted_name part is nodes[0] (an IDENTIFIER);
    its dot-separated tails and the import_names are in subsequent nodes.
    For simple cases (single-segment source): [dotted_name, import_names_node].
    """
    # Build source from dotted_name (nodes[0] + any V_DOT Several_Times)
    source_parts = [self.nodes[0].to_py()]
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
                    # Part of dotted_name: (V_DOT, IDENTIFIER)
                    source_parts.append(seq.nodes[1].to_py())
                    names_start = i + 1
                    continue
        break
    source = ".".join(source_parts)
    # Remaining nodes form import_names
    if names_start < len(self.nodes):
        names_node = self.nodes[names_start]
        # Wrap remaining nodes if needed
        if names_start + 1 < len(self.nodes):
            # Multiple remaining nodes — create a mock to pass to _import_names_to_py
            class _Mock:
                pass

            mock = _Mock()
            mock.nodes = self.nodes[names_start:]
            names = _import_names_to_py(mock)
        else:
            names = _import_names_to_py(names_node)
    else:
        names = ""
    return f"from {source} import {names}"


@method(from_stmt)
def to_py(self):
    """from_stmt: from_rel_name | from_rel_bare | from_abs"""
    return self.nodes[0].to_py()


# --- type alias ---
@method(type_alias_params)
def to_py(self):
    """type_alias_params: '[' IDENTIFIER (',' IDENTIFIER)* ']'"""
    parts = [self.nodes[0].to_py()]
    for node in self.nodes[1:]:
        if not hasattr(node, 'nodes') or not node.nodes:
            continue
        for seq in node.nodes:
            if hasattr(seq, 'nodes') and len(seq.nodes) >= 1:
                parts.append(seq.nodes[0].to_py())
    return f"[{', '.join(parts)}]"

@method(type_stmt)
def to_py(self):
    """type_stmt: 'type' IDENTIFIER type_alias_params? '=' expression"""
    # nodes: [IDENTIFIER, type_alias_params (optional), V_EQUAL, expression]
    name = self.nodes[0].to_py()
    # Check for type_alias_params
    params = ""
    eq_idx = 1
    for i, node in enumerate(self.nodes[1:], 1):
        if type(node).__name__ == 'type_alias_params':
            params = node.to_py()
            eq_idx = i + 1
            break
        elif hasattr(node, 'nodes') and node.nodes:
            # Check if first child is type_alias_params
            first = node.nodes[0] if hasattr(node, 'nodes') else node
            if type(first).__name__ == 'type_alias_params':
                params = first.to_py()
                eq_idx = i + 1
                break
    value = self.nodes[eq_idx + 1].to_py()  # V_EQUAL is at eq_idx, expression at eq_idx+1
    return f"type {name}{params} = {value}"


# --- simple_stmt ---
@method(simple_stmt)
def to_py(self):
    """simple_stmt: ann_assign_stmt | aug_assign_stmt | assign_stmt
    | return_stmt | pass_stmt | break_stmt | continue_stmt
    | del_stmt | assert_stmt | raise_stmt
    | global_stmt | nonlocal_stmt
    | import_stmt | from_stmt | type_stmt | expr_stmt"""
    return self.nodes[0].to_py()


# --- stmt_line ---
@method(stmt_line)
def to_py(self):
    """stmt_line: simple_stmt (';' simple_stmt)* ';'? NEWLINE"""
    from hek_tokenize import RichNL

    parts = [self.nodes[0].to_py()]
    newline_node = None

    for node in self.nodes[1:]:
        # Check if this node wraps a RichNL (NEWLINE token preserved as node)
        if hasattr(node, 'nodes') and node.nodes:
            inner = node.nodes[0] if len(node.nodes) == 1 else None
            if inner is not None and isinstance(inner, RichNL):
                newline_node = inner
                continue
            # Otherwise it's a Several_Times of semicolon-separated stmts
            for seq in node.nodes:
                if hasattr(seq, "nodes") and len(seq.nodes) >= 1:
                    parts.append(seq.nodes[0].to_py())
        elif isinstance(node, RichNL):
            newline_node = node

    result = "; ".join(parts)
    # Append inline comment if present in the NEWLINE RichNL
    if newline_node is not None and hasattr(newline_node, 'comments') and newline_node.comments:
        for kind, text, ind in newline_node.comments:
            if kind == 'comment':
                result += '  ' + text
    return result


###############################################################################
# Public API
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

if __name__ == "__main__":
    print("=" * 60)
    print("Python 3.14 Simple Statement Parser Tests")
    print("=" * 60)

    tests = [
        # --- Assignment ---
        ("x = 1", "x = 1"),
        ("a = b = 1", "a = b = 1"),
        ("a, b = 1, 2", "a, b = 1, 2"),
        ("x = y = z = 0", "x = y = z = 0"),
        # --- Augmented assignment ---
        ("x += 1", "x += 1"),
        ("x -= 1", "x -= 1"),
        ("x *= 2", "x *= 2"),
        ("x /= 2", "x /= 2"),
        ("x //= 2", "x //= 2"),
        ("x %= 3", "x %= 3"),
        ("x **= 2", "x **= 2"),
        ("x @= m", "x @= m"),
        ("x <<= 1", "x <<= 1"),
        ("x >>= 1", "x >>= 1"),
        ("x &= mask", "x &= mask"),
        ("x |= flag", "x |= flag"),
        ("x ^= bits", "x ^= bits"),
        # --- Annotated assignment ---
        ("x: int", "x: int"),
        ("x: int = 1", "x: int = 1"),
        ("x: str = 'hello'", "x: str = 'hello'"),
        # --- return ---
        ("return", "return"),
        ("return x", "return x"),
        ("return x, y", "return x, y"),
        # --- pass / break / continue ---
        ("pass", "pass"),
        ("break", "break"),
        ("continue", "continue"),
        # --- del ---
        ("del x", "del x"),
        ("del a, b", "del a, b"),
        # --- assert ---
        ("assert x", "assert x"),
        ("assert x, 'msg'", "assert x, 'msg'"),
        # --- raise ---
        ("raise", "raise"),
        ("raise ValueError", "raise ValueError"),
        ("raise ValueError from exc", "raise ValueError from exc"),
        # --- global / nonlocal ---
        ("global x", "global x"),
        ("global x, y", "global x, y"),
        ("nonlocal x", "nonlocal x"),
        ("nonlocal a, b, c", "nonlocal a, b, c"),
        # --- import ---
        ("import os", "import os"),
        ("import os.path", "import os.path"),
        ("import os as o", "import os as o"),
        ("import os, sys", "import os, sys"),
        # --- from import ---
        ("from os import path", "from os import path"),
        ("from os import path as p", "from os import path as p"),
        ("from os import path, getcwd", "from os import path, getcwd"),
        ("from . import foo", "from . import foo"),
        ("from ..pkg import bar", "from ..pkg import bar"),
        ("from os import *", "from os import *"),
        # --- type alias ---
        ("type Vector = list", "type Vector = list"),
        # --- expression statement ---
        ("f(x)", "f(x)"),
        ("x", "x"),
        ("1 + 2", "1 + 2"),
    ]

    passed = failed = 0
    for code, expected in tests:
        try:
            result = parse_stmt(code)
            if result:
                output = result.to_py()
                if output == expected:
                    print(f"  PASS: {code!r} -> {output!r}")
                    passed += 1
                else:
                    print(f"  MISMATCH: {code!r}")
                    print(f"    expected: {expected!r}")
                    print(f"    got:      {output!r}")
                    failed += 1
            else:
                print(f"  FAIL: {code!r} -> parse returned None")
                failed += 1
        except Exception as e:
            print(f"  ERROR: {code!r} -> {e}")
            import traceback

            traceback.print_exc()
            failed += 1

    print("=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
