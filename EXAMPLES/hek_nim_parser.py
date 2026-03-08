#!/usr/bin/env python3
"""Nim translation methods for Python 3.14 compound statements.

Adds to_nim() methods to the compound statement parser classes defined in
hek_py3_parser.py. Import this module to enable .to_nim() on compound
statement AST nodes.

Usage:
    from hek_nim_parser import *
    ast = parse_compound("if x:\n    pass\n")
    print(ast.to_nim())  # if x:\n    discard
"""

import sys
sys.path.insert(0, "..")

from hek_parsec import method
from hek_py3_parser import *  # noqa: F403 — need all parser rule names
from hek_py3_parser import (
    _ind, _richnl_lines, _block_inline_header_comment, _extract_clauses,
    _case_from_seq, parse_compound, parse_module,
)
from hek_tokenize import RichNL
import hek_nim_expr  # noqa: F401 — registers expr to_nim()
import hek_nim_stmt  # noqa: F401 — registers stmt to_nim()
import hek_nim_declarations  # noqa: F401 — registers decl to_nim()

###############################################################################
# to_nim() methods for compound statements
###############################################################################


@method(NL)
def to_nim(self, indent=0):
    rn = RichNL.extract_from(self)
    return rn.to_py() if rn is not None else ''


# --- block ---
@method(block)
def to_nim(self, indent=0):
    """Emit body lines calling to_nim() recursively."""
    lines = []
    for node in self.nodes:
        tname = type(node).__name__
        if tname in ("Fmap", "Filter"):
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
                    if stmt_node is not None and hasattr(stmt_node, "to_nim"):
                        try:
                            lines.append(stmt_node.to_nim(indent))
                        except TypeError:
                            lines.append(_ind(indent) + stmt_node.to_nim())
                    if nl_several is not None:
                        for nl_node in nl_several.nodes:
                            trivia = _richnl_lines(nl_node)
                            if trivia is not None:
                                lines.extend(trivia)
                else:
                    inner = seq
                    if inner is not None and hasattr(inner, "to_nim"):
                        try:
                            lines.append(inner.to_nim(indent))
                        except TypeError:
                            lines.append(_ind(indent) + inner.to_nim())
        elif hasattr(node, "to_nim"):
            try:
                lines.append(node.to_nim(indent))
            except TypeError:
                lines.append(_ind(indent) + node.to_nim())
    return "\n".join(lines)


@method(statement)
def to_nim(self, indent=0):
    inner = self.nodes[0]
    try:
        return inner.to_nim(indent)
    except TypeError:
        return _ind(indent) + inner.to_nim()


# --- if / elif / else ---
@method(elif_clause)
def to_nim(self, indent=0):
    cond = self.nodes[0].to_nim()
    hc = _block_inline_header_comment(self.nodes[1])
    body = self.nodes[1].to_nim(indent + 1)
    return f"{_ind(indent)}elif {cond}:{hc}\n{body}"


@method(else_clause)
def to_nim(self, indent=0):
    hc = _block_inline_header_comment(self.nodes[0])
    body = self.nodes[0].to_nim(indent + 1)
    return f"{_ind(indent)}else:{hc}\n{body}"


@method(if_stmt)
def to_nim(self, indent=0):
    cond = self.nodes[0].to_nim()
    hc = _block_inline_header_comment(self.nodes[1])
    body = self.nodes[1].to_nim(indent + 1)
    result = f"{_ind(indent)}if {cond}:{hc}\n{body}"
    for node in self.nodes[2:]:
        if not hasattr(node, "nodes") or not node.nodes:
            continue
        for seq in node.nodes:
            if hasattr(seq, "nodes") and seq.nodes:
                clause = seq.nodes[0] if hasattr(seq.nodes[0], "to_nim") else seq
            else:
                clause = seq
            if hasattr(clause, "to_nim"):
                try:
                    result += "\n" + clause.to_nim(indent)
                except TypeError:
                    result += "\n" + _ind(indent) + clause.to_nim()
    return result


# --- while ---
@method(while_stmt)
def to_nim(self, indent=0):
    cond = self.nodes[0].to_nim()
    hc = _block_inline_header_comment(self.nodes[1])
    body = self.nodes[1].to_nim(indent + 1)
    result = f"{_ind(indent)}while {cond}:{hc}\n{body}"
    # Nim has no while/else — skip else clause
    return result


# --- for ---
@method(for_target)
def to_nim(self):
    parts = [self.nodes[0].to_nim()]
    for node in self.nodes[1:]:
        if type(node).__name__ == "Several_Times" and node.nodes:
            for seq in node.nodes:
                if hasattr(seq, "nodes") and seq.nodes:
                    parts.append(seq.nodes[0].to_nim())
    return ", ".join(parts)


@method(for_stmt)
def to_nim(self, indent=0):
    target = self.nodes[0].to_nim()
    iterable = self.nodes[1].to_nim()
    hc = _block_inline_header_comment(self.nodes[2])
    body = self.nodes[2].to_nim(indent + 1)
    result = f"{_ind(indent)}for {target} in {iterable}:{hc}\n{body}"
    # Nim has no for/else — skip else clause
    return result


# --- try / except / finally ---
@method(except_clause)
def to_nim(self, indent=0):
    exc = self.nodes[0].to_nim()
    result = f"except {exc}"
    for node in self.nodes[1:]:
        if type(node).__name__ == "Several_Times" and node.nodes:
            for seq in node.nodes:
                if hasattr(seq, "nodes") and seq.nodes:
                    result += f" as {seq.nodes[0].to_nim()}"
            continue
        if hasattr(node, "to_nim") and type(node).__name__ == "block":
            hc = _block_inline_header_comment(node)
            try:
                body = node.to_nim(indent + 1)
            except TypeError:
                body = _ind(indent + 1) + node.to_nim()
            return f"{_ind(indent)}{result}:{hc}\n{body}"
    return f"{_ind(indent)}{result}:"


@method(except_star_clause)
def to_nim(self, indent=0):
    exc = self.nodes[1].to_nim()
    result = f"except* {exc}"
    for node in self.nodes[2:]:
        if type(node).__name__ == "Several_Times" and node.nodes:
            for seq in node.nodes:
                if hasattr(seq, "nodes") and seq.nodes:
                    result += f" as {seq.nodes[0].to_nim()}"
            continue
        if hasattr(node, "to_nim") and type(node).__name__ == "block":
            hc = _block_inline_header_comment(node)
            try:
                body = node.to_nim(indent + 1)
            except TypeError:
                body = _ind(indent + 1) + node.to_nim()
            return f"{_ind(indent)}{result}:{hc}\n{body}"
    return f"{_ind(indent)}{result}:"


@method(except_bare)
def to_nim(self, indent=0):
    hc = _block_inline_header_comment(self.nodes[0])
    body = self.nodes[0].to_nim(indent + 1)
    return f"{_ind(indent)}except:{hc}\n{body}"


@method(finally_clause)
def to_nim(self, indent=0):
    hc = _block_inline_header_comment(self.nodes[0])
    body = self.nodes[0].to_nim(indent + 1)
    return f"{_ind(indent)}finally:{hc}\n{body}"


def _extract_clauses_nim(nodes, indent):
    """Extract except/else/finally clauses calling to_nim()."""
    parts = []
    for node in nodes:
        if not hasattr(node, "nodes"):
            if hasattr(node, "to_nim"):
                try:
                    parts.append(node.to_nim(indent))
                except TypeError:
                    parts.append(_ind(indent) + node.to_nim())
            continue
        if type(node).__name__ == "Several_Times":
            for seq in node.nodes:
                if hasattr(seq, "nodes") and seq.nodes:
                    inner = seq.nodes[0] if len(seq.nodes) == 1 else seq
                    if hasattr(inner, "to_nim"):
                        try:
                            parts.append(inner.to_nim(indent))
                        except TypeError:
                            parts.append(_ind(indent) + inner.to_nim())
                elif hasattr(seq, "to_nim"):
                    try:
                        parts.append(seq.to_nim(indent))
                    except TypeError:
                        parts.append(_ind(indent) + seq.to_nim())
        elif hasattr(node, "to_nim"):
            try:
                parts.append(node.to_nim(indent))
            except TypeError:
                parts.append(_ind(indent) + node.to_nim())
    return parts


@method(try_except)
def to_nim(self, indent=0):
    hc = _block_inline_header_comment(self.nodes[0])
    body = self.nodes[0].to_nim(indent + 1)
    result = f"{_ind(indent)}try:{hc}\n{body}"
    try:
        result += "\n" + self.nodes[1].to_nim(indent)
    except TypeError:
        result += "\n" + _ind(indent) + self.nodes[1].to_nim()
    clauses = _extract_clauses_nim(self.nodes[2:], indent)
    for c in clauses:
        result += "\n" + c
    return result


@method(try_finally)
def to_nim(self, indent=0):
    hc = _block_inline_header_comment(self.nodes[0])
    body = self.nodes[0].to_nim(indent + 1)
    fin = self.nodes[1].to_nim(indent)
    return f"{_ind(indent)}try:{hc}\n{body}\n{fin}"


@method(try_stmt)
def to_nim(self, indent=0):
    return self.nodes[0].to_nim(indent)


# --- with ---
@method(with_item)
def to_nim(self):
    expr = self.nodes[0].to_nim()
    for node in self.nodes[1:]:
        if type(node).__name__ == "Several_Times" and node.nodes:
            for seq in node.nodes:
                if hasattr(seq, "nodes") and seq.nodes:
                    return f"{expr} as {seq.nodes[0].to_nim()}"
    return expr


@method(with_stmt)
def to_nim(self, indent=0):
    # Nim has no 'with' — keep Python syntax as best-effort
    items = [self.nodes[0].to_nim()]
    block_node = None
    for node in self.nodes[1:]:
        if type(node).__name__ == "Several_Times":
            for seq in node.nodes:
                if hasattr(seq, "nodes") and seq.nodes:
                    item = seq.nodes[0]
                    if hasattr(item, "to_nim"):
                        items.append(item.to_nim())
        elif hasattr(node, "to_nim"):
            block_node = node
    body = ""
    hc = ""
    if block_node:
        hc = _block_inline_header_comment(block_node)
        try:
            body = block_node.to_nim(indent + 1)
        except TypeError:
            body = _ind(indent + 1) + block_node.to_nim()
    return f"{_ind(indent)}with {', '.join(items)}:{hc}\n{body}"


@method(with_stmt_paren)
def to_nim(self, indent=0):
    items = []
    block_node = None
    for node in self.nodes:
        tname = type(node).__name__
        if tname == "with_item":
            items.append(node.to_nim())
        elif tname == "Several_Times":
            for seq in node.nodes:
                sname = type(seq).__name__
                if sname == "Sequence_Parser":
                    for child in seq.nodes:
                        if type(child).__name__ == "with_item":
                            items.append(child.to_nim())
                elif sname == "with_item":
                    items.append(seq.to_nim())
        elif tname == "block":
            block_node = node
    body = ""
    hc = ""
    if block_node:
        hc = _block_inline_header_comment(block_node)
        try:
            body = block_node.to_nim(indent + 1)
        except TypeError:
            body = _ind(indent + 1) + block_node.to_nim()
    ind1 = _ind(indent + 1)
    items_str = (",\n" + ind1).join(items)
    return f"{_ind(indent)}with (\n{ind1}{items_str},\n{_ind(indent)}):{hc}\n{body}"


# --- match / case -> Nim case statement ---
@method(pattern_literal)
def to_nim(self):
    n = self.nodes[0]
    if hasattr(n, "to_nim"):
        return n.to_nim()
    return str(n)


@method(pattern_capture)
def to_nim(self):
    n = self.nodes[0]
    if hasattr(n, "to_nim"):
        return n.to_nim()
    return str(n)


@method(pattern_wildcard)
def to_nim(self):
    return "_"


@method(pattern_group)
def to_nim(self):
    return f"({self.nodes[0].to_nim()})"


@method(pattern_sequence)
def to_nim(self):
    parts = [self.nodes[0].to_nim()]
    for node in self.nodes[1:]:
        if type(node).__name__ == "Several_Times" and node.nodes:
            for seq in node.nodes:
                if hasattr(seq, "nodes") and seq.nodes:
                    parts.append(seq.nodes[0].to_nim())
    return f"@[{', '.join(parts)}]"


@method(pattern_or)
def to_nim(self):
    parts = [self.nodes[0].to_nim()]
    for node in self.nodes[1:]:
        if type(node).__name__ == "Several_Times" and node.nodes:
            for seq in node.nodes:
                if hasattr(seq, "nodes") and len(seq.nodes) >= 2:
                    parts.append(seq.nodes[1].to_nim())
    return ", ".join(parts)


@method(pattern_value)
def to_nim(self):
    parts = [self.nodes[0].to_nim()]
    for node in self.nodes[1:]:
        if type(node).__name__ == "Several_Times" and node.nodes:
            for seq in node.nodes:
                if hasattr(seq, "nodes") and len(seq.nodes) >= 2:
                    parts.append(seq.nodes[1].to_nim())
    return ".".join(parts)


@method(keyword_pattern)
def to_nim(self):
    return f"{self.nodes[0].to_nim()} = {self.nodes[1].to_nim()}"


@method(pattern_class_arg)
def to_nim(self):
    return self.nodes[0].to_nim()


@method(pattern_class)
def to_nim(self):
    name = self.nodes[0].to_nim()
    patterns = []
    for node in self.nodes[1:]:
        if type(node).__name__ == "Several_Times" and node.nodes:
            for seq in node.nodes:
                if hasattr(seq, "nodes"):
                    patterns.append(seq.nodes[0].to_nim())
                    for inner in seq.nodes[1:]:
                        if type(inner).__name__ == "Several_Times" and inner.nodes:
                            for sub in inner.nodes:
                                if hasattr(sub, "nodes") and sub.nodes:
                                    patterns.append(sub.nodes[0].to_nim())
                elif hasattr(seq, "to_nim"):
                    patterns.append(seq.to_nim())
    return f"{name}({', '.join(patterns)})"


@method(pattern_mapping)
def to_nim(self):
    pairs = []
    def _extract_pair(nodes):
        key = val = None
        for n in nodes:
            tname = type(n).__name__
            if tname == "Fmap" and hasattr(n, "nodes") and n.nodes and n.nodes[0] == ":":
                continue
            elif key is None and hasattr(n, "to_nim"):
                key = n.to_nim()
            elif hasattr(n, "to_nim"):
                val = n.to_nim()
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
    return "{" + ", ".join(pairs) + "}.toTable"


@method(base_pattern)
def to_nim(self):
    return self.nodes[0].to_nim()


@method(pattern_as)
def to_nim(self):
    pat = self.nodes[0].to_nim()
    name = self.nodes[1].to_nim()
    return f"{pat} as {name}"


@method(pattern)
def to_nim(self):
    return self.nodes[0].to_nim()


@method(case_guard)
def to_nim(self):
    return f" if {self.nodes[0].to_nim()}"


@method(case_clause)
def to_nim(self, indent=0):
    pat = self.nodes[0].to_nim()
    guard = ""
    block_node = None
    for node in self.nodes[1:]:
        if type(node).__name__ == "Several_Times" and node.nodes:
            for seq in node.nodes:
                if hasattr(seq, "to_nim"):
                    guard = seq.to_nim()
        elif hasattr(node, "to_nim"):
            block_node = node
    hc = _block_inline_header_comment(block_node) if block_node else ""
    body = ""
    if block_node:
        try:
            body = block_node.to_nim(indent + 1)
        except TypeError:
            body = _ind(indent + 1) + block_node.to_nim()
    return f"{_ind(indent)}of {pat}{guard}:{hc}\n{body}"


@method(match_stmt)
def to_nim(self, indent=0):
    """match -> Nim case statement"""
    subject = self.nodes[0].to_nim()
    result = f"{_ind(indent)}case {subject}:"
    for node in self.nodes[1:]:
        tname = type(node).__name__
        if tname == "case_clause":
            result += "\n" + node.to_nim(indent + 1)
        elif tname == "Several_Times":
            for seq in node.nodes:
                stname = type(seq).__name__
                if stname == "case_clause":
                    result += "\n" + seq.to_nim(indent + 1)
                elif stname == "Sequence_Parser" and hasattr(seq, "nodes"):
                    result += "\n" + _case_from_seq_nim(seq, indent + 1)
    return result


def _case_from_seq_nim(seq, indent):
    pat = ""
    guard = ""
    block_node = None
    for child in seq.nodes:
        tname = type(child).__name__
        if tname == "block":
            block_node = child
        elif tname == "Several_Times":
            for inner in child.nodes:
                if hasattr(inner, "to_nim"):
                    guard = inner.to_nim()
        elif tname == "case_guard":
            guard = child.to_nim()
        else:
            pat = child.to_nim()
    hc = _block_inline_header_comment(block_node) if block_node else ""
    body = block_node.to_nim(indent + 1) if block_node else ""
    return f"{_ind(indent)}of {pat}{guard}:{hc}\n{body}"


# --- Function parameters ---
@method(param_plain)
def to_nim(self):
    """param_plain -> Nim: name: type = default"""
    name = self.nodes[0].to_nim()
    annotation = ""
    default = ""
    for node in self.nodes[1:]:
        if type(node).__name__ == "Several_Times" and node.nodes:
            for seq in node.nodes:
                if not hasattr(seq, "nodes") or len(seq.nodes) < 2:
                    continue
                op_node = seq.nodes[0]
                val_node = seq.nodes[1]
                op_str = ""
                if hasattr(op_node, "node"):
                    op_str = op_node.node
                elif hasattr(op_node, "nodes") and op_node.nodes:
                    op_str = op_node.nodes[0] if isinstance(op_node.nodes[0], str) else ""
                if op_str == ":":
                    annotation = f": {val_node.to_nim()}"
                elif op_str == "=":
                    default = f" = {val_node.to_nim()}"
    if not annotation:
        annotation = ": auto"
    return f"{name}{annotation}{default}"


@method(param_star)
def to_nim(self):
    """*args -> args: varargs[auto]"""
    result = ""
    name = ""
    ann = ""
    for node in self.nodes[1:]:
        if type(node).__name__ == "Several_Times" and node.nodes:
            for seq in node.nodes:
                if hasattr(seq, "nodes"):
                    name = seq.nodes[0].to_nim()
                    for inner in seq.nodes[1:]:
                        if type(inner).__name__ == "Several_Times" and inner.nodes:
                            for a in inner.nodes:
                                if hasattr(a, "nodes") and len(a.nodes) >= 2:
                                    ann = f": varargs[{a.nodes[1].to_nim()}]"
                elif hasattr(seq, "to_nim"):
                    val = seq.to_nim()
                    if val != "*":
                        name = val
    if name:
        if not ann:
            ann = ": varargs[auto]"
        return f"{name}{ann}"
    return ""


@method(param_dstar)
def to_nim(self):
    """**kwargs -> keep as-is (no Nim equivalent)"""
    name = self.nodes[0].to_nim()
    annotation = ""
    for node in self.nodes[1:]:
        if type(node).__name__ == "Several_Times" and node.nodes:
            for seq in node.nodes:
                if hasattr(seq, "nodes") and len(seq.nodes) >= 2:
                    annotation = f": {seq.nodes[1].to_nim()}"
    return f"**{name}{annotation}"


@method(param_slash)
def to_nim(self):
    # Nim has no positional-only separator — omit
    return ""


@method(param)
def to_nim(self):
    return self.nodes[0].to_nim()


@method(param_list)
def to_nim(self):
    parts = []
    p = self.nodes[0].to_nim()
    if p:
        parts.append(p)
    for node in self.nodes[1:]:
        if type(node).__name__ == "Several_Times" and node.nodes:
            for seq in node.nodes:
                if hasattr(seq, "nodes") and seq.nodes:
                    p = seq.nodes[0].to_nim()
                    if p:
                        parts.append(p)
    return ", ".join(parts)


# --- Decorators ---
@method(decorator)
def to_nim(self, indent=0):
    # Nim uses pragmas {.decorator.} — keep @ syntax as best-effort
    return f"{_ind(indent)}@{self.nodes[0].to_nim()}"


@method(decorators)
def to_nim(self, indent=0):
    lines = []
    for node in self.nodes:
        if hasattr(node, "to_nim"):
            try:
                lines.append(node.to_nim(indent))
            except TypeError:
                lines.append(_ind(indent) + "@" + node.to_nim())
    return "\n".join(lines)


# --- return_annotation ---
@method(return_annotation)
def to_nim(self):
    """-> type  becomes  : type  in Nim"""
    return f": {self.nodes[1].to_nim()}"


# --- Function definition ---
@method(func_def)
def to_nim(self, indent=0):
    """def f(a: int) -> str:  ->  proc f(a: int): string ="""
    decos = ""
    name = ""
    params = ""
    ret_ann = ""
    block_node = None

    for node in self.nodes:
        tname = type(node).__name__
        if tname == "decorators":
            decos = node.to_nim(indent) + "\n"
        elif tname == "Several_Times":
            for seq in node.nodes:
                stname = type(seq).__name__
                if stname == "decorators":
                    decos = seq.to_nim(indent) + "\n"
                elif stname == "decorator":
                    decos += seq.to_nim(indent) + "\n"
                elif stname == "param_list":
                    params = seq.to_nim()
                elif stname == "return_annotation":
                    ret_ann = seq.to_nim()
                elif stname in ("param_plain", "param_star", "param_dstar", "param_slash"):
                    params = seq.to_nim()
        elif tname == "IDENTIFIER":
            name = node.to_nim()
        elif tname == "block":
            block_node = node
        elif tname == "param_list":
            params = node.to_nim()
        elif tname == "return_annotation":
            ret_ann = node.to_nim()

    hc = _block_inline_header_comment(block_node) if block_node else ""
    body = block_node.to_nim(indent + 1) if block_node else ""
    return f"{decos}{_ind(indent)}proc {name}({params}){ret_ann} ={hc}\n{body}"


@method(async_func_def)
def to_nim(self, indent=0):
    """async def -> proc {.async.}"""
    decos = ""
    name = ""
    params = ""
    ret_ann = ""
    block_node = None

    for node in self.nodes:
        tname = type(node).__name__
        if tname == "decorators":
            decos = node.to_nim(indent) + "\n"
        elif tname == "Several_Times":
            for seq in node.nodes:
                stname = type(seq).__name__
                if stname == "decorators":
                    decos = seq.to_nim(indent) + "\n"
                elif stname == "decorator":
                    decos += seq.to_nim(indent) + "\n"
                elif stname == "param_list":
                    params = seq.to_nim()
                elif stname == "return_annotation":
                    ret_ann = seq.to_nim()
                elif stname in ("param_plain", "param_star", "param_dstar", "param_slash"):
                    params = seq.to_nim()
        elif tname == "IDENTIFIER":
            name = node.to_nim()
        elif tname == "block":
            block_node = node
        elif tname == "param_list":
            params = node.to_nim()
        elif tname == "return_annotation":
            ret_ann = node.to_nim()

    hc = _block_inline_header_comment(block_node) if block_node else ""
    body = block_node.to_nim(indent + 1) if block_node else ""
    return f"{decos}{_ind(indent)}proc {name}({params}){ret_ann} {{.async.}} ={hc}\n{body}"


# --- Class definition ---
@method(class_def)
def to_nim(self, indent=0):
    """class Foo(Bar): -> type Foo = object of Bar"""
    decos = ""
    name = ""
    bases = ""
    block_node = None

    for node in self.nodes:
        tname = type(node).__name__
        if tname == "decorators":
            decos = node.to_nim(indent) + "\n"
        elif tname == "Several_Times":
            for seq in node.nodes:
                stname = type(seq).__name__
                if stname == "decorator":
                    decos += seq.to_nim(indent) + "\n"
                elif stname == "decorators":
                    decos = seq.to_nim(indent) + "\n"
                elif stname == "class_args":
                    bases = seq.to_nim()
        elif tname == "class_args":
            bases = node.to_nim()
        elif tname == "IDENTIFIER":
            name = node.to_nim()
        elif tname == "block":
            block_node = node

    hc = _block_inline_header_comment(block_node) if block_node else ""
    body = block_node.to_nim(indent + 1) if block_node else ""
    # Nim: type Foo = object of Bar
    parent = ""
    if bases and bases not in ("()", ""):
        # Extract base class from "(Bar)" or "(Bar, Baz)"
        inner = bases[1:-1] if bases.startswith("(") else bases
        parent = f" of {inner.split(',')[0].strip()}"
    return f"{decos}{_ind(indent)}type {name} = object{parent}\n{body}"


@method(class_args)
def to_nim(self):
    st = self.nodes[0]
    if hasattr(st, "nodes") and st.nodes:
        args_node = st.nodes[0]
        return f"({args_node.to_nim()})"
    return "()"


# --- Async for / with ---
@method(async_for_stmt)
def to_nim(self, indent=0):
    target = self.nodes[0].to_nim()
    iterable = self.nodes[1].to_nim()
    hc = _block_inline_header_comment(self.nodes[2])
    body = self.nodes[2].to_nim(indent + 1)
    return f"{_ind(indent)}for {target} in {iterable}:{hc}  # async\n{body}"


@method(async_with_stmt)
def to_nim(self, indent=0):
    items = [self.nodes[0].to_nim()]
    block_node = None
    for node in self.nodes[1:]:
        if type(node).__name__ == "Several_Times":
            for seq in node.nodes:
                if hasattr(seq, "nodes") and seq.nodes:
                    item = seq.nodes[0]
                    if hasattr(item, "to_nim"):
                        items.append(item.to_nim())
        elif hasattr(node, "to_nim"):
            block_node = node
    body = ""
    hc = ""
    if block_node:
        hc = _block_inline_header_comment(block_node)
        try:
            body = block_node.to_nim(indent + 1)
        except TypeError:
            body = _ind(indent + 1) + block_node.to_nim()
    return f"{_ind(indent)}with {', '.join(items)}:{hc}  # async\n{body}"


# --- compound_stmt ---
@method(compound_stmt)
def to_nim(self, indent=0):
    return self.nodes[0].to_nim(indent)


# --- stmt_line (override from hek_nim_stmt to call to_nim recursively) ---
@method(stmt_line)
def to_nim(self, indent=0):
    parts = []
    newline_node = None

    for node in self.nodes:
        tname = type(node).__name__
        if tname == "simple_stmt":
            parts.append(_ind(indent) + node.to_nim())
        elif isinstance(node, RichNL):
            newline_node = node
        elif tname == "Several_Times":
            for seq in node.nodes:
                if isinstance(seq, RichNL):
                    newline_node = seq
                elif hasattr(seq, "nodes") and seq.nodes:
                    inner = seq.nodes[0] if len(seq.nodes) == 1 else None
                    if inner is not None and isinstance(inner, RichNL):
                        newline_node = inner
                    else:
                        for child in seq.nodes:
                            if hasattr(child, "to_nim"):
                                parts.append(_ind(indent) + child.to_nim())
        elif hasattr(node, "to_nim"):
            try:
                parts.append(node.to_nim(indent))
            except TypeError:
                parts.append(_ind(indent) + node.to_nim())

    if not parts:
        parts = [_ind(indent) + self.nodes[0].to_nim()]

    result = "; ".join(p.strip() for p in parts if p.strip())
    result = _ind(indent) + result

    if newline_node is not None and hasattr(newline_node, 'comments') and newline_node.comments:
        for kind, text, ind in newline_node.comments:
            if kind == 'comment':
                result += '  ' + text
    return result


###############################################################################
# Tests
###############################################################################

if __name__ == "__main__":
    print("=" * 60)
    print("Python -> Nim Compound Statement Translation Tests")
    print("=" * 60)

    tests = [
        # --- if / elif / else ---
        (
            "if x:\n    pass\n",
            "if x:\n    discard",
        ),
        (
            "if x:\n    y = 1\n",
            "if x:\n    var y = 1",
        ),
        (
            "if x:\n    a = 1\nelif y:\n    b = 2\n",
            "if x:\n    var a = 1\nelif y:\n    var b = 2",
        ),
        (
            "if x:\n    a = 1\nelif y:\n    b = 2\nelse:\n    c = 3\n",
            "if x:\n    var a = 1\nelif y:\n    var b = 2\nelse:\n    var c = 3",
        ),
        # --- while ---
        (
            "while x:\n    pass\n",
            "while x:\n    discard",
        ),
        # --- for ---
        (
            "for x in xs:\n    pass\n",
            "for x in xs:\n    discard",
        ),
        (
            "for i in range:\n    x = i\n",
            "for i in range:\n    var x = i",
        ),
        # --- try / except / finally ---
        (
            "try:\n    pass\nexcept:\n    pass\n",
            "try:\n    discard\nexcept:\n    discard",
        ),
        (
            "try:\n    x = 1\nexcept ValueError:\n    pass\n",
            "try:\n    var x = 1\nexcept ValueError:\n    discard",
        ),
        (
            "try:\n    x = 1\nexcept ValueError as e:\n    pass\n",
            "try:\n    var x = 1\nexcept ValueError as e:\n    discard",
        ),
        (
            "try:\n    x = 1\nfinally:\n    y = 2\n",
            "try:\n    var x = 1\nfinally:\n    var y = 2",
        ),
        # --- with (kept as-is) ---
        (
            "with f():\n    pass\n",
            "with f():\n    discard",
        ),
        (
            "with f() as x:\n    pass\n",
            "with f() as x:\n    discard",
        ),
        # --- def -> proc ---
        (
            "def f():\n    pass\n",
            "proc f() =\n    discard",
        ),
        (
            "def f(a, b):\n    return a\n",
            "proc f(a: auto, b: auto) =\n    return a",
        ),
        (
            "def f(a: int) -> str:\n    pass\n",
            "proc f(a: int): string =\n    discard",
        ),
        (
            "def f(*args):\n    pass\n",
            "proc f(args: varargs[auto]) =\n    discard",
        ),
        # --- class -> type object ---
        (
            "class Foo:\n    pass\n",
            "type Foo = object\n    discard",
        ),
        (
            "class Foo(Bar):\n    pass\n",
            "type Foo = object of Bar\n    discard",
        ),
        # --- async def -> proc {.async.} ---
        (
            "async def f():\n    pass\n",
            "proc f() {.async.} =\n    discard",
        ),
        # --- match -> case ---
        (
            "match x:\n    case 1:\n        pass\n",
            "case x:\n    of 1:\n        discard",
        ),
        (
            "match x:\n    case _:\n        pass\n",
            "case x:\n    of _:\n        discard",
        ),
        (
            "match x:\n    case 1 | 2:\n        pass\n",
            "case x:\n    of 1, 2:\n        discard",
        ),
        # --- nested ---
        (
            "if x:\n    if y:\n        pass\n",
            "if x:\n    if y:\n        discard",
        ),
        (
            "def f():\n    for x in xs:\n        if x:\n            return x\n",
            "proc f() =\n    for x in xs:\n        if x:\n            return x",
        ),
        # --- decorator ---
        (
            "@dec\ndef f():\n    pass\n",
            "@dec\nproc f() =\n    discard",
        ),
    ]

    passed = failed = 0
    for code, expected in tests:
        try:
            result = parse_compound(code)
            if result:
                output = result.to_nim()
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
