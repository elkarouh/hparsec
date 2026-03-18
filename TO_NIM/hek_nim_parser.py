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

import sys, os
_dir = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(_dir, ".."))
sys.path.insert(0, os.path.join(_dir, "..", "HPYTHON_GRAMMAR"))


from hek_parsec import method, ParserState
from py3compound_stmt import *  # noqa: F403 — grammar definitions
from hek_helpers import _ind, _richnl_lines, _block_inline_header_comment
from py3compound_stmt import parse_compound, parse_module
from hek_tokenize import RichNL
import re
import hek_nim_expr  # noqa: F401 — registers expr to_nim()
import hek_nim_stmt  # noqa: F401 — registers stmt to_nim()
import hek_nim_declarations  # noqa: F401 — registers decl to_nim()

###############################################################################
# Class method registry for base pragma detection
_class_methods = {}   # class_name -> set of method names
_class_parents = {}   # class_name -> parent_name or None

def _strip_generic(name):
    """Strip generic params: 'Optimizer[S, D]' -> 'Optimizer'"""
    idx = name.find("[")
    return name[:idx] if idx >= 0 else name

def _is_new_method(class_name, method_name):
    """Return True if method_name is not defined in any ancestor of class_name."""
    parent = _class_parents.get(class_name)
    while parent:
        base_parent = _strip_generic(parent)
        if method_name in _class_methods.get(base_parent, set()):
            return False
        parent = _class_parents.get(base_parent)
    return True

# to_nim() methods for compound statements
###############################################################################


@method(NL)
def to_nim(self, indent=0):
    rn = RichNL.extract_from(self)
    return rn.to_py() if rn is not None else ''


# --- block ---
@method(block)
def to_nim(self, indent=0, is_virtual=False, class_name=None, parent_name=None, type_params=""):
    """Emit body lines. For virtual classes, generates proper Nim structure."""
    lines = []
    fields = []
    methods = []
    
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
                        if is_virtual:
                            stmt_node_type = type(stmt_node).__name__
                            if stmt_node_type == "func_def":
                                methods.append(stmt_node)
                            elif stmt_node_type == "stmt_line":
                                found_field = False
                                for child in stmt_node.nodes:
                                    if type(child).__name__ == "decl_ann_assign_stmt":
                                        fields.append(stmt_node)
                                        found_field = True
                                        break
                                if not found_field:
                                    try:
                                        lines.append(stmt_node.to_nim(indent))
                                    except TypeError:
                                        lines.append(_ind(indent) + stmt_node.to_nim())
                            else:
                                try:
                                    lines.append(stmt_node.to_nim(indent))
                                except TypeError:
                                    lines.append(_ind(indent) + stmt_node.to_nim())
                        else:
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
    
    if class_name:  # Process all classes with fields/methods
        result_lines = []
        field_defaults = []  # list of (field_name, default_expr) for constructor init
        # Emit fields (inside object body): strip var/let/const keyword and defaults
        for field in fields:
            line = field.to_nim(indent)
            stripped = line.lstrip()
            for kw in ("var ", "let ", "const "):
                if stripped.startswith(kw):
                    line = line[:len(line) - len(stripped)] + stripped[len(kw):]
                    break
            # Capture default value before stripping
            import re as _re
            default_match = _re.search(r'^\s*(\w+)\s*:.+?\s*=\s*(.+)$', line.strip())
            if default_match:
                field_defaults.append((default_match.group(1), default_match.group(2)))
            # Strip default value: Nim object fields don't support inline defaults
            line = _re.sub(r' = .+$', '', line)
            result_lines.append(line)
        
        # Emit a blank line after fields for readability
        if fields:
            result_lines.append("")

        
        inits = []
        other_methods = []
        for method in methods:
            method_type = type(method).__name__
            func_node = None
            if method_type == "func_def":
                func_node = method
            elif method_type == "stmt_line":
                for child in method.nodes:
                    if type(child).__name__ == "func_def":
                        func_node = child
                        break
            if func_node:
                for node in func_node.nodes:
                    if type(node).__name__ == "IDENTIFIER":
                        method_name = str(node.nodes[0])
                        if method_name == "__init__":
                            inits.append(func_node)
                        else:
                            other_methods.append((func_node, method_name))
                        break
        
        # Register all method names for this class
        if class_name:
            _class_methods[class_name] = set()
            for _, mname in other_methods:
                _class_methods[class_name].add(mname)
            _class_parents[class_name] = parent_name if parent_name else None

        # Check if this is a virtual class
        is_virtual_class = getattr(self, '_is_virtual', False)

        # Use base_indent for procs/methods (top level), not the indented value
        base_indent = getattr(self, '_base_indent', indent)
        class_type = class_name + type_params if class_name else None
        
        # Emit forward declarations for methods so __init__ can call them
        if inits and other_methods:
            for func_node_m, mname in other_methods:
                fwd = _generate_method_decl(func_node_m, base_indent, class_name, parent_name, is_virtual_class, type_params)
                if fwd:
                    sig = fwd[0].rstrip()
                    if sig.endswith(" ="):
                        sig = sig[:-2]
                    # Skip forward declarations for iterators (Nim doesn't support them)
                    if sig.lstrip().startswith("iterator "):
                        continue
                    result_lines.append(sig)

        for func_node in inits:
            # Generate init/new procs at top level (same indent as type definition)
            init_lines, new_lines = _generate_init_new(func_node, base_indent, class_name, parent_name, is_virtual_class, type_params, field_defaults=field_defaults)
            result_lines.extend(init_lines)
            result_lines.extend(new_lines)
        

        # If no __init__ but class needs a constructor, generate a default newClassName
        if not inits and class_name:
            new_name = f"new{class_name}"
            export = "*" if base_indent == 0 else ""
            result_lines.append(f"{_ind(base_indent)}proc {new_name}{export}{type_params}(): {class_type} =")
            result_lines.append(f"{_ind(base_indent + 1)}new(result)")
            # Initialize fields with default values
            for fname, fdefault in field_defaults:
                result_lines.append(f"{_ind(base_indent + 1)}result.{fname} = {fdefault}")
        for func_node, method_name in other_methods:
            # Generate methods at top level (same indent as type definition)
            method_lines = _generate_method_decl(func_node, base_indent, class_name, parent_name, is_virtual_class, type_params)
            result_lines.extend(method_lines)
        
        # If no fields or methods, emit discard for empty body
        if not result_lines:
            result_lines.append(_ind(indent) + "discard")
        return "\n".join(result_lines)
    
    # For non-class blocks, if empty emit discard
    if not lines:
        return _ind(indent) + "discard"
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
    cond = hek_nim_expr._nim_truthiness(self.nodes[0].to_nim())
    # Detect if __name__ == "__main__": -> when isMainModule:
    cond_stripped = cond.replace(" ", "")
    if cond_stripped in ('__name__=="__main__"', "__name__=='__main__'"):
        hc = _block_inline_header_comment(self.nodes[1])
        body = self.nodes[1].to_nim(indent + 1)
        return f"{_ind(indent)}when isMainModule:{hc}\n{body}"
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
    cond = hek_nim_expr._nim_truthiness(self.nodes[0].to_nim())
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
    # File iteration: for line in f -> for line in f.lines
    sym = ParserState.symbol_table.lookup(iterable)
    if sym and sym.get("type") == "File":
        iterable = f"{iterable}.lines"
    # Nim tuple unpacking in for: for x, y in seq -> for (x, y) in seq
    if "," in target and not target.startswith("("):
        target = f"({target})"
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
    # Translate with open(file, mode) as var -> Nim open()/defer:close()
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
    # Detect open(filename, mode) as varname pattern
    import re as _re
    full_item = ", ".join(items)
    m = _re.match(r'open\((.+?)\)\s+as\s+(\w+)', full_item)
    if m:
        args_str, var_name = m.group(1), m.group(2)
        mode_map = {'"r"': "fmRead", "'r'": "fmRead",
                    '"w"': "fmWrite", "'w'": "fmWrite",
                    '"a"': "fmAppend", "'a'": "fmAppend"}
        args = [a.strip() for a in args_str.split(",")]
        filename = args[0]
        nim_mode = "fmRead"
        if len(args) > 1:
            raw_mode = args[1].strip()
            # Skip encoding and other kwargs
            if "=" not in raw_mode:
                nim_mode = mode_map.get(raw_mode, raw_mode)
        # Register the file variable in the symbol table
        ParserState.symbol_table.add(var_name, "File", "let")
        # Emit block: to create a new scope (mirroring Python's with statement)
        ind = _ind(indent)
        ind1 = _ind(indent + 1)
        result = f"{ind}block:{hc}\n"
        result += f"{ind1}let {var_name} = open({filename}, {nim_mode})\n"
        result += f"{ind1}defer: {var_name}.close()\n"
        if block_node:
            try:
                body = block_node.to_nim(indent + 1)
            except TypeError:
                body = ind1 + block_node.to_nim()
        result += body
        return result
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
    name = str(n)
    # Nim disallows leading underscores — strip single leading _
    if name.startswith("_") and not name.startswith("__"):
        name = name[1:]
    return name


@method(pattern_capture)
def to_nim(self, prec=None):
    n = self.nodes[0]
    if hasattr(n, "to_nim"):
        name = n.to_nim()
    else:
        name = str(n)
    # Resolve tick attributes: Type__tick__First -> first value of subrange/enum
    if "__tick__" in name:
        type_name, _, attr = name.partition("__tick__")
        info = ParserState.tick_types.get(type_name)
        if info and attr in info:
            return str(info[attr])
    # Nim disallows leading underscores — strip single leading _
    if name.startswith("_") and not name.startswith("__"):
        name = name[1:]
    return name


@method(pattern_wildcard)
def to_nim(self):
    return "_"


@method(pattern_others)
def to_nim(self):
    return "others"


@method(pattern_range)
def to_nim(self):
    lo = self.nodes[0].to_nim()
    hi = self.nodes[-1].to_nim()
    return f"{lo} .. {hi}"


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
    ParserState.nim_imports.add("tables")
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


@method(when_clause)
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
    prefix = "else" if pat == "others" else f"of {pat}"
    return f"{_ind(indent)}{prefix}{guard}:{hc}\n{body}"


@method(case_stmt)
def to_nim(self, indent=0):
    """match -> Nim case statement"""
    subject = self.nodes[0].to_nim()
    result = f"{_ind(indent)}case {subject}:"
    for node in self.nodes[1:]:
        tname = type(node).__name__
        if tname == "when_clause":
            result += "\n" + node.to_nim(indent + 1)
        elif tname == "Several_Times":
            for seq in node.nodes:
                stname = type(seq).__name__
                if stname == "when_clause":
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
    prefix = "else" if pat == "others" else f"of {pat}"
    return f"{_ind(indent)}{prefix}{guard}:{hc}\n{body}"


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
    nim_type = annotation[2:] if annotation.startswith(": ") else annotation[1:]
    ParserState.symbol_table.add(name, nim_type, "param")
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

    # Store return type so return_stmt can use it for Option wrapping
    ParserState._current_return_type = ret_ann  # e.g. ': Option[string]'
    ParserState.symbol_table.push_scope(name or "<func>")
    hc = _block_inline_header_comment(block_node) if block_node else ""
    body = block_node.to_nim(indent + 1) if block_node else ""
    ParserState.symbol_table.pop_scope()
    ParserState._current_return_type = ""
    # Add var to params that are mutated in body (assigned to or .add called)
    if params and body:
        import re as _re
        new_params = []
        for p in params.split(", "):
            pname = p.split(":")[0].strip()
            if pname and pname != "self" and " = " not in p and _re.search(
                rf"(?<![=(,.])\b{_re.escape(pname)}\b\s*(\.add\(|\[.*\]\s*=|[+\-*/]=|=(?!=))", body
            ):
                if not p.startswith("var ") and ": " in p:
                    # Nim syntax: param: var T
                    parts = p.split(": ", 1)
                    p = parts[0] + ": var " + parts[1]
            new_params.append(p)
        params = ", ".join(new_params)
    # -- Method hoisting ------------------------------------------------
    # Nim forbids `method` declarations inside procs.  When an HPython
    # function body contains class definitions (which emit Nim methods),
    # we hoist types, methods, procs, consts, and ALL_CAPS vars to the
    # module's top level, leaving only executable code inside the proc.
    #
    # This is transparent when classes live at the module level (the
    # normal case) -- no hoisting or renaming occurs.
    #
    # Name mangling:
    #   When *multiple* functions define types with the **same** name
    #   (e.g. two functions both define `State_T`), the second and
    #   subsequent definitions are mangled with a suffix derived from
    #   the enclosing function name (example3 -> _3) so that each set
    #   of hoisted declarations gets unique top-level names.  Mangling
    #   is applied consistently to hoisted types, methods, procs, and
    #   the executable code that stays inside the proc.
    #
    #   Mangling is **only** triggered when a name collision is detected,
    #   so single-use type names are never renamed.
    # ----------------------------------------------------------------
    if block_node and body:
        import re as _re_h
        body_lines = body.split("\n")

        # --- Pass 1: collect local type names defined in this body ---
        local_types = []
        for line in body_lines:
            stripped = line.lstrip()
            if stripped.startswith("type ") and not stripped.startswith("type("):
                tm = _re_h.match(r"type\s+(\w+)", stripped)
                if tm:
                    local_types.append(tm.group(1))

        # --- Derive suffix from function name (example3 -> _3, myFunc -> _myFunc) ---
        suffix = ""
        if local_types and name:
            m_num = _re_h.match(r"example(\d+)$", name)
            if m_num:
                suffix = "_" + m_num.group(1)
            else:
                suffix = "_" + name

        # --- Build mangling map: only rename types that conflict with top-level ---
        if not hasattr(ParserState, '_hoisted_type_names'):
            ParserState._hoisted_type_names = set()
        if not hasattr(ParserState, '_hoisted_enum_members'):
            ParserState._hoisted_enum_members = set()
        # Collect enum members for each local type
        local_enum_members = {}  # type_name -> [member1, member2, ...]
        for line in body_lines:
            stripped = line.lstrip()
            if stripped.startswith("type ") and " enum " in stripped:
                em = _re_h.match(r"type\s+(\w+)\s*=\s*enum\s+(.*)", stripped)
                if em:
                    members = [m.strip().rstrip(",") for m in em.group(2).split(",") if m.strip()]
                    local_enum_members[em.group(1)] = members
        mangle_map = {}  # old_name -> new_name
        for tname in local_types:
            if suffix and tname in ParserState._hoisted_type_names:
                mangle_map[tname] = tname + suffix
                # Also mangle enum members if this type is an enum
                if tname in local_enum_members:
                    for member in local_enum_members[tname]:
                        if member in ParserState._hoisted_enum_members:
                            mangle_map[member] = member + suffix
                            ParserState._hoisted_enum_members.add(member + suffix)
                        else:
                            ParserState._hoisted_enum_members.add(member)
            else:
                if tname in local_enum_members:
                    for member in local_enum_members[tname]:
                        ParserState._hoisted_enum_members.add(member)
            ParserState._hoisted_type_names.add(tname if tname not in mangle_map else mangle_map[tname])

        def _mangle_line(line):
            """Apply type name mangling to a line."""
            if not mangle_map:
                return line
            for old_name, new_name in mangle_map.items():
                line = _re_h.sub(r'\b' + old_name + r'\b', new_name, line)
            return line

        # --- Pass 2: separate hoisted vs kept, applying mangling ---
        hoisted = []
        kept = []
        in_method = False
        method_indent = 0
        in_type = False
        type_base_indent = 0
        for line in body_lines:
            stripped = line.lstrip()
            cur_indent = len(line) - len(stripped)
            # Detect start of a method (indented one level inside proc)
            if stripped.startswith("method "):
                in_method = True
                method_indent = cur_indent
                hoisted.append(_mangle_line(line[method_indent:]))
                continue
            # Continuation of a method body (deeper indent)
            if in_method:
                if stripped == "" or cur_indent > method_indent:
                    hoisted.append(_mangle_line(line[method_indent:] if len(line) >= method_indent else line))
                    continue
                else:
                    in_method = False
            # Detect type/object declarations
            if stripped.startswith("type ") and not stripped.startswith("type("):
                in_type = True
                type_base_indent = cur_indent
                dedented_line = line[type_base_indent:] if cur_indent > 0 else line
                hoisted.append(_mangle_line(dedented_line))
                continue
            # Continuation of a multi-line type
            if in_type:
                if stripped == "" or cur_indent > type_base_indent:
                    hoisted.append(_mangle_line(line[type_base_indent:] if len(line) >= type_base_indent else line))
                    continue
                else:
                    in_type = False
            # Drop import statements (already handled at top level by nim_imports)
            if stripped.startswith("import "):
                continue
            # Hoist const declarations and ALL_CAPS let/var declarations
            if stripped.startswith("const "):
                dedented_line = line[cur_indent:] if cur_indent > 0 else line
                hoisted.append(_mangle_line(dedented_line))
                continue
            if stripped.startswith("let "):
                let_m = _re_h.match(r"let\s+([A-Z][A-Z_0-9]*)\s*:", stripped)
                if let_m:
                    dedented_line = line[cur_indent:] if cur_indent > 0 else line
                    hoisted.append(_mangle_line(dedented_line))
                    continue
            if stripped.startswith("var "):
                var_m = _re_h.match(r"var\s+([A-Z][A-Z_0-9]*)\s*:", stripped)
                if var_m:
                    dedented_line = line[cur_indent:] if cur_indent > 0 else line
                    hoisted.append(_mangle_line(dedented_line))
                    continue
            # Hoist proc/func declarations that are methods (have self/base param)
            # or constructors (init/new prefixed).  Keep nested procs that
            # are plain closures — they need enclosing scope variables.
            if stripped.startswith("proc ") or stripped.startswith("func "):
                _is_method = "(self" in stripped or "(base" in stripped
                _is_ctor = _re_h.match(r'(?:proc|func)\s+(init|new)', stripped)
                if _is_method or _is_ctor:
                    in_method = True
                    method_indent = cur_indent
                    hoisted.append(_mangle_line(line[method_indent:]))
                    continue
            kept.append(_mangle_line(line))
        if hoisted:
            hoisted_block = "\n".join(hoisted) + "\n"
            body = "\n".join(kept)
            # If no return annotation but body has return stmts, infer auto
            if not ret_ann and body:
                if _re_h.search(r'\breturn\b\s+\S', body):
                    ret_ann = ": auto"
            return f"{hoisted_block}{decos}{_ind(indent)}proc {name}({params}){ret_ann} ={hc}\n{body}"
    # If no return annotation but body has return statements, infer ': auto'
    if not ret_ann and body:
        import re as _re
        if _re.search(r'\breturn\b\s+\S', body):
            ret_ann = ": auto"
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

    ParserState.symbol_table.push_scope(name or "<async_func>")
    hc = _block_inline_header_comment(block_node) if block_node else ""
    body = block_node.to_nim(indent + 1) if block_node else ""
    ParserState.symbol_table.pop_scope()
    return f"{decos}{_ind(indent)}proc {name}({params}){ret_ann} {{.async.}} ={hc}\n{body}"


# --- Class definition ---
@method(class_def)
def to_nim(self, indent=0):
    """class Foo(Bar): -> type Foo = ref object of Bar (if @virtual)"""
    decos = ""
    name = ""
    bases = ""
    type_params = ""
    block_node = None

    for node in self.nodes:
        tname = type(node).__name__
        if tname == "decorators":
            decos_str = node.to_nim(indent)
            # Strip @virtual — ref/method is now inferred from inheritance
            if "@virtual" not in decos_str:
                decos = decos_str + "\n"
        elif tname == "Several_Times":
            for seq in node.nodes:
                stname = type(seq).__name__
                if stname == "decorator":
                    deco_str = seq.to_nim(indent)
                    if "@virtual" not in deco_str:
                        decos += deco_str + "\n"
                elif stname == "decorators":
                    decos_str = seq.to_nim(indent)
                    if "@virtual" not in decos_str:
                        decos = decos_str + "\n"
                elif stname == "type_alias_params":
                    type_params = seq.to_nim()
                elif stname == "class_args":
                    bases = seq.to_nim()
        elif tname == "type_alias_params":
            type_params = node.to_nim()
        elif tname == "class_args":
            bases = node.to_nim()
        elif tname == "IDENTIFIER":
            name = node.to_nim()
        elif tname == "block":
            block_node = node

    # Infer virtual from class hierarchy (pre-scanned in translate())
    is_virtual = name in getattr(ParserState, "_ref_classes", set())

    parent_name = ""
    if bases and bases not in ("()", ""):
        inner = bases[1:-1] if bases.startswith("(") else bases
        # Split on comma but respect bracket nesting (e.g. Optimizer[S, D])
        depth = 0
        for i, ch in enumerate(inner):
            if ch in "[(": depth += 1
            elif ch in "])": depth -= 1
            elif ch == "," and depth == 0:
                inner = inner[:i]
                break
        parent_name = inner.strip()

    # Warn if a tuple type is used directly as a generic parameter
    if bases and "[(" in bases and ")]" in bases:
        import re as _re
        _m = _re.search(r'(\w+)\[\(', bases)
        _parent = _m.group(1) if _m else "Base"
        print(f"WARNING: class {name}({_parent}[(...)]): tuple used as generic parameter.\n"
              f"  Use a type alias instead:  type MyTuple is (int, int)\n"
              f"  Then:  class {name}({_parent}[MyTuple]):", file=sys.stderr)


    # Register class name in symbol table so constructor calls can be detected
    if name:
        ParserState.symbol_table.add(name, name, "class")
    ParserState.symbol_table.push_scope(name or "<class>")
    # Pre-check for self-referencing fields (e.g., children: [Digit_T]TrieNode)
    if block_node and name and not is_virtual:
        def _has_self_ref(node, cls_name):
            """Check if any IDENTIFIER in the node matches the class name."""
            tname = type(node).__name__
            if tname == "IDENTIFIER":
                val = getattr(node, "node", None)
                if not isinstance(val, str) and hasattr(node, "nodes") and node.nodes:
                    val = str(node.nodes[0])
                if val == cls_name:
                    return True
            if hasattr(node, "nodes"):
                for child in node.nodes:
                    if _has_self_ref(child, cls_name):
                        return True
            return False
        def _find_field_decls(node):
            """Recursively find ann_assign_stmt / decl_ann_assign_stmt nodes."""
            tn = type(node).__name__
            if tn in ("ann_assign_stmt", "decl_ann_assign_stmt"):
                return [node]
            result = []
            if hasattr(node, "nodes"):
                for child in node.nodes:
                    result.extend(_find_field_decls(child))
            return result
        for decl in _find_field_decls(block_node):
            if _has_self_ref(decl, name):
                is_virtual = True
                break
    if block_node:
        block_node._is_virtual = is_virtual
        block_node._class_name = name
        block_node._parent_name = parent_name
        block_node._base_indent = indent  # Store original indent for procs/methods
    # Always use is_virtual=True for block processing to get init/new procs
    # The 'ref' keyword is controlled separately
    body = block_node.to_nim(indent + 1, is_virtual=True, class_name=name, parent_name=parent_name, type_params=type_params) if block_node else ""
    
    parent = f" of {parent_name}" if parent_name else " of RootObj"
    # Check field declarations for self-reference (e.g., children: array[X, TrieNode])
    # Only match lines that look like field decls: "    name: type"
    import re as _re
    field_lines = [l for l in body.split("\n") if l.strip() and _re.match(r"\s+\w+:", l) and not l.strip().startswith("proc ") and not l.strip().startswith("method ")]
    fields_text = "\n".join(field_lines)
    needs_ref = is_virtual or (name and name in fields_text)
    ref_keyword = "ref " if needs_ref else ""
    ParserState.symbol_table.pop_scope()
    return f"{decos}{_ind(indent)}type {name}{type_params} = {ref_keyword}object{parent}\n{body}"


# --- Type block forms (tuple, record) ---

def _extract_fields_from_block(block_node, indent):
    """Extract field declarations from a block, returning indented Nim field lines.
    Strips var/let/const keywords and default values (same as class field extraction)."""
    import re as _re
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
                        if hasattr(child, "to_nim"):
                            cname = type(child).__name__
                            if cname == "stmt_line":
                                try:
                                    line = child.to_nim(indent)
                                except TypeError:
                                    line = _ind(indent) + child.to_nim()
                                stripped = line.lstrip()
                                for kw in ("var ", "let ", "const "):
                                    if stripped.startswith(kw):
                                        line = line[:len(line) - len(stripped)] + stripped[len(kw):]
                                        break
                                # Strip default value
                                line = _re.sub(r' = .+$', '', line)
                                if line.strip():
                                    lines.append(line)
    return lines


def _extract_variant_fields_nim(stmt_nodes, indent):
    """Extract field declarations from variant_when stmt_line nodes."""
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
                        line = child.to_nim(indent)
                    except TypeError:
                        line = _ind(indent) + child.to_nim()
                    stripped = line.lstrip()
                    for kw in ("var ", "let ", "const "):
                        if stripped.startswith(kw):
                            line = line[:len(line) - len(stripped)] + stripped[len(kw):]
                            break
                    line = _re.sub(r" = .+$", "", line)
                    if line.strip():
                        lines.append(line)
    return lines


@method(type_block_stmt)
def to_nim(self, indent=0):
    """type_block_stmt: 'type' IDENTIFIER discrim_param? type_alias_params? (=|is) (tuple_def|discrim_record_def|record_def)"""
    name = self.nodes[0].to_nim()
    params = ""
    discrim_name = None
    discrim_type = None
    rhs = self.nodes[-1]
    for node in self.nodes[1:-1]:
        ntype = type(node).__name__
        if ntype == "type_alias_params":
            params = node.to_nim()
        elif ntype == "Several_Times" and hasattr(node, "nodes"):
            for child in node.nodes:
                cn = type(child).__name__
                if cn == "type_alias_params":
                    params = child.to_nim()
                elif cn == "Sequence_Parser" and hasattr(child, "nodes"):
                    # discrim_param: (Name : Type) -> [IDENTIFIER, Fmap(:), type_name]
                    idents = [c for c in child.nodes if type(c).__name__ in ("IDENTIFIER", "type_name", "Filter")]
                    if len(idents) >= 2:
                        discrim_name = idents[0].to_nim()
                        discrim_type = idents[1].to_nim()
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
        # Discriminated record -> Nim object with case
        result = f"{_ind(indent)}type {name}{params} = object\n"
        result += f"{_ind(indent + 1)}case {discrim_name}: {discrim_type}\n"
        whens_node = None
        for child in variant_case_node.nodes:
            if type(child).__name__ == "Several_Times":
                whens_node = child
                break
        if whens_node:
            for when_node in whens_node.nodes:
                # when_node: [IDENTIFIER(pattern), NL, INDENT, Several_Times(fields), DEDENT]
                pat = None
                fields_node = None
                for child in when_node.nodes:
                    cn = type(child).__name__
                    if cn == "IDENTIFIER" and pat is None:
                        pat = child.to_nim()
                    elif cn == "Several_Times":
                        fields_node = child
                if pat and fields_node:
                    if pat == "others":
                        result += f"{_ind(indent + 1)}else:\n"
                    else:
                        result += f"{_ind(indent + 1)}of {pat}:\n"
                    fields = _extract_variant_fields_nim(fields_node.nodes, indent + 2)
                    for fld in fields:
                        result += fld + "\n"
        return result.rstrip("\n")
    if not block_node:
        block_node = rhs
    fields = _extract_fields_from_block(block_node, indent + 1)
    nim_kind = "tuple" if keyword == "tuple" else "object"
    return f"{_ind(indent)}type {name}{params} = {nim_kind}\n" + "\n".join(fields)



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
            "type Foo = object of RootObj\nproc newFoo*(): Foo =\n    new(result)",
        ),
        (
            "class Foo(Bar):\n    pass\n",
            "type Foo = object of Bar\nproc newFoo*(): Foo =\n    new(result)",
        ),
        # --- async def -> proc {.async.} ---
        (
            "async def f():\n    pass\n",
            "proc f() {.async.} =\n    discard",
        ),
        # --- match -> case ---
        (
            "case x:\n    when 1:\n        pass\n",
            "case x:\n    of 1:\n        discard",
        ),
        (
            "case x:\n    when _:\n        pass\n",
            "case x:\n    of _:\n        discard",
        ),
        (
            "case x:\n    when 1 | 2:\n        pass\n",
            "case x:\n    of 1, 2:\n        discard",
        ),
        (
            "case x:\n    when others:\n        pass\n",
            "case x:\n    else:\n        discard",
        ),
        (
            "case x:\n    when 1 .. 5:\n        pass\n",
            "case x:\n    of 1 .. 5:\n        discard",
        ),
        # --- discriminated records ---
        (
            "type Shape (Kind : Shape_Kind) is record:\n    case Kind is\n        when Circle:\n            Radius : float\n        when Rectangle:\n            Width : float\n            Height : float\n",
            "type Shape = object\n    case Kind: Shape_Kind\n    of Circle:\n        Radius: float\n    of Rectangle:\n        Width: float\n        Height: float",
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


def _generate_init_new(func_node, indent, class_name, parent_name, is_virtual=True, type_params="", field_defaults=None):
    """Generate init proc and new constructor for a class __init__ method."""
    class_type = class_name + type_params
    init_lines = []
    new_lines = []
    
    block_node = None
    param_list_node = None
    
    for node in func_node.nodes:
        tname = type(node).__name__
        if tname == "block":
            block_node = node
        elif tname == "Several_Times":
            for st in node.nodes:
                if type(st).__name__ == "param_list":
                    param_list_node = st
                    break
    
    param_strs = []
    param_names = []
    if param_list_node:
        for p in param_list_node.nodes:
            ptype_name = type(p).__name__
            param_nodes = []
            if ptype_name == "param_plain":
                param_nodes.append(p)
            elif ptype_name == "Several_Times":
                # Several_Times can contain multiple Sequence_Parser children
                for st_child in p.nodes:
                    if type(st_child).__name__ == "Sequence_Parser":
                        for sp_child in st_child.nodes:
                            if type(sp_child).__name__ == "param_plain":
                                param_nodes.append(sp_child)
            for param_node in param_nodes:
                pname = str(param_node.nodes[0].nodes[0])
                if pname == "self":
                    continue
                # Use param_plain.to_nim() to get name: type = default
                param_strs.append(param_node.to_nim())
                param_names.append(pname)
    
    params_str = ", ".join(param_strs)
    
    init_name = f"init{class_name}"
    # ref types: self: ClassName; value types: self: var ClassName
    is_ref = is_virtual
    if is_ref:
        self_param = f"self: {class_type}"
    else:
        self_param = f"self: var {class_type}"
    init_sig = f"{_ind(indent)}proc {init_name}{type_params}({self_param}{', ' + params_str if params_str else ''}) ="
    
    init_body = []
    if block_node:
        ParserState.symbol_table.push_scope(f"init{class_name}")
        for ps in param_strs:
            parts = ps.split(":")
            if len(parts) >= 2:
                pn = parts[0].strip()
                pt = parts[1].strip().split("=")[0].strip()
                ParserState.symbol_table.add(pn, pt, "param")
        init_body = _extract_block_body(block_node, indent + 1, is_init_body=True)
        ParserState.symbol_table.pop_scope()
        # Handle super().__init__() calls - replace with initParent(self, ...)
        for i, line in enumerate(init_body):
            if "super().__init__" in line:
                # Replace super().__init__(args) with initParent(self, args)
                match = re.search(r'super\(\).__init__\((.*)\)', line)
                if match:
                    args = match.group(1)
                    line = line.replace(f"super().__init__({args})", f"init{parent_name}(self, {args})")
                init_body[i] = line
    
    init_lines.append(init_sig)
    # Initialize fields with default values before user's init body
    if field_defaults:
        for fname, fdefault in field_defaults:
            init_lines.append(f"{_ind(indent + 1)}self.{fname} = {fdefault}")
    init_lines.extend(init_body)
    
    new_name = f"new{class_name}"
    export = "*" if indent == 0 else ""
    new_sig = f"{_ind(indent)}proc {new_name}{export}{type_params}({params_str}): {class_type} ="
    new_body = []
    if is_ref:
        new_body.append(f"{_ind(indent + 1)}new(result)")
    if param_names:
        new_body.append(f"{_ind(indent + 1)}{init_name}(result, {', '.join(param_names)})")
    else:
        new_body.append(f"{_ind(indent + 1)}{init_name}(result)")
    
    new_lines.append(new_sig)
    new_lines.extend(new_body)
    
    return init_lines, new_lines


def _generate_method_decl(func_node, indent, class_name, parent_name, is_virtual=False, type_params=""):
    """Generate method declaration. Uses 'method' for virtual, 'proc' for non-virtual."""
    lines = []
    
    name = ""
    params = []
    ret_ann = ""
    block_node = None
    
    for node in func_node.nodes:
        tname = type(node).__name__
        if tname == "IDENTIFIER":
            name = str(node.nodes[0])
        elif tname == "Several_Times":
            for st in node.nodes:
                st_name = type(st).__name__
                if st_name == "param_list":
                    for p in st.nodes:
                        ptype_name = type(p).__name__
                        param_nodes = []
                        if ptype_name == "param_plain":
                            param_nodes.append(p)
                        elif ptype_name == "Several_Times":
                            for st_child in p.nodes:
                                if type(st_child).__name__ == "Sequence_Parser":
                                    for sp_child in st_child.nodes:
                                        if type(sp_child).__name__ == "param_plain":
                                            param_nodes.append(sp_child)
                        for param_node in param_nodes:
                            pname = str(param_node.nodes[0].nodes[0])
                            ptype = "auto"
                            pdefault = ""
                            for pn in param_node.nodes[1:]:
                                if type(pn).__name__ == "Several_Times" and pn.nodes:
                                    for seq in pn.nodes:
                                        if hasattr(seq, "nodes") and len(seq.nodes) >= 2:
                                            op_str = str(seq.nodes[0].nodes[0]) if hasattr(seq.nodes[0], "nodes") and seq.nodes[0].nodes else ""
                                            if op_str == ":":
                                                ptype = seq.nodes[1].to_nim()
                                            elif op_str == "=":
                                                pdefault = f" = {seq.nodes[1].to_nim()}"
                            if pname == "self":
                                params.append(f"self: {class_name}{type_params}")
                            else:
                                params.append(f"{pname}: {ptype}{pdefault}")
                elif st_name == "return_annotation":
                    ret_ann = st.to_nim()
        elif tname == "return_annotation":
            ret_ann = node.to_nim()
        elif tname == "block":
            block_node = node
    
    # Store return type so return_stmt can use it for Option wrapping
    ParserState._current_return_type = ret_ann  # e.g. ': Option[string]'
    # Push scope and register params for body translation
    ParserState.symbol_table.push_scope(name or "<method>")
    for p in params:
        parts = p.split(":")
        if len(parts) >= 2:
            pn = parts[0].strip()
            pt = ":".join(parts[1:]).strip()
            ParserState.symbol_table.add(pn, pt, "param")

    # Extract body first so we can detect mutations
    body_lines = []
    if block_node:
        body_lines = _extract_block_body(block_node, indent + 1)

    # Add var to params that are mutated in body
    body_text = "\n".join(body_lines)
    if params and body_text:
        import re as _re
        new_params = []
        for p in params:
            pname = p.split(":")[0].strip()
            if pname and pname != "self" and " = " not in p and _re.search(
                rf"(?<![=(,.])\b{_re.escape(pname)}\b\s*(\.add\(|\[.*\]\s*=|[+\-*/]=|=(?!=))", body_text
            ):
                if not p.startswith("var ") and ": " in p:
                    # Nim syntax: param: var T
                    parts = p.split(": ", 1)
                    p = parts[0] + ": var " + parts[1]
            new_params.append(p)
        params = new_params

    params_str = ", ".join(params)
    # Detect if body contains yield -> use iterator instead of proc/method
    has_yield = any("yield " in line or line.strip() == "yield" for line in body_lines)
    if has_yield:
        pragma = ""
        keyword = "iterator"
        if not ret_ann:
            ret_ann = ": auto"
    elif is_virtual:
        pragma = " {.base.}" if _is_new_method(class_name, name) else ""
        keyword = "method"
    else:
        pragma = ""
        keyword = "proc"

    generic_params = type_params if type_params else ""
    method_sig = f"{_ind(indent)}{keyword} {name}{generic_params}({params_str}){ret_ann}{pragma} ="
    lines.append(method_sig)
    lines.extend(body_lines)

    ParserState.symbol_table.pop_scope()
    ParserState._current_return_type = ""
    return lines


def _extract_block_body(block_node, indent, is_init_body=False):
    """Extract body statements from a block node."""
    result_lines = []

    def _emit(line):
        # In init bodies, strip var from self.x assignments
        if is_init_body and line.strip().startswith("var self."):
            line = line.replace("var self.", "self.")
        # Skip redundant init lines (arrays/tables/seqs auto-init in Nim ref objects)
        if is_init_body:
            s = line.strip()
            if s.startswith("self.") and ("= initTable()" in s or "= collect(initTable" in s or s.endswith("= @[]")):
                return
        result_lines.append(line)

    for node in block_node.nodes:
        tname = type(node).__name__
        if tname in ("Fmap", "Filter"):
            continue
        if tname == "Several_Times":
            for seq in node.nodes:
                if type(seq).__name__ == "Sequence_Parser":
                    for child in seq.nodes:
                        if hasattr(child, "to_nim"):
                            try:
                                _emit(child.to_nim(indent))
                            except TypeError:
                                _emit(_ind(indent) + child.to_nim())
                elif hasattr(seq, "to_nim"):
                    try:
                        _emit(seq.to_nim(indent))
                    except TypeError:
                        _emit(_ind(indent) + seq.to_nim())
        elif hasattr(node, "to_nim"):
            try:
                _emit(node.to_nim(indent))
            except TypeError:
                _emit(_ind(indent) + node.to_nim())
    # If init body is empty after skipping, add discard
    if is_init_body and all(not l.strip() for l in result_lines):
        result_lines = [_ind(indent) + "discard"]
    return result_lines
