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
sys.path.insert(0, os.path.join(_dir, "..", "ADASCRIPT_GRAMMAR"))


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

# Python dunder method -> Nim operator/proc name
# Operators that Nim spells with backtick-quoted names.
_DUNDER_TO_NIM = {
    # Binary arithmetic
    "__add__":       "`+`",
    "__sub__":       "`-`",
    "__mul__":       "`*`",
    "__matmul__":    "`@`",
    "__truediv__":   "`/`",
    "__floordiv__":  "`div`",
    "__mod__":       "`mod`",
    "__pow__":       "`^`",
    "__lshift__":    "`shl`",
    "__rshift__":    "`shr`",
    "__and__":       "`and`",
    "__or__":        "`|`",
    "__xor__":       "`xor`",
    # Unary
    "__neg__":       "`-`",
    "__pos__":       "`+`",
    "__invert__":    "`not`",
    # Comparison
    "__eq__":        "`==`",
    "__ne__":        "`!=`",
    "__lt__":        "`<`",
    "__le__":        "`<=`",
    "__gt__":        "`>`",
    "__ge__":        "`>=`",
    # Item access
    "__getitem__":   "`[]`",
    "__setitem__":   "`[]=`",
    "__contains__":  "contains",
    # Callable object
    "__call__":      "`()`",
    # Reflected binary operators (param order is flipped vs normal)
    "__radd__":      "`+`",
    "__rsub__":      "`-`",
    "__rmul__":      "`*`",
    "__rtruediv__":  "`/`",
    "__rfloordiv__": "`div`",
    "__rmod__":      "`mod`",
    "__rpow__":      "`^`",
    "__ror__":       "`|`",
    "__rand__":      "`&`",
    "__rxor__":      "`xor`",
    # String / repr
    "__str__":       "`$`",
    "__repr__":      "`$`",
    # Standard Nim procs (no backticks needed)
    "__len__":       "len",
    "__hash__":      "hash",
    "__bool__":      "bool",
    "__abs__":       "abs",
    "__int__":       "int",
    "__float__":     "float",
    "__iter__":      None,   # becomes iterator items (special-cased)
    "__next__":      None,   # iterator protocol — skip
    "__enter__":     None,   # context manager — skip
    "__exit__":      None,   # context manager — skip
    "__del__":       None,   # destructor — skip
    "__init__":      None,   # handled separately as initX / newX
    "__new__":       None,   # handled separately
}

_SKIP_DUNDERS = {k for k, v in _DUNDER_TO_NIM.items() if v is None}

# Reflected operators: Python's (self, other) maps to Nim's (other, self)
_REVERSED_DUNDERS = {
    "__radd__", "__rsub__", "__rmul__", "__rtruediv__", "__rfloordiv__",
    "__rmod__", "__rpow__", "__ror__", "__rand__", "__rxor__",
}


def _nim_proc_name(py_name):
    """Translate a Python dunder/magic method name to its Nim proc name.

    Returns (nim_name, keyword) where keyword is 'proc', 'iterator', or None
    (None means skip this method entirely).

    Examples:
      __add__    -> ('`+`', 'proc')
      __iter__   -> ('items', 'iterator')
      __init__   -> (None, None)    -- handled elsewhere
    """
    if py_name in _SKIP_DUNDERS:
        if py_name == "__iter__":
            return "items", "iterator"
        return None, None
    nim_name = _DUNDER_TO_NIM.get(py_name)
    if nim_name is not None:
        return nim_name, "proc"
    # Nim disallows leading single underscore — strip it (mirrors IDENTIFIER.to_nim())
    if py_name != "_" and py_name.startswith("_") and not py_name.startswith("__"):
        py_name = py_name[1:]
    return py_name, "proc"   # non-dunder — unchanged

def _strip_generic(name):
    """Strip generic params: 'Optimizer[S, D]' -> 'Optimizer'"""
    idx = name.find("[")
    return name[:idx] if idx >= 0 else name

def _is_new_method(class_name, method_name):
    """Return True if method_name is not defined in any ancestor of class_name.
    Conservatively returns False if any ancestor's method set is unknown (e.g.
    the dependency was loaded from cache and never re-translated in this session),
    so that override methods never get {.base.} accidentally.
    """
    parent = _class_parents.get(class_name)
    while parent:
        base_parent = _strip_generic(parent)
        parent_methods = _class_methods.get(base_parent)  # None when unknown
        if parent_methods is None:
            return False  # unknown ancestor → conservatively assume override
        if method_name in parent_methods:
            return False  # found in ancestor → override
        parent = _class_parents.get(base_parent)
    return True


def _any_subclass_overrides(base_class, method_name):
    """Return True if any known subclass of base_class defines method_name.

    Uses the whole-file pre-scan stored in ParserState._all_class_methods
    (populated before translation begins) so that subclasses defined later in
    the file are already visible when the base-class methods are emitted.
    """
    all_methods = getattr(ParserState, "_all_class_methods", None)
    if all_methods is None:
        return True  # no pre-scan data → conservative: keep as method
    # Build the set of all subclasses (direct and transitive) of base_class.
    # _class_parents is populated incrementally during translation, but
    # _all_class_methods covers the whole file so we can derive subclass
    # relationships from it via the pre-scan hierarchy stored alongside.
    # Fallback: check every class whose *name* suggests it extends base_class.
    # We walk all_methods keys and check _class_parents for parentage.
    all_parents = getattr(ParserState, "_all_class_parents", None)
    if all_parents is None:
        return True
    # Collect all subclasses (BFS)
    subclasses = set()
    frontier = {base_class}
    while frontier:
        nxt = set()
        for cls, par in all_parents.items():
            if par and _strip_generic(par) in frontier and cls not in subclasses:
                subclasses.add(cls)
                nxt.add(cls)
        frontier = nxt
    return any(method_name in all_methods.get(sc, set()) for sc in subclasses)

# to_nim() methods for compound statements
###############################################################################

###############################################################################
# Bashism resolution — Nim equivalents
###############################################################################

_BASH_NIM = {
    "__bash_arg0__": "getAppFilename()",
    "__bash_args__": "commandLineParams()",
    "__bash_argc__": "paramCount()",
}


def _bash_to_nim(placeholder):
    """Translate a __bash_*__ placeholder to its Nim equivalent.

    Dispatch table:
      $0        -> getAppFilename()                          (requires os)
      $1 .. $N  -> (if paramCount() >= N: paramStr(N) else: "")  (multi-digit)
                   Guards against IndexDefect when the script is called
                   with fewer arguments than expected, matching bash
                   semantics where unset positional params expand to "".
      $@        -> commandLineParams()                       (requires os)
      $#        -> paramCount()                              (requires os)
      $NAME     -> getEnv("NAME")                           (requires os)

    All forms add ``os`` to ParserState.nim_imports so that the translate()
    driver inserts ``import os`` at the top of the output.
    """
    if placeholder in _BASH_NIM:
        ParserState.nim_imports.add("os")
        return _BASH_NIM[placeholder]
    # $1 .. $9 — safe, bash-compatible: return "" when argument is absent
    if placeholder.startswith("__bash_arg") and placeholder.endswith("__"):
        num_str = placeholder[len("__bash_arg"):-2]
        if num_str.isdigit() and num_str != "0":
            n = int(num_str)
            ParserState.nim_imports.add("os")
            return f'(if paramCount() >= {n}: paramStr({n}) else: "")'
    if placeholder.startswith("__bash_env_") and placeholder.endswith("__"):
        env_name = placeholder[len("__bash_env_"):-2]
        ParserState.nim_imports.add("os")
        return f'getEnv("{env_name}")'
    return placeholder  # unknown placeholder — pass through unchanged


@method(NL)
def to_nim(self, indent=0):
    """NL: newline/blank-line token -> emit preserved comment/blank lines from RichNL"""
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
        ParserState._current_class_name = class_name
        result_lines = []
        field_defaults = []  # list of (field_name, default_expr) for constructor init
        import re as _re
        # Emit fields (inside object body): strip var/let/const keyword and defaults
        for field in fields:
            line = field.to_nim(indent)
            stripped = line.lstrip()
            for kw in ("var ", "let ", "const "):
                if stripped.startswith(kw):
                    line = line[:len(line) - len(stripped)] + stripped[len(kw):]
                    break
            # Capture default value before stripping
            default_match = _re.search(r'^\s*(\w+)\s*:.+?\s*=\s*(.+)$', line.strip())
            if default_match:
                field_defaults.append((default_match.group(1), default_match.group(2)))
            # Register field type in class_field_types for Option-aware attr lookup
            field_type_match = _re.search(r'^\s*(\w+)\s*:\s*(.+?)(?:\s*=.*)?$', line.strip())
            if field_type_match and class_name:
                fname = field_type_match.group(1)
                ftype = field_type_match.group(2).strip()
                if fname in hek_nim_expr._PY_UNIVERSAL_METHOD_TO_NIM:
                    nim_equiv = hek_nim_expr._PY_UNIVERSAL_METHOD_TO_NIM[fname]
                    raise SyntaxError(
                        f"Field name '{fname}' in class '{class_name}' conflicts with "
                        f"the universal method mapping '{fname}' -> '{nim_equiv}'. "
                        f"Rename the field.")
                if class_name not in ParserState.class_field_types:
                    ParserState.class_field_types[class_name] = {}
                ParserState.class_field_types[class_name][fname] = ftype
            # Strip default value: Nim object fields don't support inline defaults
            line = _re.sub(r' = .+$', '', line)
            # Export field with * so subclasses in other modules can access it
            if getattr(ParserState, 'export_symbols', False):
                line = _re.sub(r'^(\s*\w+):', r'\1*:', line, count=1)
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


        # If no __init__ but class needs a constructor, generate a default newClassName.
        # If the class has a parent with a known constructor, forward its parameters.
        if not inits and class_name:
            new_name = f"new{class_name}"
            export = "*" if base_indent == 0 else ""
            parent_param_types = (
                getattr(ParserState, "proc_param_types", {}).get(f"new{parent_name}", [])
                if parent_name else []
            )
            parent_param_strs = (
                ParserState.proc_param_types_full.get(f"new{parent_name}", [])
                if parent_name else []
            )
            if parent_param_strs:
                # Forward constructor: mirror parent params and call initParent(result, ...)
                fwd_params = ", ".join(parent_param_strs)
                fwd_args = ", ".join(p.split(":")[0].strip().split(" = ")[0] for p in parent_param_strs)
                result_lines.append(f"{_ind(base_indent)}proc {new_name}{export}{type_params}({fwd_params}): {class_type} =")
                result_lines.append(f"{_ind(base_indent + 1)}new(result)" if is_virtual_class else f"{_ind(base_indent + 1)}result = {class_type}()")
                result_lines.append(f"{_ind(base_indent + 1)}init{parent_name}(result, {fwd_args})")
                for fname, fdefault in field_defaults:
                    result_lines.append(f"{_ind(base_indent + 1)}result.{fname} = {fdefault}")
            else:
                result_lines.append(f"{_ind(base_indent)}proc {new_name}{export}{type_params}(): {class_type} =")
                result_lines.append(f"{_ind(base_indent + 1)}new(result)" if is_virtual_class else f"{_ind(base_indent + 1)}result = {class_type}()")
                for fname, fdefault in field_defaults:
                    result_lines.append(f"{_ind(base_indent + 1)}result.{fname} = {fdefault}")
        for func_node, method_name in other_methods:
            # Generate methods at top level (same indent as type definition)
            method_lines = _generate_method_decl(func_node, base_indent, class_name, parent_name, is_virtual_class, type_params)
            result_lines.extend(method_lines)

        # If no fields or methods, emit discard for empty body
        if not result_lines:
            result_lines.append(_ind(indent) + "discard")
        ParserState._current_class_name = None
        return "\n".join(result_lines)

    # For non-class blocks, if empty emit discard
    if not lines:
        return _ind(indent) + "discard"
    return "\n".join(lines)


@method(statement)
def to_nim(self, indent=0):
    """statement: compound_stmt | stmt_line -> Nim: delegates to inner node"""
    inner = self.nodes[0]
    try:
        return inner.to_nim(indent)
    except TypeError:
        return _ind(indent) + inner.to_nim()


# --- if / elif / else ---
@method(elif_clause)
def to_nim(self, indent=0):
    """elif_clause: 'elif' expression ':' block -> Nim: 'elif cond:\n  body'"""
    cond = hek_nim_expr._nim_truthiness(self.nodes[0].to_nim())
    hc = _block_inline_header_comment(self.nodes[1])
    body = self.nodes[1].to_nim(indent + 1)
    return f"{_ind(indent)}elif {cond}:{hc}\n{body}"


@method(else_clause)
def to_nim(self, indent=0):
    """else_clause: 'else' ':' block -> Nim: 'else:\n  body'"""
    hc = _block_inline_header_comment(self.nodes[0])
    body = self.nodes[0].to_nim(indent + 1)
    return f"{_ind(indent)}else:{hc}\n{body}"


@method(if_stmt)
def to_nim(self, indent=0):
    """if_stmt: 'if' expression ':' block elif_clause* else_clause? -> Nim: 'if cond:'; 'if __name__ == "__main__"' -> 'when isMainModule:'"""
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
    """while_stmt: 'while' expression ':' block else_clause? -> Nim: 'while cond:' (else clause dropped)"""
    cond = hek_nim_expr._nim_truthiness(self.nodes[0].to_nim())
    hc = _block_inline_header_comment(self.nodes[1])
    body = self.nodes[1].to_nim(indent + 1)
    result = f"{_ind(indent)}while {cond}:{hc}\n{body}"
    # Nim has no while/else — skip else clause
    return result


# --- for ---
@method(for_target)
def to_nim(self):
    """for_target: IDENTIFIER (',' IDENTIFIER)* -> Nim: loop variable(s)"""
    parts = [self.nodes[0].to_nim()]
    for node in self.nodes[1:]:
        if type(node).__name__ == "Several_Times" and node.nodes:
            for seq in node.nodes:
                if hasattr(seq, "nodes") and seq.nodes:
                    parts.append(seq.nodes[0].to_nim())
    return ", ".join(parts)


@method(for_stmt)
def to_nim(self, indent=0):
    """for_stmt: 'for' for_target 'in' expression ':' block else_clause? -> Nim: 'for target in iter:' (else dropped); file vars -> .lines"""
    target = self.nodes[0].to_nim()
    iterable = self.nodes[1].to_nim()
    # File iteration: for line in f -> for line in f.lines
    sym = ParserState.symbol_table.lookup(iterable)
    if sym and sym.get("type") == "File":
        iterable = f"{iterable}.lines"
    # Table iteration: for k in table -> for k in table.keys
    from hek_nim_expr import _nim_expr_type
    _iter_type = _nim_expr_type(iterable) or ""
    if _iter_type.startswith("Table["):
        if "," in target and target.startswith("("):
            iterable = f"{iterable}.pairs"
        else:
            iterable = f"{iterable}.keys"
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
    """except_clause: 'except' expression ('as' IDENTIFIER)? ':' block -> Nim: 'except Type as name:\n  body'"""
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
    """except_star_clause: 'except*' expression ('as' IDENTIFIER)? ':' block -> Nim: 'except* Type' (Python 3.11+ ExceptionGroup)"""
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
    """except_bare: 'except' ':' block -> Nim: 'except:\n  body'"""
    hc = _block_inline_header_comment(self.nodes[0])
    body = self.nodes[0].to_nim(indent + 1)
    return f"{_ind(indent)}except:{hc}\n{body}"


@method(finally_clause)
def to_nim(self, indent=0):
    """finally_clause: 'finally' ':' block -> Nim: 'finally:\n  body'"""
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
    """try_except: 'try' ':' block (except_clause | except_star_clause)+ else_clause? -> Nim: 'try:\n  body\nexcept ...'"""
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
    """try_finally: 'try' ':' block finally_clause -> Nim: 'try:\n  body\nfinally:\n  ...'"""
    hc = _block_inline_header_comment(self.nodes[0])
    body = self.nodes[0].to_nim(indent + 1)
    fin = self.nodes[1].to_nim(indent)
    return f"{_ind(indent)}try:{hc}\n{body}\n{fin}"


@method(try_stmt)
def to_nim(self, indent=0):
    """try_stmt: try_except | try_finally"""
    return self.nodes[0].to_nim(indent)


# --- with ---
@method(with_item)
def to_nim(self):
    """with_item: expression ('as' IDENTIFIER)? -> Nim: 'expr as name'"""
    expr = self.nodes[0].to_nim()
    for node in self.nodes[1:]:
        if type(node).__name__ == "Several_Times" and node.nodes:
            for seq in node.nodes:
                if hasattr(seq, "nodes") and seq.nodes:
                    return f"{expr} as {seq.nodes[0].to_nim()}"
    return expr


@method(with_stmt)
def to_nim(self, indent=0):
    """with_stmt: 'with' with_item (',' with_item)* ':' block -> Nim: 'block:' with open() pattern or plain 'with'"""
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
    """with_stmt_paren: 'with' '(' with_item (',' with_item)* ')' ':' block -> Nim: parenthesised with"""
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
    """pattern_literal: literal value in case/when pattern -> Nim: literal"""
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
    """pattern_capture: IDENTIFIER in pattern (capture variable) -> Nim: name binding

    Also handles all plain IDENTIFIER uses (expressions, assignments, etc.)
    because pattern_capture = IDENTIFIER in the grammar — this method is the
    last writer on the shared class.  It therefore covers:
      - Tick attributes  (Type__tick__Attr)
      - Bash placeholders (__bash_*__)
      - Normal identifier pass-through
    """
    n = self.nodes[0]
    if hasattr(n, "to_nim"):
        name = n.to_nim()
    else:
        name = str(n)
    # Resolve tick attributes
    if "__tick__" in name:
        type_name, _, attr = name.partition("__tick__")
        info = ParserState.tick_types.get(type_name)
        if info and attr in info:
            return str(info[attr])
        # Check for set variable — only 'Choice and 'Size are valid on sets
        _sym = ParserState.symbol_table.lookup(type_name)
        _sym_type = _sym.get("type", "") if _sym else ""
        _is_set = _sym_type.startswith("HashSet") or _sym_type.startswith("set[")
        if _is_set and attr not in ("Choice", "Size", "len", "Length"):
            raise SyntaxError(
                f"'{attr} is not valid on a set; only 'Choice and 'Size are supported for sets"
            )
        # Ada tick attributes for enum operations
        if attr == "Range":
            # T'Range as set literal -> {T.low..T.high}
            return f"{{{type_name}.low..{type_name}.high}}"
        if attr == "Next":
            return type_name + ".succ"
        elif attr == "Prev":
            return type_name + ".pred"
        elif attr == "Choice":
            ParserState.nim_imports.add("random")
            if "randomize()" not in ParserState.nim_init_stmts:
                ParserState.nim_init_stmts.append("randomize()")
            if _is_set:
                if _sym_type.startswith("HashSet"):
                    ParserState.nim_imports.add("sequtils")
                    return f"{type_name}.toSeq[rand({type_name}.len - 1)]"
                else:
                    # set[T] (ordinal set) — use sample()
                    return f"sample({type_name})"
            return f"rand({type_name})"
        # General value tick attributes
        elif attr == "len" or attr == "Length":
            return type_name + ".len"
        elif attr == "Size":
            return type_name + ".sizeof"
        # Unknown tick attribute — emit as method call
        return type_name + "." + attr
    # Resolve bashisms: __bash_*__ placeholders -> Nim equivalents
    if name.startswith("__bash_") and name.endswith("__"):
        return _bash_to_nim(name)
    # '_' alone is the discard identifier in Nim — keep it.
    # Other single-leading-underscore names: strip the underscore.
    # But leave double-underscore names (dunder) intact.
    if name != "_" and name.startswith("_") and not name.startswith("__"):
        name = name[1:]
    return name


@method(pattern_wildcard)
def to_nim(self):
    """pattern_wildcard: '_' (wildcard) -> Nim: '_'"""
    return "_"


@method(pattern_others)
def to_nim(self):
    """pattern_others: 'others' (default branch) -> Nim: 'else'"""
    return "others"


@method(pattern_range)
def to_nim(self):
    """pattern_range: expression '..' expression (range pattern) -> Nim: 'lo .. hi'"""
    lo = self.nodes[0].to_nim()
    hi = self.nodes[-1].to_nim()
    return f"{lo} .. {hi}"


@method(pattern_group)
def to_nim(self):
    """pattern_group: '(' pattern ')' -> Nim: '(pattern)'"""
    return f"({self.nodes[0].to_nim()})"


@method(pattern_sequence)
def to_nim(self):
    """pattern_sequence: '[' pattern (',' pattern)* ']' -> Nim: '@[p1, p2, ...]'"""
    parts = [self.nodes[0].to_nim()]
    for node in self.nodes[1:]:
        if type(node).__name__ == "Several_Times" and node.nodes:
            for seq in node.nodes:
                if hasattr(seq, "nodes") and seq.nodes:
                    parts.append(seq.nodes[0].to_nim())
    return f"@[{', '.join(parts)}]"


@method(pattern_or)
def to_nim(self):
    """pattern_or: pattern ('|' pattern)+ -> Nim: 'p1, p2, ...' (Nim of-branch alternatives)"""
    parts = [self.nodes[0].to_nim()]
    for node in self.nodes[1:]:
        if type(node).__name__ == "Several_Times" and node.nodes:
            for seq in node.nodes:
                if hasattr(seq, "nodes") and len(seq.nodes) >= 2:
                    parts.append(seq.nodes[1].to_nim())
    return ", ".join(parts)


@method(pattern_value)
def to_nim(self):
    """pattern_value: IDENTIFIER ('.' IDENTIFIER)+ (attribute pattern) -> Nim: dotted name"""
    parts = [self.nodes[0].to_nim()]
    for node in self.nodes[1:]:
        if type(node).__name__ == "Several_Times" and node.nodes:
            for seq in node.nodes:
                if hasattr(seq, "nodes") and len(seq.nodes) >= 2:
                    parts.append(seq.nodes[1].to_nim())
    return ".".join(parts)


@method(keyword_pattern)
def to_nim(self):
    """keyword_pattern: IDENTIFIER '=' pattern -> Nim: 'field = pattern' in class pattern"""
    return f"{self.nodes[0].to_nim()} = {self.nodes[1].to_nim()}"


@method(pattern_class_arg)
def to_nim(self):
    """pattern_class_arg: pattern (positional or keyword) -> Nim: inner pattern"""
    return self.nodes[0].to_nim()


@method(pattern_class)
def to_nim(self):
    """pattern_class: IDENTIFIER '(' pattern_class_arg* ')' -> Nim: class pattern"""
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
    """pattern_mapping: '{' key ':' pattern ... '}' -> Nim: table match (approximated)"""
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
    """base_pattern: pattern_sequence | pattern_mapping | pattern_class | pattern_or | pattern_value | pattern_capture | pattern_wildcard | pattern_literal | pattern_group"""
    return self.nodes[0].to_nim()


@method(pattern_as)
def to_nim(self):
    """pattern_as: pattern 'as' IDENTIFIER -> Nim: 'pattern as name'"""
    pat = self.nodes[0].to_nim()
    name = self.nodes[1].to_nim()
    return f"{pat} as {name}"


@method(pattern)
def to_nim(self):
    """pattern: pattern_as | base_pattern"""
    return self.nodes[0].to_nim()


@method(case_guard)
def to_nim(self):
    """case_guard: 'if' expression (match guard) -> Nim: ' if expr'"""
    return f" if {self.nodes[0].to_nim()}"


@method(when_clause)
def to_nim(self, indent=0):
    """when_clause: 'when' pattern case_guard? ':' block -> Nim: 'of pattern (if guard):\n  body'"""
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
    # Option[T] param with None default: nil -> none(T)
    if default == " = nil" and "Option[" in nim_type:
        import re as _re
        m = _re.search(r"Option\[(.+)\]", nim_type)
        if m:
            default = f" = none({m.group(1)})"
            ParserState.nim_imports.add("options")
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
    """param_slash: '/' (positional-only separator, Python 3.8+) -> Nim: omitted (no equivalent)"""
    # Nim has no positional-only separator — omit
    return ""


@method(param)
def to_nim(self):
    """param: param_star | param_dstar | param_slash | param_kw | param_pos -> Nim: single parameter"""
    return self.nodes[0].to_nim()


@method(param_list)
def to_nim(self):
    """param_list: param (',' param)* -> Nim: ', '.join(non-empty param strings)"""
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
    """decorator: '@' dotted_name ['(' arguments? ')'] NL -> Nim: pragmas where known (e.g. @property, @staticmethod); others kept as comments"""
    # Nim uses pragmas {.decorator.} — keep @ syntax as best-effort
    return f"{_ind(indent)}@{self.nodes[0].to_nim()}"


@method(decorators)
def to_nim(self, indent=0):
    """decorators: decorator+ -> Nim: collected decorator lines preceding the proc/type definition"""
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
    # Strip trailing bare result -- Nim implicit return variable makes it redundant
    if ret_ann and body:
        _blines = body.rstrip().splitlines()
        if _blines and _blines[-1].strip() == "result":
            body = chr(10).join(_blines[:-1]) + chr(10)
    _shadow_vars = []
    # Add var to params that are mutated in body (assigned to or .add called)
    if params and body:
        import re as _re
        new_params = []
        for p in params.split(", "):
            pname = p.split(":")[0].strip()
            if pname and pname != "self" and _re.search(
                rf"(?<![=(,.])\b{_re.escape(pname)}\b\s*(\.add\(|\[.*\]\s*=(?!=)|[+\-*/]=|=(?!=))", body
            ):
                if " = " in p:
                    _shadow_vars.append(pname)
                elif not p.startswith("var ") and ": " in p:
                    # Nim syntax: param: var T
                    parts = p.split(": ", 1)
                    p = parts[0] + ": var " + parts[1]
            new_params.append(p)
        params = ", ".join(new_params)
        if _shadow_vars:
            _sv_indent = " " * (4 * (indent + 1))
            _sv_lines = "\n".join(f"{_sv_indent}var {sv} = {sv}" for sv in _shadow_vars)
            body = _sv_lines + "\n" + body
    # -- Method hoisting ------------------------------------------------
    # Nim forbids `method` declarations inside procs.  When an Adascript
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
            return f"{hoisted_block}{decos}{_ind(indent)}proc {name}({params}){ret_ann} ={hc}\n{body}"
    # Translate dunder method names to Nim operator procs
    nim_name, nim_keyword = _nim_proc_name(name)
    if nim_name is None:
        return ""  # skip (e.g. __init__ handled via class_def)
    keyword = nim_keyword or "proc"
    _exp = "*" if getattr(ParserState, 'export_symbols', False) and indent == 0 else ""
    # Infer generic type params from parameter/return type annotations.
    # Single uppercase-letter identifiers (S, D, C, T, K, V …) are type
    # variables by Adascript convention; collect them and add [S, D, C] to
    # the proc signature so Nim accepts the generic proc.
    import re as _re_gp
    _gp_candidates = set(_re_gp.findall(r'\b([A-Z])\b', params + " " + ret_ann))
    _generic_params = "[" + ", ".join(sorted(_gp_candidates)) + "]" if _gp_candidates else ""
    return f"{decos}{_ind(indent)}{keyword} {nim_name}{_exp}{_generic_params}({params}){ret_ann} ={hc}\n{body}"


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

    has_virtual_deco = False
    for node in self.nodes:
        tname = type(node).__name__
        if tname == "decorators":
            decos_str = node.to_nim(indent)
            # Strip @virtual — it controls ref/object, not a real Nim decorator
            if "@virtual" not in decos_str:
                decos = decos_str + "\n"
            else:
                has_virtual_deco = True
        elif tname == "Several_Times":
            for seq in node.nodes:
                stname = type(seq).__name__
                if stname == "decorator":
                    deco_str = seq.to_nim(indent)
                    if "@virtual" not in deco_str:
                        decos += deco_str + "\n"
                    else:
                        has_virtual_deco = True
                elif stname == "decorators":
                    decos_str = seq.to_nim(indent)
                    if "@virtual" not in decos_str:
                        decos = decos_str + "\n"
                    else:
                        has_virtual_deco = True
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

    # Infer virtual from class hierarchy or explicit @virtual decorator
    is_virtual = has_virtual_deco or name in getattr(ParserState, "_ref_classes", set())

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
    _exp = "*" if getattr(ParserState, 'export_symbols', False) and indent == 0 else ""
    ParserState.symbol_table.pop_scope()
    return f"{decos}{_ind(indent)}type {name}{_exp}{type_params} = {ref_keyword}object{parent}\n{body}"


# --- Type block forms (tuple, record) ---

def _extract_fields_from_block(block_node, indent):
    """Extract field declarations from a block, returning indented Nim field lines.
    Strips var/let/const keywords and default values (same as class field extraction).
    Also strips export markers (*) from field names: tuple fields cannot be exported."""
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
                                # Strip export marker from field name (tuple fields can't be exported)
                                line = _re.sub(r'^(\s*\w+)\*:', r'\1:', line)
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
    _exp = "*" if getattr(ParserState, 'export_symbols', False) and indent == 0 else ""
    if variant_case_node and discrim_name:
        # Discriminated record -> Nim object with case
        result = f"{_ind(indent)}type {name}{_exp}{params} = object\n"
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
    # Register type kind and field order for constructor translation
    ParserState.symbol_table.add(name, nim_kind, "type")
    import re as _re
    field_names = []
    field_types_list = []
    for fline in fields:
        fm = _re.match(r'\s*(\w+)\s*:\s*(.+)', fline)
        if fm:
            field_names.append(fm.group(1))
            field_types_list.append(fm.group(2).strip())
    if name not in ParserState.class_field_types:
        ParserState.class_field_types[name] = {}
    for fn, ft in zip(field_names, field_types_list):
        ParserState.class_field_types[name][fn] = ft
    if not hasattr(ParserState, 'tuple_field_order'):
        ParserState.tuple_field_order = {}
    if nim_kind == "tuple":
        # Tuples: positional constructor -> (field: val, ...)
        ParserState.tuple_field_order[name] = field_names
    else:
        # Objects: positional constructor -> TypeName(field: val, ...)
        if not hasattr(ParserState, 'object_field_order'):
            ParserState.object_field_order = {}
        ParserState.object_field_order[name] = field_names
    return f"{_ind(indent)}type {name}{_exp}{params} = {nim_kind}\n" + "\n".join(fields)



@method(class_args)
def to_nim(self):
    """class_args: '(' bases? ')' (class inheritance list) -> Nim: base class name for 'ref object of Base'"""
    st = self.nodes[0]
    if hasattr(st, "nodes") and st.nodes:
        args_node = st.nodes[0]
        return f"({args_node.to_nim()})"
    return "()"


# --- Async for / with ---
@method(async_for_stmt)
def to_nim(self, indent=0):
    """async_for_stmt: 'async' 'for' for_target 'in' expression ':' block -> Nim: plain 'for' loop (async annotation kept as comment)"""
    target = self.nodes[0].to_nim()
    iterable = self.nodes[1].to_nim()
    hc = _block_inline_header_comment(self.nodes[2])
    body = self.nodes[2].to_nim(indent + 1)
    return f"{_ind(indent)}for {target} in {iterable}:{hc}  # async\n{body}"


@method(async_with_stmt)
def to_nim(self, indent=0):
    """async_with_stmt: 'async' 'with' with_item (',' with_item)* ':' block -> Nim: plain 'with' (async annotation kept as comment)"""
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


# ---------------------------------------------------------------------------
# Shell statement — to_nim()
# ---------------------------------------------------------------------------
# Reuse the Python-backend helpers by importing them. They live in
# hek_py3_parser which is already on the import path via hek_nim_parser's
# sys.path setup.  We import lazily inside the method to avoid a circular
# import at module load time.

@method(shell_stmt)
def to_nim(self, indent=0):
    """shell_stmt: [decl_keyword IDENTIFIER '='] ('shell'|'shellLines') [shell_opts] ':' cmd+

    Nim output:
      import osproc  (auto-inserted via ParserState.nim_imports)
      import strformat  (when {var} interpolation is used)

      # shell: cmd
      discard execCmd(\"cmd\")

      # let result = shell: cmd
      let _r = execCmdEx(\"cmd\")
      let result = (output: _r[0], code: _r[1])

      # let lines = shellLines: cmd
      let _r = execCmdEx(\"cmd\")
      let lines = _r[0].splitLines()

    Options:
      cwd=\"/tmp\"     -> command is prefixed with \"cd /tmp && \"
      timeout=5000   -> comment added; execCmdEx has no timeout parameter
    """
    # Import helpers from Python backend (grammar-neutral extraction utilities)
    import sys as _sys, os as _os
    _to_py_dir = _os.path.join(_os.path.dirname(__file__), '..', 'TO_PYTHON')
    if _to_py_dir not in _sys.path:
        _sys.path.insert(0, _to_py_dir)
    from hek_py3_parser import _parse_shell_stmt

    ind = _ind(indent)
    target_kw, target_name, target_tuple, kw, opts, cmd, needs_fstring = _parse_shell_stmt(self)

    ParserState.nim_imports.add("osproc")

    # cwd: prefix the command with "cd <dir> && "
    if "cwd" in opts:
        cwd_val = opts["cwd"].strip('"').strip("'")
        cmd = f"cd {cwd_val} && {cmd}"

    # timeout comment
    timeout_comment = ""
    if "timeout" in opts:
        timeout_comment = f"  # timeout: {opts['timeout']}ms (execCmdEx has no timeout)"

    import re as _re_env
    has_env_vars = bool(_re_env.search(r'__bash_env_\w+__', cmd))

    if needs_fstring:
        q = '"""'
        ParserState.nim_imports.add("strformat")
        cmd_str = f"fmt{q}{cmd}{q}"
    elif has_env_vars:
        # Use regular quotes so & getEnv(...) concatenation works
        q = '"'
        cmd_str = f"{q}{cmd}{q}"
    else:
        q = '"""'
        cmd_str = f"{q}{cmd}{q}"
    # Replace __bash_env_NAME__ placeholders with getEnv("NAME") concatenation
    def _subst_env(s):
        ParserState.nim_imports.add("os")
        return '" & getEnv("' + s.group(1) + '") & "'
    cmd_str = _re_env.sub(r'__bash_env_(\w+)__', _subst_env, cmd_str)
    # Clean up empty string fragments: "" & ... -> ... and ... & "" -> ...
    cmd_str = cmd_str.replace('"" & ', '').replace(' & ""', '')

    lines = []

    nim_kw = "let" if target_kw in (None, "let", "const") else "var"
    lines = []

    # execCmdEx slot types: 0→string (stdout), 1→int (exitCode), 2→string (stderr compat)
    _SLOT_TYPES = ["string", "int", "string"]

    # Use a unique temp name to avoid redefinition errors when multiple shell
    # statements appear in the same scope.
    _exec_count = getattr(ParserState, "_exec_result_count", 0)
    ParserState._exec_result_count = _exec_count + 1
    exec_tmp = f"execResult{_exec_count}"

    if target_tuple:
        # let (out, code) = shell: cmd        — 2-element
        # let (out, code, _) = shell: cmd     — 3-element (3rd slot is "" for compat)
        slots = [f"{exec_tmp}[0]", f"{exec_tmp}[1]", '""']
        # Emit the temp only if at least one non-_ slot needs it
        named = [(i, v) for i, v in enumerate(target_tuple) if v != "_"]
        if named:
            lines.append(f"{ind}let {exec_tmp} = execCmdEx({cmd_str}){timeout_comment}")
            for i, var_name in named:
                slot_type = _SLOT_TYPES[i] if i < len(_SLOT_TYPES) else "string"
                lines.append(f"{ind}{nim_kw} {var_name} = {slots[i]}")
                ParserState.symbol_table.add(var_name, slot_type, nim_kw)
        else:
            lines.append(f"{ind}discard execCmdEx({cmd_str}){timeout_comment}")
    elif target_name:
        if kw == "shellLines":
            # Inline directly — no temp needed
            ParserState.nim_imports.add("strutils")
            lines.append(f"{ind}{nim_kw} {target_name} = execCmdEx({cmd_str}){timeout_comment}[0].splitLines()")
            ParserState.symbol_table.add(target_name, "seq[string]", nim_kw)
        else:
            lines.append(f"{ind}let {exec_tmp} = execCmdEx({cmd_str}){timeout_comment}")
            lines.append(
                f"{ind}{nim_kw} {target_name} = (output: {exec_tmp}[0], code: {exec_tmp}[1])"
            )
            # Register as shell_result so _nim_truthiness can resolve
            # field access like result.output -> result.output.len > 0
            ParserState.symbol_table.add(target_name, "shell_result", nim_kw)
    elif kw == "shellLines":
        ParserState.nim_imports.add("strutils")
        lines.append(f"{ind}return execCmdEx({cmd_str}){timeout_comment}[0].splitLines()")
    else:
        lines.append(f"{ind}discard execCmd({cmd_str}){timeout_comment}")

    return "\n".join(lines)


# --- compound_stmt ---
@method(compound_stmt)
def to_nim(self, indent=0):
    """compound_stmt: if_stmt | while_stmt | for_stmt | try_stmt | with_stmt | match_stmt | func_def | class_def | decorated_def | async_func_def | async_for_stmt | async_with_stmt | shell_stmt"""
    return self.nodes[0].to_nim(indent)


# --- stmt_line (override from hek_nim_stmt to call to_nim recursively) ---
@method(stmt_line)
def to_nim(self, indent=0):
    """stmt_line: simple_stmt NL -> Nim: simple statement line"""
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
                                val = child.to_nim()
                                if val is not None:
                                    parts.append(_ind(indent) + val)
        elif hasattr(node, "to_nim"):
            try:
                val = node.to_nim(indent)
                if val is not None:
                    parts.append(val)
            except TypeError:
                val = node.to_nim()
                if val is not None:
                    parts.append(_ind(indent) + val)

    if not parts:
        parts = [_ind(indent) + self.nodes[0].to_nim()]

    result = "; ".join(p.strip() for p in parts if p.strip())
    # Bare print (no args) -> echo "" (empty line)
    if result == "echo":
        result = 'echo ""'
    # Convert bare string literals (docstrings) to Nim doc comments
    non_empty = [p for p in parts if p.strip()]
    if len(non_empty) == 1:
        r = result.strip()
        if r and len(r) >= 2 and r[0] == r[-1] and r[0] in ('"', "'"):
            result = _ind(indent) + '## ' + r[1:-1]
        else:
            result = _ind(indent) + result
    else:
        result = _ind(indent) + result

    # Multiline results (e.g. ## docstrings from STRING.to_nim()) have the
    # indent prefix only on the first line.  Re-apply it to every subsequent
    # non-empty line so the generated Nim is properly indented.
    if '\n' in result:
        _lines = result.split('\n')
        _fixed = [_lines[0]]
        for _l in _lines[1:]:
            _fixed.append(_ind(indent) + _l.lstrip() if _l.strip() else '')
        result = '\n'.join(_fixed)
    if newline_node is not None and hasattr(newline_node, 'comments') and newline_node.comments:
        for kind, text, ind in newline_node.comments:
            if kind == 'comment':
                result += '  ' + text
    return result


###############################################################################
# Tests
###############################################################################


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

    # Register parameter types for call-site Option[T] coercion
    new_name_key = f"new{class_name}"
    param_types_list = []
    for ps in param_strs:
        import re as _re2
        m2 = _re2.match(r'\w+\s*:\s*(.+?)(?:\s*=.*)?$', ps.strip())
        param_types_list.append(m2.group(1).strip() if m2 else "")
    ParserState.proc_param_types[new_name_key] = param_types_list
    # Store full param strings (name: type = default) for forwarding constructors
    ParserState.proc_param_types_full[new_name_key] = list(param_strs)

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
    """Generate method declaration. Uses 'method' for virtual, 'proc' for non-virtual.
    A @proc decorator on the method forces 'proc' emission and is stripped from output,
    making it transparent to the user (no explicit self-type, no out-of-class placement).
    """
    lines = []

    name = ""
    params = []
    ret_ann = ""
    block_node = None
    force_proc = False   # set when @proc decorator is present
    extra_decos = []     # non-@proc decorators to keep

    # Pre-scan for @proc decorator before the main node loop.
    # func_def grammar: decorators[:] + ikw("def") + IDENTIFIER + ... + block
    # The optional decorators group is wrapped in Several_Times, which in turn
    # may contain a `decorators` node or individual `decorator` nodes.
    def _extract_deco_names(node):
        """Recursively yield (node, text) for all decorator nodes found."""
        tname = type(node).__name__
        if tname == "decorator":
            if hasattr(node, "to_nim"):
                try:
                    txt = node.to_nim(indent).strip()
                except TypeError:
                    txt = node.to_nim().strip()
                yield node, txt
        elif tname in ("decorators", "Several_Times", "Sequence_Parser"):
            if hasattr(node, "nodes"):
                for child in node.nodes:
                    yield from _extract_deco_names(child)

    for node in func_node.nodes:
        for deco_node, deco_text in _extract_deco_names(node):
            if deco_text == "@proc":
                force_proc = True
            else:
                extra_decos.append(deco_text)

    for node in func_node.nodes:
        tname = type(node).__name__
        if tname == "decorators":
            pass  # already handled above
        elif tname == "IDENTIFIER":
            name = str(node.nodes[0])
        elif tname == "Several_Times":
            for st in node.nodes:
                st_name = type(st).__name__
                if st_name == "param_list":
                    for p in st.nodes:
                        ptype_name = type(p).__name__
                        param_nodes = []
                        if ptype_name == "param_plain":
                            param_nodes.append(("plain", p))
                        elif ptype_name == "param_star":
                            param_nodes.append(("star", p))
                        elif ptype_name == "Several_Times":
                            for st_child in p.nodes:
                                if type(st_child).__name__ == "Sequence_Parser":
                                    for sp_child in st_child.nodes:
                                        if type(sp_child).__name__ == "param_plain":
                                            param_nodes.append(("plain", sp_child))
                                        elif type(sp_child).__name__ == "param_star":
                                            param_nodes.append(("star", sp_child))
                        for param_kind, param_node in param_nodes:
                            if param_kind == "star":
                                star_str = param_node.to_nim()
                                if star_str:
                                    params.append(star_str)
                                continue
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
    _shadow_vars = []
    if params and body_text:
        import re as _re
        # Strip comment lines so docstrings don't trigger false mutation detection
        _body_no_comments = "\n".join(
            line for line in body_lines if not line.lstrip().startswith("#")
        )
        # For non-virtual classes, promote self to var if body mutates any self.field
        # or calls any self.method() (which may itself be a mutating proc).
        if not is_virtual and class_name and _re.search(
            r"self\.\w+\s*(\.add\(|\[.*\]\s*=(?!=)|[+\-*/]=|=(?!=)|\()", _body_no_comments
        ):
            params = [
                f"self: var {class_name}{type_params}" if p.startswith(f"self: {class_name}") else p
                for p in params
            ]
        new_params = []
        for p in params:
            pname = p.split(":")[0].strip()
            if pname and pname != "self" and _re.search(
                rf"(?<![=(,.])\b{_re.escape(pname)}\b\s*(\.add\(|\[.*\]\s*=(?!=)|[+\-*/]=|=(?!=))", _body_no_comments
            ):
                if " = " in p:
                    _shadow_vars.append(pname)
                elif not p.startswith("var ") and ": " in p:
                    # Nim syntax: param: var T
                    parts = p.split(": ", 1)
                    p = parts[0] + ": var " + parts[1]
            new_params.append(p)
        params = new_params
        if _shadow_vars:
            _sv_indent = " " * (4 * (indent + 1))
            for sv in _shadow_vars:
                body_lines.insert(0, f"{_sv_indent}var {sv} = {sv}")
            body_text = "\n".join(body_lines)

    params_str = ", ".join(params)
    # Detect if body contains yield -> use iterator instead of proc/method
    has_yield = any("yield " in line or line.strip() == "yield" for line in body_lines)
    if has_yield:
        pragma = ""
        keyword = "iterator"
        if not ret_ann:
            ret_ann = ": auto"
    elif force_proc:
        # @proc decorator: user explicitly opts out of virtual dispatch for this
        # method.  Emit as a plain proc — no {.base.} pragma needed.
        pragma = ""
        keyword = "proc"
    elif is_virtual:
        pragma = " {.base.}" if _is_new_method(class_name, name) else ""
        keyword = "method"
    else:
        pragma = ""
        keyword = "proc"

    generic_params = type_params if type_params else ""
    # Translate dunder names to Nim operator procs
    nim_name, nim_kw = _nim_proc_name(name)
    if nim_name is None:
        ParserState.symbol_table.pop_scope()
        ParserState._current_return_type = ""
        return []  # skip (e.g. __init__)
    if nim_kw == "iterator":
        keyword = "iterator"
        pragma = ""
    # Reflected operators: Python (self, other) -> Nim (other, self)
    if name in _REVERSED_DUNDERS and len(params) == 2:
        params_str = f"{params[1]}, {params[0]}"
    # __call__ requires the callOperator experimental feature
    if name == "__call__":
        ParserState.nim_pragmas.add('experimental: "callOperator"')
    deco_prefix = ("\n".join(extra_decos) + "\n") if extra_decos else ""
    _exp = "*" if getattr(ParserState, 'export_symbols', False) and indent == 0 else ""
    method_sig = f"{deco_prefix}{_ind(indent)}{keyword} {nim_name}{_exp}{generic_params}({params_str}){ret_ann}{pragma} ="
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
            "type Foo = object of RootObj\nproc newFoo*(): Foo =\n    result = Foo()",
        ),
        (
            "class Foo(Bar):\n    pass\n",
            "type Foo = object of Bar\nproc newFoo*(): Foo =\n    result = Foo()",
        ),
        # --- __call__ and __ror__ (pipe operator) ---
        (
            "class Style:\n    var on: str\n    def __call__(self, *args: str) -> str:\n        return self.on\n    def __ror__(self, other: str) -> str:\n        return self(other)\n",
            'type Style = object of RootObj\n    on: string\n\nproc newStyle*(): Style =\n    result = Style()\nproc `()`(self: Style, args: varargs[string]): string =\n    return self.on\nproc `|`(other: string, self: Style): string =\n    return self(other)',
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

