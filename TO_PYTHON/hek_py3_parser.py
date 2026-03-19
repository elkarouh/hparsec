#!/usr/bin/env python3
"""Python 3.14 Compound Statement Parser — to_py() methods.

Grammar definitions are in py3compound_stmt.py. This module adds to_py() rendering
methods to the grammar node classes.
"""

import sys, os
_dir = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(_dir, ".."))
sys.path.insert(0, os.path.join(_dir, "..", "HPYTHON_GRAMMAR"))

from py3compound_stmt import *  # noqa: F403 — grammar definitions
from hek_tokenize import RichNL
from hek_parsec import method, ParserState
from hek_helpers import INDENT_STR, _ind, _richnl_lines, _block_inline_header_comment, _block_last_stmt
import hek_py3_stmt  # noqa: F401 — registers stmt to_py() methods

###############################################################################
# to_py() methods
###############################################################################


# NL parser node wraps a RichNL; delegate rendering to RichNL.to_py()
@method(NL)
def to_py(self, indent=0):
    """NL: delegate to the wrapped RichNL's rendering."""
    rn = RichNL.extract_from(self)
    return rn.to_py() if rn is not None else ''

@method(block)
def to_py(self, indent=0):
    """block: NEWLINE INDENT NL* (statement NL*)+ DEDENT

    Emits body lines joined by newlines. Blank lines and comments between
    statements (stored as RichNL in the NL[:] Several_Times after each
    statement) are preserved with correct indentation.
    """
    lines = []
    for node in self.nodes:
        tname = type(node).__name__
        if tname == "Fmap":
            continue
        if tname == "Several_Times":
            for seq in node.nodes:
                if type(seq).__name__ == "Sequence_Parser" and hasattr(seq, "nodes"):
                    stmt_node = None
                    nl_several = None
                    for child in seq.nodes:
                        if child is None:
                            continue
                        if type(child).__name__ == "Several_Times":
                            nl_several = child
                        elif stmt_node is None:
                            stmt_node = child
                    # Emit the statement
                    if stmt_node is not None and hasattr(stmt_node, "to_py"):
                        try:
                            lines.append(stmt_node.to_py(indent))
                        except TypeError:
                            raw = stmt_node.to_py()
                            if '\n' in raw:
                                lines.extend(_ind(indent) + ln for ln in raw.split('\n'))
                            else:
                                lines.append(_ind(indent) + raw)
                    # Emit trailing NLs (blank lines / comments) after the statement
                    if nl_several is not None:
                        for nl_node in nl_several.nodes:
                            trivia = _richnl_lines(nl_node)
                            if trivia is not None:
                                lines.extend(trivia)
                else:
                    inner = seq
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
    # Trailing blank lines in a block belong to the inter-statement spacing
    # of the outer scope. We emit them here so callers can decide what to do.
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
    hc = _block_inline_header_comment(self.nodes[1])
    body = self.nodes[1].to_py(indent + 1)
    return f"{_ind(indent)}elif {cond}:{hc}\n{body}"


@method(else_clause)
def to_py(self, indent=0):
    """else_clause: 'else' ':' block"""
    hc = _block_inline_header_comment(self.nodes[0])
    body = self.nodes[0].to_py(indent + 1)
    return f"{_ind(indent)}else:{hc}\n{body}"


@method(if_stmt)
def to_py(self, indent=0):
    """if_stmt: 'if' named_expression ':' block ('elif' ...)* ('else' ...)?"""
    cond = self.nodes[0].to_py()
    hc = _block_inline_header_comment(self.nodes[1])
    body = self.nodes[1].to_py(indent + 1)
    result = f"{_ind(indent)}if {cond}:{hc}\n{body}"
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
    hc = _block_inline_header_comment(self.nodes[1])
    body = self.nodes[1].to_py(indent + 1)
    result = f"{_ind(indent)}while {cond}:{hc}\n{body}"
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
    hc = _block_inline_header_comment(self.nodes[2])
    body = self.nodes[2].to_py(indent + 1)
    result = f"{_ind(indent)}for {target} in {iterable}:{hc}\n{body}"
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
    for node in self.nodes[1:]:
        if type(node).__name__ == "Several_Times" and node.nodes:
            for seq in node.nodes:
                if hasattr(seq, "nodes") and seq.nodes:
                    result += f" as {seq.nodes[0].to_py()}"
            continue
        if hasattr(node, "to_py") and type(node).__name__ == "block":
            hc = _block_inline_header_comment(node)
            try:
                body = node.to_py(indent + 1)
            except TypeError:
                body = _ind(indent + 1) + node.to_py()
            return f"{_ind(indent)}{result}:{hc}\n{body}"
    return f"{_ind(indent)}{result}:"


@method(except_star_clause)
def to_py(self, indent=0):
    """except_star_clause: 'except' '*' expression ('as' IDENTIFIER)? ':' block"""
    exc = self.nodes[1].to_py()
    result = f"except* {exc}"
    for node in self.nodes[2:]:
        if type(node).__name__ == "Several_Times" and node.nodes:
            for seq in node.nodes:
                if hasattr(seq, "nodes") and seq.nodes:
                    result += f" as {seq.nodes[0].to_py()}"
            continue
        if hasattr(node, "to_py") and type(node).__name__ == "block":
            hc = _block_inline_header_comment(node)
            try:
                body = node.to_py(indent + 1)
            except TypeError:
                body = _ind(indent + 1) + node.to_py()
            return f"{_ind(indent)}{result}:{hc}\n{body}"
    return f"{_ind(indent)}{result}:"


@method(except_bare)
def to_py(self, indent=0):
    """except_bare: 'except' ':' block"""
    hc = _block_inline_header_comment(self.nodes[0])
    body = self.nodes[0].to_py(indent + 1)
    return f"{_ind(indent)}except:{hc}\n{body}"


@method(finally_clause)
def to_py(self, indent=0):
    """finally_clause: 'finally' ':' block"""
    hc = _block_inline_header_comment(self.nodes[0])
    body = self.nodes[0].to_py(indent + 1)
    return f"{_ind(indent)}finally:{hc}\n{body}"


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
    hc = _block_inline_header_comment(self.nodes[0])
    body = self.nodes[0].to_py(indent + 1)
    result = f"{_ind(indent)}try:{hc}\n{body}"
    try:
        result += "\n" + self.nodes[1].to_py(indent)
    except TypeError:
        result += "\n" + _ind(indent) + self.nodes[1].to_py()
    clauses = _extract_clauses(self.nodes[2:], indent)
    for c in clauses:
        result += "\n" + c
    return result


@method(try_finally)
def to_py(self, indent=0):
    """try_finally: 'try' ':' block 'finally' ':' block"""
    hc = _block_inline_header_comment(self.nodes[0])
    body = self.nodes[0].to_py(indent + 1)
    fin = self.nodes[1].to_py(indent)
    return f"{_ind(indent)}try:{hc}\n{body}\n{fin}"


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
    hc = ""
    if block_node:
        hc = _block_inline_header_comment(block_node)
        try:
            body = block_node.to_py(indent + 1)
        except TypeError:
            body = _ind(indent + 1) + block_node.to_py()
    return f"{_ind(indent)}with {', '.join(items)}:{hc}\n{body}"


@method(with_stmt_paren)
def to_py(self, indent=0):
    """with_stmt_paren: 'with' '(' NL* with_item (',' NL* with_item)* ','? NL* ')' ':' block"""
    items = []
    block_node = None
    for node in self.nodes:
        tname = type(node).__name__
        if tname == "with_item":
            items.append(node.to_py())
        elif tname == "Several_Times":
            for seq in node.nodes:
                sname = type(seq).__name__
                if sname == "Sequence_Parser":
                    # (COMMA + NL[:] + with_item) sequence
                    for child in seq.nodes:
                        if type(child).__name__ == "with_item":
                            items.append(child.to_py())
                elif sname == "with_item":
                    items.append(seq.to_py())
        elif tname == "block":
            block_node = node
    body = ""
    hc = ""
    if block_node:
        hc = _block_inline_header_comment(block_node)
        try:
            body = block_node.to_py(indent + 1)
        except TypeError:
            body = _ind(indent + 1) + block_node.to_py()
    ind1 = _ind(indent + 1)
    items_str = (",\n" + ind1).join(items)
    return f"{_ind(indent)}with (\n{ind1}{items_str},\n{_ind(indent)}):{hc}\n{body}"


# --- case / when ---
@method(pattern_literal)
def to_py(self):
    """pattern_literal: NUMBER | STRING | 'None' | 'True' | 'False'"""
    return (
        self.nodes[0].to_py() if hasattr(self.nodes[0], "to_py") else str(self.nodes[0])
    )


@method(pattern_capture)
def to_py(self, prec=None):
    """pattern_capture: IDENTIFIER"""
    name = (
        self.nodes[0].to_py() if hasattr(self.nodes[0], "to_py") else str(self.nodes[0])
    )
    # Resolve tick attributes: Type__tick__First -> first value of subrange/enum
    if "__tick__" in name:
        type_name, _, attr = name.partition("__tick__")
        info = ParserState.tick_types.get(type_name)
        if info and attr in info:
            return str(info[attr])
    return name


@method(pattern_wildcard)
def to_py(self):
    """pattern_wildcard: '_'"""
    return "_"


@method(pattern_others)
def to_py(self):
    """pattern_others: 'others' (default branch) -> Nim: 'else'"""
    return "_"


@method(pattern_range)
def to_py(self):
    """pattern_range: expression '..' expression (range pattern) -> Nim: 'lo .. hi'"""
    lo = self.nodes[0].to_py()
    hi = self.nodes[-1].to_py()
    return f"{lo} .. {hi}"


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


@method(keyword_pattern)
def to_py(self):
    """keyword_pattern: IDENTIFIER '=' pattern"""
    return f"{self.nodes[0].to_py()}={self.nodes[1].to_py()}"


@method(pattern_class_arg)
def to_py(self):
    """pattern_class_arg: keyword_pattern | pattern"""
    return self.nodes[0].to_py()


@method(pattern_class)
def to_py(self):
    """pattern_class: IDENTIFIER '(' (pattern_class_arg (',' pattern_class_arg)*)? ')'"""
    name = self.nodes[0].to_py()
    patterns = []
    for node in self.nodes[1:]:
        if type(node).__name__ == "Several_Times" and node.nodes:
            for seq in node.nodes:
                if hasattr(seq, "nodes"):
                    # seq is Sequence_Parser: [pattern_class_arg, Several_Times[(,pattern_class_arg)...]]
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


@method(when_clause)
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
    hc = _block_inline_header_comment(block_node) if block_node else ""
    body = ""
    if block_node:
        try:
            body = block_node.to_py(indent + 1)
        except TypeError:
            body = _ind(indent + 1) + block_node.to_py()
    return f"{_ind(indent)}case {pat}{guard}:{hc}\n{body}"


@method(case_stmt)
def to_py(self, indent=0):
    """match_stmt: 'match' expression ':' NEWLINE INDENT (case_clause)+ DEDENT"""
    subject = self.nodes[0].to_py()
    result = f"{_ind(indent)}match {subject}:"
    # Case clauses are in the Several_Times node.
    # Each case is a Sequence_Parser [pattern, block] or [pattern, Several_Times(guard), block]
    # due to case_clause being flattened.
    for node in self.nodes[1:]:
        tname = type(node).__name__
        if tname == "when_clause":
            result += "\n" + node.to_py(indent + 1)
        elif tname == "Several_Times":
            for seq in node.nodes:
                stname = type(seq).__name__
                if stname == "when_clause":
                    result += "\n" + seq.to_py(indent + 1)
                elif stname == "Sequence_Parser" and hasattr(seq, "nodes"):
                    result += "\n" + _case_from_seq(seq, indent + 1)
    return result


def _case_from_seq(seq, indent):
    """Reconstruct a case clause from a flattened Sequence_Parser [pattern, guard?, block]."""
    pat = ""
    guard = ""
    block_node = None
    for child in seq.nodes:
        tname = type(child).__name__
        if tname == "block":
            block_node = child
        elif tname == "Several_Times":
            for inner in child.nodes:
                if hasattr(inner, "to_py"):
                    guard = inner.to_py()
        elif tname == "case_guard":
            guard = child.to_py()
        else:
            pat = child.to_py()
    hc = _block_inline_header_comment(block_node) if block_node else ""
    body = block_node.to_py(indent + 1) if block_node else ""
    return f"{_ind(indent)}case {pat}{guard}:{hc}\n{body}"


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
                if not hasattr(seq, "nodes") or len(seq.nodes) < 2:
                    continue
                # seq.nodes[0] is the visible op (V_COLON or V_EQUAL), nodes[1] is the value
                op_node = seq.nodes[0]
                val_node = seq.nodes[1]
                # Get the operator string
                op_str = ""
                if hasattr(op_node, "node"):
                    op_str = op_node.node
                elif hasattr(op_node, "nodes") and op_node.nodes:
                    op_str = op_node.nodes[0] if isinstance(op_node.nodes[0], str) else ""
                if op_str == ":":
                    annotation = f": {val_node.to_py()}"
                elif op_str == "=":
                    default = f"={val_node.to_py()}"
    # PEP 8: spaces around = when annotation present
    if annotation and default:
        default = " " + default[0] + " " + default[1:]  # "=val" -> "= val"
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
    decorator=self.nodes[0].to_py()
    if decorator == 'virtual':
        return ''
    return f"{_ind(indent)}@{decorator}"


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
    decos = ""
    name = ""
    params = ""
    ret_ann = ""
    body = ""
    block_node = None

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
            block_node = node
        elif tname == "param_list":
            params = node.to_py()
        elif tname == "return_annotation":
            ret_ann = node.to_py()

    hc = _block_inline_header_comment(block_node) if block_node else ""
    body = block_node.to_py(indent + 1) if block_node else ""
    # Implicit return: if last statement is a bare expression, add return
    # Skip for -> None functions (they don't return a value)
    last_stmt = _block_last_stmt(block_node)
    is_none_return = ret_ann.strip().endswith("None")
    if ret_ann and not is_none_return and last_stmt and type(last_stmt.nodes[0]).__name__ == "expressions":
        body = body.rstrip("\n")
        # Find the last non-comment, non-blank line to prepend return
        lines = body.split("\n")
        for i in range(len(lines) - 1, -1, -1):
            stripped = lines[i].lstrip()
            if stripped and not stripped.startswith("#"):
                indent_str = lines[i][:len(lines[i])-len(stripped)]
                lines[i] = indent_str + "return " + stripped
                break
        body = "\n".join(lines) + "\n"
    return f"{decos}{_ind(indent)}def {name}({params}){ret_ann}:{hc}\n{body}"


@method(async_func_def)
def to_py(self, indent=0):
    """async_func_def: decorators? 'async' 'def' IDENTIFIER '(' params? ')' ('->' expr)? ':' block"""
    decos = ""
    name = ""
    params = ""
    ret_ann = ""
    block_node = None

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
            block_node = node
        elif tname == "param_list":
            params = node.to_py()
        elif tname == "return_annotation":
            ret_ann = node.to_py()

    hc = _block_inline_header_comment(block_node) if block_node else ""
    body = block_node.to_py(indent + 1) if block_node else ""
    # Implicit return: if last statement is a bare expression, add return
    # Skip for -> None functions (they don't return a value)
    last_stmt = _block_last_stmt(block_node)
    is_none_return = ret_ann.strip().endswith("None")
    if ret_ann and not is_none_return and last_stmt and type(last_stmt.nodes[0]).__name__ == "expressions":
        body = body.rstrip("\n")
        # Find the last non-comment, non-blank line to prepend return
        lines = body.split("\n")
        for i in range(len(lines) - 1, -1, -1):
            stripped = lines[i].lstrip()
            if stripped and not stripped.startswith("#"):
                indent_str = lines[i][:len(lines[i])-len(stripped)]
                lines[i] = indent_str + "return " + stripped
                break
        body = "\n".join(lines) + "\n"
    return f"{decos}{_ind(indent)}async def {name}({params}){ret_ann}:{hc}\n{body}"



# --- Type block forms (tuple, record) ---

def _extract_py_fields(block_node, indent=1):
    """Extract field declarations from a block as Python lines."""
    lines = []
    for node in block_node.nodes:
        tname = type(node).__name__
        if tname in ("Fmap", "Filter"):
            continue
        if tname == "Several_Times":
            for seq in node.nodes:
                if type(seq).__name__ == "Sequence_Parser" and hasattr(seq, "nodes"):
                    for child in seq.nodes:
                        if child is None:
                            continue
                        if hasattr(child, "to_py"):
                            cname = type(child).__name__
                            if cname == "stmt_line":
                                try:
                                    line = child.to_py(indent)
                                except TypeError:
                                    line = _ind(indent) + child.to_py()
                                stripped = line.lstrip()
                                # Strip var/let/const keywords
                                for kw in ("var ", "let ", "const "):
                                    if stripped.startswith(kw):
                                        line = line[:len(line) - len(stripped)] + stripped[len(kw):]
                                        break
                                if line.strip():
                                    lines.append(line)
    return lines


def _extract_variant_fields_py(stmt_nodes, indent):
    """Extract field declarations from variant_when stmt_line nodes for Python."""
    import re as _re
    lines = []
    for seq in stmt_nodes:
        if type(seq).__name__ == "Sequence_Parser" and hasattr(seq, "nodes"):
            for child in seq.nodes:
                if child is None:
                    continue
                cname = type(child).__name__
                if cname in ("ann_assign_stmt", "stmt_line", "Sequence_Parser"):
                    try:
                        line = child.to_py(indent)
                    except TypeError:
                        line = _ind(indent) + child.to_py()
                    stripped = line.lstrip()
                    for kw in ("var ", "let ", "const "):
                        if stripped.startswith(kw):
                            line = line[:len(line) - len(stripped)] + stripped[len(kw):]
                            break
                    if line.strip():
                        lines.append(line)
    return lines


@method(type_block_stmt)
def to_py(self, indent=0):
    """type_block_stmt: 'type' IDENTIFIER discrim_param? type_alias_params? (=|is) (tuple_def|discrim_record_def|record_def)"""
    name = self.nodes[0].to_py()
    params = ""
    discrim_name = None
    discrim_type = None
    rhs = self.nodes[-1]
    for node in self.nodes[1:-1]:
        ntype = type(node).__name__
        if ntype == "type_alias_params":
            params = node.to_py()
        elif ntype == "Several_Times" and hasattr(node, "nodes"):
            for child in node.nodes:
                cn = type(child).__name__
                if cn == "type_alias_params":
                    params = child.to_py()
                elif cn == "Sequence_Parser" and hasattr(child, "nodes"):
                    # discrim_param: (Name : Type) -> [IDENTIFIER, Fmap(:), type_name]
                    idents = [c for c in child.nodes if type(c).__name__ in ("IDENTIFIER", "type_name", "Filter")]
                    if len(idents) >= 2:
                        discrim_name = idents[0].to_py()
                        discrim_type = idents[1].to_py()
    # rhs is Sequence_Parser containing [Literal_keyword, ...]
    keyword = ""
    block_node = None
    variant_case_node = None
    if hasattr(rhs, "nodes"):
        for child in rhs.nodes:
            cname = type(child).__name__
            if cname.startswith("Literal_"):
                keyword = getattr(child, "node", "")
            elif cname == "block":
                block_node = child
            elif cname == "Sequence_Parser":
                # variant_case: [IDENTIFIER(discrim), NL, INDENT, Several_Times(whens), DEDENT]
                has_ident = any(type(c).__name__ == "IDENTIFIER" for c in child.nodes)
                has_st = any(type(c).__name__ == "Several_Times" for c in child.nodes)
                if has_ident and has_st:
                    variant_case_node = child
    if variant_case_node and discrim_name:
        # Discriminated record -> Python @dataclass with all fields flattened
        ParserState.nim_imports.add("from dataclasses import dataclass, field")
        all_fields = []
        # Collect fields from each variant
        whens_node = None
        for child in variant_case_node.nodes:
            if type(child).__name__ == "Several_Times":
                whens_node = child
                break
        if whens_node:
            for when_node in whens_node.nodes:
                fields_node = None
                for child in when_node.nodes:
                    if type(child).__name__ == "Several_Times":
                        fields_node = child
                if fields_node:
                    variant_fields = _extract_variant_fields_py(fields_node.nodes, indent + 1)
                    all_fields.extend(variant_fields)
        result_lines = [f"{_ind(indent)}@dataclass", f"{_ind(indent)}class {name}{params}:"]
        result_lines.append(f"{_ind(indent + 1)}{discrim_name}: {discrim_type}")
        for fld in all_fields:
            # Add default value for variant fields (they may not all be set)
            stripped = fld.strip()
            if "=" not in stripped:
                # Add None default via field(default=None)
                fld = fld + " = None"  # type: ignore
            result_lines.append(fld)
        return "\n".join(result_lines)
    if not block_node:
        block_node = rhs  # fallback
    fields = _extract_py_fields(block_node, indent=indent+1)
    if keyword == "tuple":
        ParserState.nim_imports.add("from typing import NamedTuple")
        lines = [f"{_ind(indent)}class {name}{params}(NamedTuple):"]
        # Register field names for named_tuple_lit constructor emission
        import re as _re
        field_names = []
        for f in fields:
            lines.append(f)
            m = _re.match(r'\s+(\w+)\s*:', f)
            if m:
                field_names.append(m.group(1))
        if field_names:
            from hek_py3_expr import _register_named_tuple
            _register_named_tuple(name, field_names)
        return "\n".join(lines)
    elif keyword == "record":
        ParserState.nim_imports.add("from dataclasses import dataclass")
        lines = [f"{_ind(indent)}@dataclass", f"{_ind(indent)}class {name}{params}:"]
        for f in fields:
            lines.append(f)
        return "\n".join(lines)
    return f"{_ind(indent)}type {name}{params} = {rhs.to_py()}"



# --- Class definition ---
@method(class_def)
def to_py(self, indent=0):
    """class_def: decorators? 'class' IDENTIFIER ('(' arguments? ')')? ':' block"""
    decos = ""
    name = ""
    bases = ""
    type_params = ""
    block_node = None

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
                elif stname == "type_alias_params":
                    type_params = seq.to_py()
                elif stname == "class_args":
                    bases = seq.to_py()
        elif tname == "type_alias_params":
            type_params = node.to_py()
        elif tname == "class_args":
            bases = node.to_py()
        elif tname == "IDENTIFIER":
            name = node.to_py()
        elif tname == "block":
            block_node = node

    # Warn if a tuple type is used directly as a generic parameter
    if bases and "[(" in bases and ")]" in bases:
        import re as _re
        _m = _re.search(r'(\w+)\[\(', bases)
        _parent = _m.group(1) if _m else "Base"
        print(f"WARNING: class {name}({_parent}[(...)]): tuple used as generic parameter "
              f"will fail at runtime.\n"
              f"  Use a type alias instead:  type MyTuple is (int, int)\n"
              f"  Then:  class {name}({_parent}[MyTuple]):", file=sys.stderr)

    hc = _block_inline_header_comment(block_node) if block_node else ""
    body = block_node.to_py(indent + 1) if block_node else ""
    return f"{decos}{_ind(indent)}class {name}{type_params}{bases}:{hc}\n{body}"


@method(class_args)
def to_py(self):
    """class_args: '(' arguments? ')'"""
    # nodes[0] is the Several_Times from arguments[:]
    st = self.nodes[0]
    if hasattr(st, "nodes") and st.nodes:
        # The inner match: st.nodes[0] is the arguments node
        args_node = st.nodes[0]
        return f"({args_node.to_py()})"
    return "()"


# --- Async for / with ---
@method(async_for_stmt)
def to_py(self, indent=0):
    """async_for_stmt: 'async' 'for' targets 'in' exprs ':' block"""
    target = self.nodes[0].to_py()
    iterable = self.nodes[1].to_py()
    hc = _block_inline_header_comment(self.nodes[2])
    body = self.nodes[2].to_py(indent + 1)
    return f"{_ind(indent)}async for {target} in {iterable}:{hc}\n{body}"


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
    hc = ""
    if block_node:
        hc = _block_inline_header_comment(block_node)
        try:
            body = block_node.to_py(indent + 1)
        except TypeError:
            body = _ind(indent + 1) + block_node.to_py()
    return f"{_ind(indent)}async with {', '.join(items)}:{hc}\n{body}"


# ---------------------------------------------------------------------------
# Shell statement helpers and to_py()
# ---------------------------------------------------------------------------

def _extract_shell_opts(node):
    """Walk a shell_opts Several_Times node, returning a {key: value_str} dict.

    shell_opt grammar: IDENTIFIER iop("=") expression
    Terminal nodes (STRING, NUMBER, IDENTIFIER) all store their string value in
    .node regardless of what @method() renamed their class to.  We therefore
    match terminals by isinstance(node.node, str) rather than by class name,
    which is stable across decorator renames.
    """
    opts = {}

    def _find_str_value(n):
        """Return the first plain-string .node value found depth-first.

        Skips IDENTIFIER-valued nodes whose string is a keyword or option-name
        to avoid returning the key instead of the value.
        """
        val = getattr(n, "node", None)
        if isinstance(val, str):
            return val
        if hasattr(n, "nodes"):
            for c in n.nodes:
                if c is not None:
                    r = _find_str_value(c)
                    if r is not None:
                        return r
        return None

    def _walk(n):
        if n is None:
            return
        # A shell_opt Sequence_Parser: first child is IDENTIFIER (key), rest is expression.
        # @method(IDENTIFIER) renames the class from "Filter" to "IDENTIFIER", so we
        # match by isidentifier() on the string value rather than the class name.
        if type(n).__name__ == "Sequence_Parser" and hasattr(n, "nodes") and n.nodes:
            first = n.nodes[0]
            first_val = getattr(first, "node", None)
            if isinstance(first_val, str) and first_val.isidentifier():
                for sibling in n.nodes[1:]:
                    val = _find_str_value(sibling)
                    if val is not None:
                        opts[first_val] = val
                        return  # consumed this opt, don't recurse deeper
        if hasattr(n, "nodes"):
            for c in n.nodes:
                _walk(c)

    _walk(node)
    return opts


def _extract_shell_body(body_st):
    """Reconstruct the shell command string from the body Several_Times node.

    Preserves original spacing using token source positions.
    Returns (cmd_str, needs_fstring) where needs_fstring is True when any
    bare '{' or '}' OP token appears (indicating {var} interpolation).
    """
    import tokenize as _tkn
    tokens = []
    for node in body_st.nodes:
        tok = getattr(node, "node", None)
        if tok is not None and hasattr(tok, "string"):
            tokens.append(tok)
    if not tokens:
        return "", False

    parts = []
    for i, tok in enumerate(tokens):
        if i > 0:
            prev = tokens[i - 1]
            gap = tok.start[1] - prev.end[1]
            parts.append(" " * max(gap, 1) if gap >= 1 else "")
        parts.append(tok.string)

    cmd = "".join(parts)
    needs_fstring = any(
        tok.type == _tkn.OP and tok.string in ("{", "}")
        for tok in tokens
    )
    return cmd, needs_fstring


def _parse_shell_stmt(node):
    """Decompose a shell_stmt AST node into its logical parts.

    Returns (target_kw, target_name, kw, opts, cmd, needs_fstring) where:
      target_kw   -- 'let' | 'var' | 'const' | None
      target_name -- str | None
      kw          -- 'shell' | 'shellLines'
      opts        -- dict {str: str}
      cmd         -- reconstructed command string
      needs_fstring -- bool (True when {var} interpolation tokens present)
    """
    nodes = node.nodes

    # Locate the shell keyword node
    kw = None
    kw_idx = -1
    for i, n in enumerate(nodes):
        val = getattr(n, "node", None)
        if isinstance(val, str) and val in ("shell", "shellLines"):
            kw = val
            kw_idx = i
            break

    # Optional assignment target sits before the keyword
    target_kw = target_name = None
    if kw_idx > 0:
        target_st = nodes[0]
        if hasattr(target_st, "nodes") and target_st.nodes:
            seq = target_st.nodes[0]
            if hasattr(seq, "nodes"):
                for n in seq.nodes:
                    val = getattr(n, "node", None)
                    if not isinstance(val, str):
                        continue
                    if val in ("let", "var", "const"):
                        target_kw = val
                    elif val.isidentifier() and val not in ("let", "var", "const", "="):
                        # IDENTIFIER node: @method(IDENTIFIER) renames its class to "IDENTIFIER",
                        # so match by value rather than class name to stay rename-safe.
                        target_name = val

    # Remaining nodes after the keyword: possibly [opts_st, body_st] or [body_st]
    opts = {}
    body_st = None
    for n in nodes[kw_idx + 1 :]:
        if type(n).__name__ != "Several_Times" or not n.nodes:
            continue
        # Body Several_Times: children are Filter nodes wrapping TokenInfo objects
        first = n.nodes[0]
        tok = getattr(first, "node", None)
        if hasattr(tok, "string") and not isinstance(tok, str):
            body_st = n
            break
        # Otherwise it's the opts Several_Times
        opts = _extract_shell_opts(n)

    cmd, needs_fstring = _extract_shell_body(body_st) if body_st else ("", False)
    return target_kw, target_name, kw, opts, cmd, needs_fstring


@method(shell_stmt)
def to_py(self, indent=0):
    """shell_stmt: [decl_keyword IDENTIFIER '='] ('shell'|'shellLines') [shell_opts] ':' cmd+

    Python output:
      import subprocess as _subprocess, types as _types  (auto-inserted at top)

      # shell: cmd
      _subprocess.run(\"\"\"cmd\"\"\", shell=True)

      # let result = shell: cmd
      _r = _subprocess.run(\"\"\"cmd\"\"\", shell=True, capture_output=True, text=True)
      result = _types.SimpleNamespace(output=_r.stdout, stderr=_r.stderr, code=_r.returncode)

      # let lines = shellLines: cmd
      _r = _subprocess.run(\"\"\"cmd\"\"\", shell=True, capture_output=True, text=True)
      lines = _r.stdout.splitlines()

    Variable interpolation: {name} in cmd body -> f\\\"\\\"\\\"...{name}...\\\"\\\"\\\"
    Options: cwd=\"/tmp\" -> cwd=\"/tmp\"; timeout=5000 -> timeout=5.0 (ms -> s)
    """
    ind = _ind(indent)
    target_kw, target_name, kw, opts, cmd, needs_fstring = _parse_shell_stmt(self)

    # Mark that shell imports are needed; py2py.translate() inserts them at top
    ParserState.nim_imports.add("import subprocess as _subprocess")
    if target_name:
        ParserState.nim_imports.add("import types as _types")

    q = '"""'
    cmd_str = f"f{q}{cmd}{q}" if needs_fstring else f"{q}{cmd}{q}"

    run_kwargs = ["shell=True"]
    if target_name:
        run_kwargs += ["capture_output=True", "text=True"]
    if "cwd" in opts:
        run_kwargs.append(f"cwd={opts['cwd']}")
    if "timeout" in opts:
        ms = opts["timeout"]
        try:
            run_kwargs.append(f"timeout={int(ms) / 1000}")
        except ValueError:
            run_kwargs.append(f"timeout={ms} / 1000")

    kwargs_str = ", ".join(run_kwargs)
    lines = []

    if target_name:
        lines.append(f"{ind}_r = _subprocess.run({cmd_str}, {kwargs_str})")
        if kw == "shellLines":
            lines.append(f"{ind}{target_name} = _r.stdout.splitlines()")
        else:
            lines.append(
                f"{ind}{target_name} = _types.SimpleNamespace("
                f"output=_r.stdout, stderr=_r.stderr, code=_r.returncode)"
            )
    else:
        lines.append(f"{ind}_subprocess.run({cmd_str}, {kwargs_str})")

    return "\n".join(lines)


# --- compound_stmt ---
@method(compound_stmt)
def to_py(self, indent=0):
    """compound_stmt: if | while | for | try | with | match | def | class | async... | shell_stmt"""
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
        # --- case / when ---
        (
            "case x:\n    when 1:\n        pass\n",
            "match x:\n    case 1:\n        pass",
        ),
        (
            "case x:\n    when _:\n        pass\n",
            "match x:\n    case _:\n        pass",
        ),
        (
            "case x:\n    when 1:\n        a = 1\n    when 2:\n        b = 2\n",
            "match x:\n    case 1:\n        a = 1\n    case 2:\n        b = 2",
        ),
        (
            "case x:\n    when y if y > 0:\n        pass\n",
            "match x:\n    case y if y > 0:\n        pass",
        ),
        (
            "case x:\n    when 1 | 2:\n        pass\n",
            "match x:\n    case 1 | 2:\n        pass",
        ),
        (
            'case x:\n    when "hello":\n        pass\n',
            'match x:\n    case "hello":\n        pass',
        ),
        (
            "case x:\n    when [1, 2]:\n        pass\n",
            "match x:\n    case [1, 2]:\n        pass",
        ),
        (
            "case x:\n    when Status.OK:\n        pass\n",
            "match x:\n    case Status.OK:\n        pass",
        ),
        (
            "case x:\n    when Point(1, 2):\n        pass\n",
            "match x:\n    case Point(1, 2):\n        pass",
        ),
        (
            "case x:\n    when y as z:\n        pass\n",
            "match x:\n    case y as z:\n        pass",
        ),
        (
            'case x:\n    when {"a": 1}:\n        pass\n',
            'match x:\n    case {"a": 1}:\n        pass',
        ),
        (
            'case x:\n    when {"a": 1, "b": 2}:\n        pass\n',
            'match x:\n    case {"a": 1, "b": 2}:\n        pass',
        ),
        (
            "case x:\n    when others:\n        pass\n",
            "match x:\n    case _:\n        pass",
        ),
        (
            "case x:\n    when 1 .. 5:\n        pass\n",
            "match x:\n    case 1 .. 5:\n        pass",
        ),
        # --- discriminated records ---
        (
            "type Shape (Kind : Shape_Kind) is record:\n    case Kind is\n        when Circle:\n            Radius : float\n        when Rectangle:\n            Width : float\n            Height : float\n",
            "@dataclass\nclass Shape:\n    Kind: Shape_Kind\n    Radius: float = None\n    Width: float = None\n    Height: float = None",
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
