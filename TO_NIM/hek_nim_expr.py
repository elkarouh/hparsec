#!/usr/bin/env python3
"""Nim translation methods for Python 3.14 expressions.

Adds to_nim() methods to the expression parser classes defined in
hek_py3_expr.py. Import this module to enable .to_nim() on expression AST nodes.

Usage:
    from hek_nim_expr import *
    ast = parse_expr("1 + 2 * 3")
    print(ast.to_nim())  # 1 + 2 * 3

    ast = parse_expr("x ** 2")
    print(ast.to_nim())  # x ^ 2
"""

import sys, os
_dir = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(_dir, ".."))
sys.path.insert(0, os.path.join(_dir, "..", "HPYTHON_GRAMMAR"))
# (no TO_PYTHON dependency needed)

from hek_parsec import method, ParserState
from py3expr import *
from hek_nim_declarations import _is_nim_ordinal  # noqa: F403 — need all parser rule names
from py3expr import (
    PREC_WALRUS, PREC_CONDITIONAL, PREC_OR, PREC_AND, PREC_NOT,
    PREC_CMP, PREC_BOR, PREC_BXOR, PREC_BAND, PREC_SHIFT,
    PREC_ARITH, PREC_TERM, PREC_UNARY, PREC_POWER, PREC_ATOM,
    parse_expr,
)

_COMP_OPS = {"==", "!=", "<", ">", "<=", ">=", "in", "is", "not in", "is not", "isnot", "notin"}

def _nim_truthiness(expr):
    """Convert Python truthiness expression to explicit Nim boolean.
    Strings/seqs have no implicit bool conversion in Nim."""
    sym = ParserState.symbol_table.lookup(expr)
    if sym:
        t = (sym.get("type") or "")
        if any(t.startswith(p) for p in ("string", "seq[", "str", "PriorityQueue", "FifoQueue", "LifoQueue", "HashSet", "Table", "Deque")):
            return f"{expr}.len > 0"
    return expr



###############################################################################
# Type inference helpers
###############################################################################

def _infer_literal_nim_type(node):
    """Try to infer the Nim type of a literal expression node.

    Returns the Nim type string or None if unknown.
    Walks through wrapper nodes (atom, expression, etc.) to find the leaf.
    """
    # Unwrap single-child wrapper nodes
    while hasattr(node, 'nodes') and len(node.nodes) == 1:
        node = node.nodes[0]

    # Fmap node holding a string literal value
    if type(node).__name__ == 'Fmap':
        val = node.nodes[0] if hasattr(node, 'nodes') and node.nodes else None
        if isinstance(val, str):
            if val in ('True', 'False'):
                return 'bool'
            if val == 'None':
                return 'void'
            # Check if it looks like a number
            try:
                int(val)
                return 'int'
            except ValueError:
                pass
            try:
                float(val)
                return 'float'
            except ValueError:
                pass
            # Quoted string
            if len(val) >= 2 and val[0] in ("'"  , '"'):
                return 'string'
        return None

    # If node is a string directly (from Fmap extraction)
    if isinstance(node, str):
        if node in ('True', 'False'):
            return 'bool'
        if node == 'None':
            return 'void'
        try:
            int(node)
            return 'int'
        except ValueError:
            pass
        try:
            float(node)
            return 'float'
        except ValueError:
            pass
        if len(node) >= 2 and node[0] in ("'" , '"'):
            return 'string'
        return None

    return None


###############################################################################
# to_nim() methods
###############################################################################

# Operator translation map: Python operator string -> Nim operator string
_PY_OP_TO_NIM = {
    "**": "^",
    "//": "div",
    "%": "mod",
    "@": "@",  # matmul — no Nim equivalent
    "<<": "shl",
    ">>": "shr",
    "&": "and",
    "|": "or",
    "^": "xor",
    "~": "not",
    "not in": "notin",
    "is not": "isnot",
    ":=": "=",  # walrus -> assignment
    # These stay the same:
    "+": "+", "-": "-", "*": "*", "/": "/",
    "==": "==", "!=": "!=", "<": "<", ">": ">", "<=": "<=", ">=": ">=",
    "and": "and", "or": "or", "not": "not", "in": "in", "is": "is",
}


def _op_string(node):
    """Extract operator string from a simple or compound operator node."""
    if isinstance(node.node, str):
        return node.node
    return node.to_nim()


def binop_to_nim(self, prec=None, my_prec=None):
    """Generic to_nim for left-associative binary operators.
    Parallel to binop_to_py but calls to_nim() recursively and translates operators."""
    last_st_idx = None
    for i in range(len(self.nodes) - 1, -1, -1):
        node = self.nodes[i]
        if (
            type(node).__name__ == "Several_Times"
            and hasattr(node, "nodes")
            and node.nodes
        ):
            first_seq = node.nodes[0]
            if hasattr(first_seq, "nodes") and len(first_seq.nodes) >= 2:
                last_st_idx = i
                break

    if last_st_idx is None:
        return self.nodes[0].to_nim(prec)

    left_prec = my_prec
    if last_st_idx == 1:
        result = self.nodes[0].to_nim(left_prec)
    else:
        class _Mock:
            pass
        mock = _Mock()
        mock.nodes = self.nodes[:last_st_idx]
        result = binop_to_nim(mock, left_prec, my_prec)

    right_prec = my_prec + 1 if my_prec is not None else None
    st = self.nodes[last_st_idx]
    for seq in st.nodes:
        if hasattr(seq, "nodes") and len(seq.nodes) >= 2:
            py_op = _op_string(seq.nodes[0])
            nim_op = _PY_OP_TO_NIM.get(py_op, py_op)
            right = seq.nodes[1].to_nim(right_prec)
            # seq concatenation: + -> & when operand is a seq literal
            if nim_op == "+" and (right.startswith("@[") or result.startswith("@[")):
                nim_op = "&"
            result = f"{result} {nim_op} {right}"

    if prec is not None and my_prec is not None and my_prec < prec:
        return f"({result})"
    return result


# --- leaf tokens: to_nim ---
@method(NUMBER)
def to_nim(self, prec=None):
    return self.node


@method(STRING)
def to_nim(self, prec=None):
    s = self.node
    # Convert triple-quoted strings to Nim ## comments
    triple_dq = chr(34)*3
    triple_sq = chr(39)*3
    if s.startswith(triple_dq) or s.startswith(triple_sq):
        inner = s[3:-3]
        comment_lines = ["## " + line for line in inner.strip().splitlines()]
        return chr(10).join(comment_lines)
    # Nim uses double quotes for strings; single quotes are char literals
    if s.startswith(chr(39)) and s.endswith(chr(39)) and len(s) > 2:
        inner = s[1:-1]
        inner = inner.replace(chr(34), chr(92) + chr(34))
        return chr(34) + inner + chr(34)
    return s



_PY_IDENT_TO_NIM = {
    "print": "echo",
    "str": "string",
    "list": "seq",
    "len": "len",
    "int": "int",
    "float": "float",
    "bool": "bool",
    "abs": "abs",
    "min": "min",
    "max": "max",
}

@method(IDENTIFIER)
def to_nim(self, prec=None):
    name = self.node
    # Resolve tick attributes: Type__tick__Attr -> Nim equivalent
    if "__tick__" in name:
        type_name, _, attr = name.partition("__tick__")
        info = ParserState.tick_types.get(type_name)
        if info:
            if attr == "First":
                return str(info["First"])
            elif attr == "Last":
                return str(info["Last"])
        # Ada tick attributes for enum operations
        if attr == "Next":
            return type_name + ".succ"
        elif attr == "Prev":
            return type_name + ".pred"
    return _PY_IDENT_TO_NIM.get(name, name)


@method(K_NONE)
def to_nim(self, prec=None):
    return "nil"


@method(K_TRUE)
def to_nim(self, prec=None):
    return "true"


@method(K_FALSE)
def to_nim(self, prec=None):
    return "false"


@method(ellipsis_lit)
def to_nim(self, prec=None):
    return "..."


# Visible operators — return Nim-translated string
for _p in [
    V_PLUS, V_MINUS, V_STAR, V_SLASH, V_PERCENT, V_DSLASH, V_DSTAR,
    V_TILDE, V_AT, V_PIPE, V_CARET, V_AMPER, V_LSHIFT, V_RSHIFT,
    V_LT, V_GT, V_EQ, V_NE, V_LE, V_GE, V_COLONEQUAL,
    SSTAR, K_AND, K_OR, K_NOT, K_IN, K_IS,
]:
    @method(_p)
    def to_nim(self, prec=None):
        return _PY_OP_TO_NIM.get(self.node, self.node)


@method(V_COLON)
def to_nim(self, prec=None):
    return ":"


@method(not_in_op)
def to_nim(self, prec=None):
    return "notin"


@method(is_not_op)
def to_nim(self, prec=None):
    return "isnot"


@method(comp_op)
def to_nim(self, prec=None):
    return self.nodes[0].to_nim()


# --- fstring ---
@method(fstring)
def to_nim(self, prec=None):
    """f-string -> Nim fmt string: replace f-string prefix with fmt"""
    ParserState.nim_imports.add("strformat")
    parts = []
    def _collect(node):
        tname = type(node).__name__
        if tname == "Fmap":
            parts.append(node.node)
        elif tname in ("Several_Times", "Sequence_Parser"):
            for child in node.nodes:
                _collect(child)
        elif hasattr(node, "to_nim"):
            parts.append(node.to_nim())
        elif hasattr(node, "node"):
            parts.append(node.node)
    for node in self.nodes:
        _collect(node)
    result = "".join(parts)
    # Replace f" or f' prefix with fmt"
    if result.startswith(("f\"", "f\'")):
        result = "fmt" + result[1:]
    elif result.startswith(("F\"", "F\'")):
        result = "fmt" + result[1:]
    return result


# --- str_concat ---
@method(str_concat)
def to_nim(self, prec=None):
    parts = [self.nodes[0].to_nim()]
    rep = self.nodes[1]
    if hasattr(rep, "nodes"):
        parts.extend(n.to_nim() for n in rep.nodes)
    else:
        parts.append(rep.to_nim())
    return " & ".join(parts)


# --- atom containers ---
@method(empty_paren)
def to_nim(self, prec=None):
    return "()"


@method(paren_group)
def to_nim(self, prec=None):
    return f"({self.nodes[1].to_nim()})"


@method(empty_list)
def to_nim(self, prec=None):
    return "@[]"


@method(list_display)
def to_nim(self, prec=None):
    inner_node = self.nodes[1]
    # If inner is a listcomp, collect() handles it — no @[] wrapper
    if type(inner_node).__name__ == "listcomp":
        return inner_node.to_nim()
    return f"@[{inner_node.to_nim()}]"


@method(empty_dict)
def to_nim(self, prec=None):
    ParserState.nim_imports.add("tables")
    return "initTable()"


@method(dict_display)
def to_nim(self, prec=None):
    inner_node = self.nodes[1]
    if type(inner_node).__name__ == "dictcomp":
        return inner_node.to_nim()
    ParserState.nim_imports.add("tables")
    return "{" + inner_node.to_nim() + "}.toTable"


@method(enum_array_display)
def to_nim(self, prec=None):
    """[KEY: val, KEY: val] -> [val1, val2, ...] in enum declaration order."""
    inner_node = self.nodes[1]  # dictmaker
    # Extract key-value pairs from dictmaker AST
    def _extract_kv(node):
        pairs = []
        nodes = node.nodes if hasattr(node, "nodes") else []
        if len(nodes) >= 3:
            key_text = nodes[0].to_nim().strip()
            pairs.append((key_text, nodes[2]))
            for child in nodes[3:]:
                if type(child).__name__ == "Several_Times":
                    for seq in child.nodes:
                        kv = seq if type(seq).__name__ == "kvpair" else None
                        if kv is None and hasattr(seq, "nodes"):
                            for inner in seq.nodes:
                                if type(inner).__name__ == "kvpair":
                                    kv = inner
                                    break
                        if kv and hasattr(kv, "nodes") and len(kv.nodes) >= 3:
                            pairs.append((kv.nodes[0].to_nim().strip(), kv.nodes[2]))
        return pairs
    kv_pairs = _extract_kv(inner_node)
    if not kv_pairs:
        return "[]"
    # Find which enum the keys belong to
    first_key = kv_pairs[0][0]
    enum_members = None
    for tname, info in ParserState.tick_types.items():
        if "members" in info and first_key in info["members"]:
            enum_members = info["members"]
            break
    if enum_members:
        # Emit values in enum declaration order, default for missing members
        kv_dict = {k: v for k, v in kv_pairs}
        vals = []
        for m in enum_members:
            if m in kv_dict:
                vals.append(kv_dict[m].to_nim().strip())
            else:
                sample_val = kv_pairs[0][1].to_nim().strip()
                vals.append("default(typeof(" + sample_val + "))")
        return "[" + ", ".join(vals) + "]"
    # Fallback: emit values in order given
    vals = [v.to_nim().strip() for _, v in kv_pairs]
    return "[" + ", ".join(vals) + "]"


@method(set_display)
def to_nim(self, prec=None):
    inner_node = self.nodes[1]
    # If inner is a setcomp, collect() handles it — no {} wrapper
    if type(inner_node).__name__ == "setcomp":
        return inner_node.to_nim()
    # Infer element type from first element
    first_elem = inner_node.nodes[0] if hasattr(inner_node, "nodes") and inner_node.nodes else inner_node
    elem_type = _infer_literal_nim_type(first_elem)
    if elem_type and _is_nim_ordinal(elem_type):
        return "{" + inner_node.to_nim() + "}"
    return "{" + inner_node.to_nim() + "}.toHashSet"


@method(atom)
def to_nim(self, prec=None):
    return self.nodes[0].to_nim(prec)


# --- trailers ---
@method(call_trailer)
def to_nim(self, prec=None):
    if len(self.nodes) > 1 and hasattr(self.nodes[1], "nodes") and self.nodes[1].nodes:
        return "(" + self.nodes[1].nodes[0].to_nim() + ")"
    elif len(self.nodes) > 1 and hasattr(self.nodes[1], "to_nim"):
        return "(" + self.nodes[1].to_nim() + ")"
    return "()"


@method(slice_trailer)
def to_nim(self, prec=None):
    inner = self.nodes[0].to_nim()
    # Convert negative indexing: [-1] -> [^1], [-2] -> [^2], etc.
    import re as _re
    m = _re.match(r'^-(\d+)$', inner.strip())
    if m:
        return "[^" + m.group(1) + "]"
    return "[" + inner + "]"


# Type-aware method renaming: {nim_type_prefix: {py_method: nim_method}}
_PY_METHOD_TO_NIM = {
    "seq": {"append": "add"},
    "set": {"add": "incl", "remove": "excl"},
    "HashSet": {"add": "incl", "remove": "excl"},
    "Table": {"items": "pairs"},
    "string": {"lower": "toLowerAscii", "upper": "toUpperAscii",
               "strip": "strip", "split": "split", "join": "join",
               "startswith": "startsWith", "endswith": "endsWith",
               "replace": "replace", "find": "find"},
}

@method(attr_trailer)
def to_nim(self, prec=None):
    attr_name = self.nodes[0].to_nim()
    # Handle tick attributes on expressions: .field'Next -> .field.succ, .field'Prev -> .field.pred
    if "__tick__" in attr_name:
        base, _, tick_attr = attr_name.partition("__tick__")
        if tick_attr == "Next":
            return "." + base + ".succ"
        elif tick_attr == "Prev":
            return "." + base + ".pred"
    return "." + attr_name


@method(trailer)
def to_nim(self, prec=None):
    return self.nodes[0].to_nim()


_STRUTILS_METHODS = {"toLowerAscii", "toUpperAscii", "strip", "startsWith", "endsWith", "splitLines", "parseInt", "split", "join", "replace", "find"}

# Universal method mappings that apply regardless of receiver type
_PY_UNIVERSAL_METHOD_TO_NIM = {
    "append": "add",
    "extend": "add",
    "lower": "toLowerAscii",
    "upper": "toUpperAscii",
    "strip": "strip",
    "startswith": "startsWith",
    "endswith": "endsWith",
    "get": "getOrDefault",
}

def _translate_method(obj_name, method_name):
    """Translate a Python method name based on the object's type from the symbol table."""
    sym = ParserState.symbol_table.lookup(obj_name)
    if sym:
        type_str = sym.get("type", "") or ""
        for prefix, mappings in _PY_METHOD_TO_NIM.items():
            if type_str.startswith(prefix):
                return mappings.get(method_name, method_name)
    # Fall back to universal mappings
    nim_method = _PY_UNIVERSAL_METHOD_TO_NIM.get(method_name, method_name)
    if nim_method in _STRUTILS_METHODS:
        ParserState.nim_imports.add("strutils")
    return nim_method


def _extract_call_arg(call_node):
    """Extract the argument string from a call_trailer node."""
    if len(call_node.nodes) > 1 and hasattr(call_node.nodes[1], "nodes") and call_node.nodes[1].nodes:
        return call_node.nodes[1].nodes[0].to_nim()
    elif len(call_node.nodes) > 1 and hasattr(call_node.nodes[1], "to_nim"):
        return call_node.nodes[1].to_nim()
    return ""


def _extract_call_args(call_node):
    """Extract all argument strings from a call_trailer node as a list."""
    full = _extract_call_arg(call_node)
    if not full:
        return []
    # Split on top-level commas (not inside brackets/parens)
    args = []
    depth = 0
    current = []
    for ch in full:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == "," and depth == 0:
            args.append("".join(current).strip())
            current = []
            continue
        current.append(ch)
    if current:
        args.append("".join(current).strip())
    return args


@method(primary)
def to_nim(self, prec=None):
    result = self.nodes[0].to_nim()
    # Map Python builtin names to Nim equivalents
    raw_name = result
    result = _PY_IDENT_TO_NIM.get(result, result)
    # If this is a call to a known class name, add 'new' prefix for Nim constructor
    has_call = (len(self.nodes) > 1 and hasattr(self.nodes[1], "nodes")
                and self.nodes[1].nodes
                and type(self.nodes[1].nodes[0]).__name__ == "call_trailer")
    if has_call:
        # str(x) -> $x, list(x) -> @x
        if raw_name == "str":
            call_node = self.nodes[1].nodes[0]
            arg = _extract_call_arg(call_node)
            return "$" + arg
        if raw_name == "list":
            call_node = self.nodes[1].nodes[0]
            arg = _extract_call_arg(call_node)
            if arg:
                # list(x) — if x is already a seq, just return it (Nim copies on assign)
                # If x is not a seq (e.g. a range), use @x to convert
                sym = ParserState.symbol_table.lookup(arg)
                if sym and (sym.get("type") or "").startswith("seq["):
                    return arg
                return "@" + arg
            return "@[]"
        if raw_name == "set":
            call_node = self.nodes[1].nodes[0]
            arg = _extract_call_arg(call_node)
            if arg:
                return f"{arg}.toHashSet()"
            return "initHashSet()"
        if raw_name == "range":
            call_node = self.nodes[1].nodes[0]
            args = _extract_call_args(call_node)
            if len(args) == 1:
                return f"0 ..< {args[0]}"
            elif len(args) == 2:
                return f"{args[0]} ..< {args[1]}"
            elif len(args) == 3:
                return f"countup({args[0]}, {args[1]} - 1, {args[2]})"
            return "0 ..< 0"
        if raw_name == "int":
            call_node = self.nodes[1].nodes[0]
            arg = _extract_call_arg(call_node)
            return f"int({arg})"
        if raw_name == "log":
            call_node = self.nodes[1].nodes[0]
            args = _extract_call_args(call_node)
            ParserState.nim_imports.add("math")
            if len(args) == 1:
                return f"ln({args[0]})"
        # Map stdlib queue constructors to their Nim init functions
        _STDLIB_CTORS = {"PriorityQueue": ("initPriorityQueue", "newPriorityQueueWith"),
                         "FifoQueue": ("initFifoQueue", "newFifoQueueWith"),
                         "LifoQueue": ("initLifoQueue", "newLifoQueueWith")}
        # Only map to constructor if first trailer is a call_trailer (parentheses),
        # not a slice_trailer (brackets — used for type annotations like PriorityQueue[T])
        _first_trailer = self.nodes[1].nodes[0] if len(self.nodes) > 1 and hasattr(self.nodes[1], 'nodes') and self.nodes[1].nodes else None
        _is_call = _first_trailer is not None and type(_first_trailer).__name__ == "call_trailer"
        if raw_name in _STDLIB_CTORS and _is_call:
            # Check if constructor has arguments
            _ctor_no_args, _ctor_with_args = _STDLIB_CTORS[raw_name]
            call_node = _first_trailer

            has_args = call_node is not None and hasattr(call_node, 'nodes') and call_node.nodes
            # Check if args produce non-empty output (Filter nodes exist even for empty "()")
            if has_args:
                try:
                    args_str = call_node.to_nim()
                    has_args = args_str and args_str != "()"
                except Exception:
                    has_args = False
            result = _ctor_with_args if has_args else _ctor_no_args
        else:
            sym = ParserState.symbol_table.lookup(raw_name)
            if sym and sym.get("kind") == "class":
                result = "new" + raw_name
    base_name = result  # save for type-aware method lookup
    if len(self.nodes) > 1 and hasattr(self.nodes[1], "nodes") and self.nodes[1].nodes:
        for tr in self.nodes[1].nodes:
            if type(tr).__name__ == "attr_trailer":
                method_name = tr.nodes[0].to_nim()
                # Handle Ada tick attributes: field'Next -> field.succ, field'Prev -> field.pred
                if "__tick__" in method_name:
                    base_attr, _, tick_attr = method_name.partition("__tick__")
                    if tick_attr == "Next":
                        result += "." + base_attr + ".succ"
                        continue
                    elif tick_attr == "Prev":
                        result += "." + base_attr + ".pred"
                        continue
                method_name = _translate_method(base_name, method_name)
                result += "." + method_name
            else:
                result += tr.to_nim()
    # Post-process: translate known Python stdlib patterns to Nim
    result = _translate_stdlib_patterns(result)
    return result


# Python stdlib dotted-access patterns -> Nim equivalents
_STDLIB_PATTERNS = [
    # Order matters: longer patterns first
    ("os.path.exists", "fileExists"),
    ("time.perf_counter", "cpuTime"),
    ("time.time", "epochTime"),
    ("sys.exit", "quit"),
    ("sys.argv", "commandLineParams()"),
]

def _translate_stdlib_patterns(expr):
    if "fileExists" in expr or "paramStr" in expr or "paramCount" in expr:
        ParserState.nim_imports.add("os")
    for py_pattern, nim_equiv in _STDLIB_PATTERNS:
        if expr == py_pattern:
            return nim_equiv
        if expr.startswith(py_pattern + "("):
            return nim_equiv + expr[len(py_pattern):]
        # sys.argv[N] -> paramStr(N)
        if expr.startswith(py_pattern + "[") and py_pattern == "sys.argv":
            idx = expr[len("sys.argv["):-1]
            return f"paramStr({idx})"
    # len(sys.argv) -> paramCount() + 1 (Python includes program name)
    if "len(sys.argv)" in expr:
        expr = expr.replace("len(sys.argv)", "(paramCount() + 1)")
    if "len(commandLineParams())" in expr:
        expr = expr.replace("len(commandLineParams())", "(paramCount() + 1)")
    # 'sep'.join(x) -> x.join("sep") — Python join has receiver/arg swapped vs Nim
    import re as _re
    m = _re.match(r"^(.+)\.join\((.+)\)$", expr)
    if m:
        sep, arg = m.group(1), m.group(2)
        ParserState.nim_imports.add("strutils")
        # Nim join needs string sep — use $'c' for single-char (safe inside fmt)
        if len(sep) == 3 and sep[0] == "'" and sep[-1] == "'":
            sep = "$" + sep
        elif len(sep) == 3 and sep[0] == '"' and sep[-1] == '"':
            sep = "$'" + sep[1] + "'"
        return f"{arg}.join({sep})"

    # f.readlines() -> f.readAll().splitLines()
    if expr.endswith(".readlines()"):
        obj = expr[:-len(".readlines()")]
        ParserState.nim_imports.add("strutils")
        return f"{obj}.readAll().splitLines()"
    return expr


# --- await ---
@method(await_expr)
def to_nim(self, prec=None):
    return f"await {self.nodes[0].to_nim()}"


@method(await_primary)
def to_nim(self, prec=None):
    return self.nodes[0].to_nim(prec)


# --- range expression (.., ..<) ---
@method(range_incl_op)
def to_nim(self, prec=None):
    return ".."

@method(range_excl_op)
def to_nim(self, prec=None):
    return "..<"

@method(range_expr)
def to_nim(self, prec=None):
    # range_expr: bitor_expr (('..' | '..<') bitor_expr)*
    result = self.nodes[0].to_nim(prec)
    for node in self.nodes[1:]:
        if not hasattr(node, 'nodes') or not node.nodes:
            continue
        for seq in node.nodes:
            tname = type(seq).__name__
            if tname in ("range_incl_op", "range_excl_op", "Sequence_Parser"):
                result += " " + seq.to_nim(prec) + " "
            else:
                result += seq.to_nim(prec)
    return result


# --- power ---
@method(power_rhs)
def to_nim(self, prec=None):
    return f"^ {self.nodes[1].to_nim(prec)}"


@method(power)
def to_nim(self, prec=None):
    has_power = False
    for node in self.nodes[1:]:
        if not hasattr(node, "nodes") or not node.nodes:
            continue
        first = node.nodes[0]
        if type(first).__name__ == "power_rhs":
            has_power = True
            break

    if not has_power:
        result = self.nodes[0].to_nim(prec)
        for node in self.nodes[1:]:
            if not hasattr(node, "nodes") or not node.nodes:
                continue
            for tr in node.nodes:
                result += tr.to_nim()
        return result

    result = self.nodes[0].to_nim(PREC_POWER + 1)
    for node in self.nodes[1:]:
        if not hasattr(node, "nodes") or not node.nodes:
            continue
        first = node.nodes[0]
        fname = type(first).__name__
        if fname == "power_rhs":
            exponents = [seq.nodes[1].to_nim(PREC_POWER) for seq in node.nodes]
            for exp in reversed(exponents):
                # Use pow() for float exponents, ^ for int
                if '.' in exp or exp == '0.5':
                    ParserState.nim_imports.add("math")
                    result = f"pow(float({result}), {exp})"
                else:
                    result = f"{result} ^ {exp}"
        elif fname in ("call_trailer", "index_trailer", "slice_trailer", "attr_trailer", "trailer"):
            for tr in node.nodes:
                result += tr.to_nim()
    if prec is not None and PREC_POWER < prec:
        return f"({result})"
    return result


# --- factor (unary) ---
@method(unary_plus)
def to_nim(self, prec=None):
    result = f"+{self.nodes[0].to_nim(PREC_UNARY)}"
    if prec is not None and PREC_UNARY < prec:
        return f"({result})"
    return result


@method(unary_minus)
def to_nim(self, prec=None):
    result = f"-{self.nodes[0].to_nim(PREC_UNARY)}"
    if prec is not None and PREC_UNARY < prec:
        return f"({result})"
    return result


@method(unary_tilde)
def to_nim(self, prec=None):
    result = f"not {self.nodes[0].to_nim(PREC_UNARY)}"
    if prec is not None and PREC_UNARY < prec:
        return f"({result})"
    return result


@method(factor)
def to_nim(self, prec=None):
    return self.nodes[0].to_nim(prec)


# --- left-associative binary ops ---
@method(term)
def to_nim(self, prec=None):
    return binop_to_nim(self, prec, PREC_TERM)


@method(sum_expr)
def to_nim(self, prec=None):
    return binop_to_nim(self, prec, PREC_ARITH)


@method(shift_expr)
def to_nim(self, prec=None):
    return binop_to_nim(self, prec, PREC_SHIFT)


@method(bitand_expr)
def to_nim(self, prec=None):
    return binop_to_nim(self, prec, PREC_BAND)


@method(bitxor_expr)
def to_nim(self, prec=None):
    return binop_to_nim(self, prec, PREC_BXOR)


@method(bitor_expr)
def to_nim(self, prec=None):
    return binop_to_nim(self, prec, PREC_BOR)


# --- comparison ---
@method(comparison)
def to_nim(self, prec=None):
    last_comp_idx = None
    for i in range(len(self.nodes) - 1, -1, -1):
        node = self.nodes[i]
        if (
            type(node).__name__ == "Several_Times"
            and hasattr(node, "nodes")
            and node.nodes
        ):
            first_seq = node.nodes[0]
            if (
                hasattr(first_seq, "nodes")
                and len(first_seq.nodes) >= 2
                and hasattr(first_seq.nodes[0], "node")
                and _op_string(first_seq.nodes[0]) in _COMP_OPS
            ):
                last_comp_idx = i
                break

    if last_comp_idx is None:
        return binop_to_nim(self, prec, PREC_CMP)

    operand_prec = PREC_CMP + 1
    if last_comp_idx == 1:
        base = self.nodes[0].to_nim(operand_prec)
    else:
        class _Mock:
            pass
        mock = _Mock()
        mock.nodes = self.nodes[:last_comp_idx]
        base = binop_to_nim(mock, None, None)

    chain = base
    st = self.nodes[last_comp_idx]
    for seq in st.nodes:
        if hasattr(seq, "nodes") and len(seq.nodes) >= 2:
            py_op = _op_string(seq.nodes[0])
            # Handle 'in lo .. hi' / 'in lo ..< hi' (in_range_incl / in_range_excl)
            if py_op == "in" and len(seq.nodes) >= 4:
                lo = seq.nodes[1].to_nim(operand_prec)
                range_op_node = seq.nodes[2]
                hi = seq.nodes[3].to_nim(operand_prec)
                # Detect exclusive (..<) vs inclusive (..)
                is_exclusive = (hasattr(range_op_node, 'nodes')
                    and any(hasattr(n, 'node') and str(n.node) == '<'
                            for n in range_op_node.nodes))
                op = "..<" if is_exclusive else ".."
                chain += f" in {lo}{op}{hi}"
                continue
            nim_op = _PY_OP_TO_NIM.get(py_op, py_op)
            right = seq.nodes[1].to_nim(operand_prec)
            # Option-aware: x is not None -> x.isSome, x is None -> x.isNone
            if right == "nil" and nim_op in ("isnot", "is"):
                sym = ParserState.symbol_table.lookup(chain)
                is_option = sym and "Option[" in (sym.get("type") or "")
                if is_option:
                    ParserState.nim_imports.add("options")
                    if nim_op == "isnot":
                        chain = f"{chain}.isSome"
                    else:
                        chain = f"{chain}.isNone"
                    continue
            # For nil checks on ref types, use == / != instead of is / isnot
            if right == "nil" and nim_op in ("is", "isnot"):
                nim_op = "==" if nim_op == "is" else "!="
            chain += f" {nim_op} {right}"
    if prec is not None and PREC_CMP < prec:
        return f"({chain})"
    return chain


# --- inversion ---
@method(not_prefix)
def to_nim(self, prec=None):
    operand = self.nodes[0].to_nim(PREC_NOT)
    # Check if operand is a string/seq variable — Nim has no truthiness for these
    truthy = _nim_truthiness(operand)
    if truthy != operand:
        # _nim_truthiness returned "x.len > 0", negate to "x.len == 0"
        return truthy.replace(".len > 0", ".len == 0")
    result = f"not {operand}"
    if prec is not None and PREC_NOT < prec:
        return f"({result})"
    return result


@method(inversion)
def to_nim(self, prec=None):
    return self.nodes[0].to_nim(prec)


# --- conjunction / disjunction ---
@method(conjunction)
def to_nim(self, prec=None):
    return binop_to_nim(self, prec, PREC_AND)


@method(disjunction)
def to_nim(self, prec=None):
    return binop_to_nim(self, prec, PREC_OR)


# --- walrus ---
@method(walrus)
def to_nim(self, prec=None):
    # Nim has no walrus; emit as assignment
    name = self.nodes[0].to_nim()
    val = self.nodes[2].to_nim()
    result = f"{name} = {val}"
    if prec is not None and PREC_WALRUS < prec:
        return f"({result})"
    return result


@method(named_expression)
def to_nim(self, prec=None):
    return self.nodes[0].to_nim(prec)


# --- conditional ---
@method(conditional)
def to_nim(self, prec=None):
    # Python: value if cond else alt -> Nim: (if cond: value else: alt)
    value = self.nodes[0].to_nim()
    cond = self.nodes[1].to_nim()
    alt = self.nodes[2].to_nim()
    result = f"(if {cond}: {value} else: {alt})"
    return result


# --- lambda ---
@method(lambda_param)
def to_nim(self, prec=None):
    name = self.nodes[0].to_nim()
    if len(self.nodes) > 1 and hasattr(self.nodes[1], "nodes") and self.nodes[1].nodes:
        seq = self.nodes[1].nodes[0]
        default = seq.nodes[0].to_nim()
        return f"{name}: auto = {default}"
    return f"{name}: auto"


@method(lambda_star)
def to_nim(self, prec=None):
    # Nim has no *args; emit as varargs
    return f"{self.nodes[1].to_nim()}: varargs[auto]"


@method(lambda_dstar)
def to_nim(self, prec=None):
    # Nim has no **kwargs; keep as-is
    return f"**{self.nodes[0].to_nim()}"


@method(lambda_params_entry)
def to_nim(self, prec=None):
    return self.nodes[0].to_nim()


@method(lambda_params)
def to_nim(self, prec=None):
    parts = [self.nodes[0].to_nim()]
    if len(self.nodes) > 1 and hasattr(self.nodes[1], "nodes"):
        for seq in self.nodes[1].nodes:
            if hasattr(seq, "nodes") and seq.nodes:
                parts.append(seq.nodes[0].to_nim())
    return ", ".join(parts)


@method(lambda_expr)
def to_nim(self, prec=None):
    if len(self.nodes) >= 2:
        params_st = self.nodes[0]
        if hasattr(params_st, "nodes") and params_st.nodes:
            params = params_st.nodes[0].to_nim()
        else:
            params = ""
        body = self.nodes[1].to_nim()
        result = f"proc({params}): auto = {body}"
    else:
        body = self.nodes[0].to_nim()
        result = f"proc(): auto = {body}"
    if prec is not None and PREC_CONDITIONAL < prec:
        return f"({result})"
    return result


# --- expression ---
@method(expression)
def to_nim(self, prec=None):
    return self.nodes[0].to_nim(prec)


# --- expressions ---
@method(expressions)
def to_nim(self, prec=None):
    parts = [self.nodes[0].to_nim()]
    trailing_comma = False
    for node in self.nodes[1:]:
        if not hasattr(node, "nodes") or not node.nodes:
            continue
        found_pair = False
        for seq in node.nodes:
            if hasattr(seq, "nodes") and len(seq.nodes) >= 1:
                parts.append(seq.nodes[0].to_nim())
                found_pair = True
        if not found_pair:
            trailing_comma = True
    result = ", ".join(parts)
    if len(parts) == 1 and trailing_comma:
        result += ","
    return result


# --- yield ---
@method(yield_from)
def to_nim(self, prec=None):
    # Nim has no yield from; emit as loop
    return f"for _item in {self.nodes[0].to_nim()}: yield _item"


@method(yield_val)
def to_nim(self, prec=None):
    if self.nodes and hasattr(self.nodes[0], "nodes") and self.nodes[0].nodes:
        val = self.nodes[0].nodes[0].to_nim()
        # If yield value contains commas (tuple), wrap in parens for Nim
        if "," in val and not val.startswith("("):
            val = f"({val})"
        return f"yield {val}"
    elif self.nodes:
        val = self.nodes[0].to_nim()
        if "," in val and not val.startswith("("):
            val = f"({val})"
        return f"yield {val}"
    return "yield"


@method(yield_expr)
def to_nim(self, prec=None):
    return self.nodes[0].to_nim()


# --- star expressions ---
@method(star_single)
def to_nim(self, prec=None):
    return f"*{self.nodes[1].to_nim()}"


@method(star_expression)
def to_nim(self, prec=None):
    return self.nodes[0].to_nim(prec)


@method(star_expressions)
def to_nim(self, prec=None):
    parts = [self.nodes[0].to_nim()]
    for node in self.nodes[1:]:
        if not hasattr(node, "nodes") or not node.nodes:
            continue
        for seq in node.nodes:
            if hasattr(seq, "nodes") and len(seq.nodes) >= 1:
                parts.append(seq.nodes[0].to_nim())
    return ", ".join(parts)


# --- slices ---
@method(slice_3)
def to_nim(self, prec=None):
    # a:b:c -> countup(a, b-1, c) — complex; emit as-is for now
    return f"{self.nodes[0].to_nim()}:{self.nodes[2].to_nim()}:{self.nodes[4].to_nim()}"


@method(slice_3ns)
def to_nim(self, prec=None):
    return f"{self.nodes[0].to_nim()}::{self.nodes[3].to_nim()}"


@method(slice_3nn)
def to_nim(self, prec=None):
    return f":{self.nodes[1].to_nim()}:{self.nodes[3].to_nim()}"


@method(slice_3bare)
def to_nim(self, prec=None):
    return f"::{self.nodes[2].to_nim()}"


@method(slice_2)
def to_nim(self, prec=None):
    # a:b -> a..<b (exclusive end)
    return f"{self.nodes[0].to_nim()}..<{self.nodes[2].to_nim()}"


@method(slice_1_start)
def to_nim(self, prec=None):
    return f"{self.nodes[0].to_nim()}..<len"


@method(slice_1_stop)
def to_nim(self, prec=None):
    return f"0..<{self.nodes[1].to_nim()}"


@method(slice_bare)
def to_nim(self, prec=None):
    return ":"


@method(slice_full)
def to_nim(self, prec=None):
    return self.nodes[0].to_nim()


@method(slice_expr)
def to_nim(self, prec=None):
    return self.nodes[0].to_nim()


@method(slices)
def to_nim(self, prec=None):
    parts = [self.nodes[0].to_nim()]
    for node in self.nodes[1:]:
        if not hasattr(node, "nodes") or not node.nodes:
            continue
        for seq in node.nodes:
            if hasattr(seq, "nodes") and len(seq.nodes) >= 1:
                parts.append(seq.nodes[0].to_nim())
    return ", ".join(parts)


# --- arguments ---
@method(kwarg)
def to_nim(self, prec=None):
    return f"{self.nodes[0].to_nim()} = {self.nodes[1].to_nim()}"


@method(star_arg)
def to_nim(self, prec=None):
    return f"*{self.nodes[1].to_nim()}"


@method(dstar_arg)
def to_nim(self, prec=None):
    return f"**{self.nodes[0].to_nim()}"


@method(arg)
def to_nim(self, prec=None):
    return self.nodes[0].to_nim()


@method(arguments)
def to_nim(self, prec=None):
    parts = [self.nodes[0].to_nim()]
    for node in self.nodes[1:]:
        if not hasattr(node, "nodes") or not node.nodes:
            continue
        for seq in node.nodes:
            if hasattr(seq, "nodes") and len(seq.nodes) >= 1:
                parts.append(seq.nodes[0].to_nim())
    return ", ".join(parts)


@method(genexpr_arg)
def to_nim(self, prec=None):
    return self.nodes[0].to_nim()


# --- comprehensions ---
@method(target)
def to_nim(self, prec=None):
    parts = [self.nodes[0].to_nim()]
    if len(self.nodes) > 1 and hasattr(self.nodes[1], "nodes"):
        for seq in self.nodes[1].nodes:
            if hasattr(seq, "nodes") and len(seq.nodes) >= 1:
                parts.append(seq.nodes[0].to_nim())
    return ", ".join(parts)


@method(for_if_clause)
def to_nim(self, prec=None):
    tgt = self.nodes[0].to_nim()
    # Nim interprets 'for a, b in seq' as index/value; wrap in parens for tuple unpacking
    if "," in tgt and not tgt.startswith("("):
        tgt = f"({tgt})"
    iterable = self.nodes[1].to_nim()
    result = f"for {tgt} in {iterable}"
    if len(self.nodes) > 2:
        st = self.nodes[2]
        if hasattr(st, "nodes"):
            for seq in st.nodes:
                if hasattr(seq, "nodes") and seq.nodes:
                    result += f" if {seq.nodes[0].to_nim()}"
                elif hasattr(seq, "to_nim"):
                    result += f" if {seq.to_nim()}"
    return result


@method(for_if_clauses)
def to_nim(self, prec=None):
    parts = []
    for n in self.nodes:
        if hasattr(n, "to_nim"):
            parts.append(n.to_nim())
        elif hasattr(n, "nodes"):
            for nn in n.nodes:
                if hasattr(nn, "to_nim"):
                    parts.append(nn.to_nim())
    return " ".join(parts)


@method(listcomp)
def to_nim(self, prec=None):
    # [expr for x in xs] -> collect(for x in xs: expr)
    # [expr for x in xs if cond] -> collect(for x in xs: (if cond: expr))
    ParserState.nim_imports.add("sugar")
    expr = self.nodes[0].to_nim()
    clauses = self.nodes[1].to_nim()
    # Handle filtered comprehensions: nest the if inside the for
    import re as _re
    m = _re.match(r"(for .+ in .+?) if (.+)$", clauses)
    if m:
        for_part, cond = m.group(1), m.group(2)
        return f"collect({for_part}: (if {cond}: {expr}))"
    return f"collect({clauses}: {expr})"


@method(genexpr)
def to_nim(self, prec=None):
    # (expr for x in xs) -> collect(for x in xs: expr)
    expr = self.nodes[0].to_nim()
    clauses = self.nodes[1].to_nim()
    import re as _re
    m = _re.match(r"(for .+ in .+?) if (.+)$", clauses)
    if m:
        for_part, cond = m.group(1), m.group(2)
        return f"collect({for_part}: (if {cond}: {expr}))"
    return f"collect({clauses}: {expr})"


@method(dictcomp)
def to_nim(self, prec=None):
    # {k: v for ...} -> collect(initTable, for ...: {k: v})
    key = self.nodes[0].to_nim()
    val = self.nodes[1].to_nim()
    clauses = self.nodes[2].to_nim()
    ParserState.nim_imports.add("sugar")
    ParserState.nim_imports.add("tables")
    return f"collect(initTable, {clauses}: {{{key}: {val}}})"


@method(setcomp)
def to_nim(self, prec=None):
    # {expr for x in xs} -> collect(initHashSet, for x in xs: expr)
    expr = self.nodes[0].to_nim()
    clauses = self.nodes[1].to_nim()
    return f"collect(initHashSet, {clauses}: {expr})"


# --- dict/set makers ---
@method(kvpair)
def to_nim(self, prec=None):
    return f"{self.nodes[0].to_nim()}: {self.nodes[2].to_nim()}"


@method(dictmaker)
def to_nim(self, prec=None):
    first_pair = f"{self.nodes[0].to_nim()}: {self.nodes[2].to_nim()}"
    parts = [first_pair]
    for node in self.nodes[3:]:
        if not hasattr(node, "nodes") or not node.nodes:
            continue
        for seq in node.nodes:
            if hasattr(seq, "nodes") and len(seq.nodes) >= 1:
                parts.append(seq.nodes[0].to_nim())
    return ", ".join(parts)


@method(setmaker)
def to_nim(self, prec=None):
    parts = [self.nodes[0].to_nim()]
    for node in self.nodes[1:]:
        if not hasattr(node, "nodes") or not node.nodes:
            continue
        for seq in node.nodes:
            if hasattr(seq, "nodes") and len(seq.nodes) >= 1:
                parts.append(seq.nodes[0].to_nim())
    return ", ".join(parts)




###############################################################################
# Tests
###############################################################################

if __name__ == "__main__":
    print()
    print("=" * 60)
    print("Python -> Nim Expression Translation Tests")
    print("=" * 60)

    nim_tests = [
        # --- Literals ---
        ("42", "42"),
        ("3.14", "3.14"),
        ('"hello"', '"hello"'),
        ("None", "nil"),
        ("True", "true"),
        ("False", "false"),
        ("...", "..."),
        # --- Arithmetic (same operators) ---
        ("1 + 2", "1 + 2"),
        ("1 + 2 * 3", "1 + 2 * 3"),
        ("(1 + 2) * 3", "(1 + 2) * 3"),
        ("10 / 3", "10 / 3"),
        # --- Operators that differ ---
        ("10 // 3", "10 div 3"),
        ("10 % 3", "10 mod 3"),
        ("x ** 2", "x ^ 2"),
        ("a @ b", "a @ b"),
        # --- Bitwise -> Nim keywords ---
        ("x << 2", "x shl 2"),
        ("x >> 1", "x shr 1"),
        ("x & y", "x and y"),
        ("x | y", "x or y"),
        ("x ^ y", "x xor y"),
        ("~x", "not x"),
        # --- Boolean (same in Nim) ---
        ("x and y", "x and y"),
        ("x or y", "x or y"),
        ("not x", "not x"),
        # --- Comparison ---
        ("x < y", "x < y"),
        ("x == y", "x == y"),
        ("x != y", "x != y"),
        ("x <= y", "x <= y"),
        ("x >= y", "x >= y"),
        # --- Comparison operators that differ ---
        ("x not in y", "x notin y"),
        ("x is not y", "x isnot y"),
        ("x in y", "x in y"),
        ("x is y", "x is y"),
        # --- Unary ---
        ("-x", "-x"),
        ("+x", "+x"),
        # --- Conditional (Python ternary -> Nim if expr) ---
        ("a if b else c", "(if b: a else: c)"),
        # --- Lambda -> proc ---
        ("lambda x: x + 1", "proc(x: auto): auto = x + 1"),
        ("lambda x, y: x + y", "proc(x: auto, y: auto): auto = x + y"),
        # --- Containers ---
        ("[]", "@[]"),
        ("[1, 2, 3]", "@[1, 2, 3]"),
        ("{}", "initTable()"),
        ("{1: 2, 3: 4}", "{1: 2, 3: 4}.toTable"),
        ("{1, 2, 3}", "{1, 2, 3}"),
        ('{"a", "b"}', '{"a", "b"}.toHashSet'),
        ("()", "()"),
        # --- Calls, subscripts, attributes (same syntax) ---
        ("f(x)", "f(x)"),
        ("f(x, y)", "f(x, y)"),
        ("a[i]", "a[i]"),
        ("obj.attr", "obj.attr"),
        ("f(x).y", "f(x).y"),
        # --- Keyword args: = stays but with spaces in Nim ---
        ("f(x=1)", "f(x = 1)"),
        # --- String concat -> & ---
        ('"a" "b"', '"a" & "b"'),
        # --- Slices ---
        ("a[1:3]", "a[1..<3]"),
        # --- Await (same) ---
        ("await f()", "await f()"),
        # --- Comprehensions -> collect ---
        ("[x for x in xs]", "collect(for x in xs: x)"),
        ("{x for x in xs}", "collect(initHashSet, for x in xs: x)"),
        # --- Yield (same) ---
        # --- Power precedence ---
        ("2 ** 3 ** 2", "2 ^ 3 ^ 2"),
        # --- Mixed precedence with Nim translations ---
        ("a + b * c // d", "a + b * c div d"),
        ("x << 1 | y >> 2", "x shl 1 or y shr 2"),
    ]

    nim_passed = nim_failed = 0
    for code, expected in nim_tests:
        try:
            result = parse_expr(code)
            if result:
                output = result.to_nim()
                if output == expected:
                    print(f"  PASS: {code!r} -> {output!r}")
                    nim_passed += 1
                else:
                    print(f"  MISMATCH: {code!r}")
                    print(f"    expected: {expected!r}")
                    print(f"    got:      {output!r}")
                    nim_failed += 1
            else:
                print(f"  FAIL: {code!r} -> parse returned None")
                nim_failed += 1
        except Exception as e:
            print(f"  ERROR: {code!r} -> {e}")
            import traceback
            traceback.print_exc()
            nim_failed += 1

    print("=" * 60)
    print(f"Results: {nim_passed} passed, {nim_failed} failed")
    print()


@method(named_tuple_field)
def to_nim(self, prec=None):
    name = self.nodes[0].to_nim()
    # nodes[1] is V_COLON, nodes[2] is expression
    val = self.nodes[2].to_nim()
    return f"{name}: {val}"

@method(named_tuple_lit)
def to_nim(self, prec=None):
    # nodes[0]=LPAREN_NODE, nodes[1]=first field, nodes[2]=Several_Times of rest
    first = self.nodes[1].to_nim()
    fields = [first]
    rest = self.nodes[2]  # Several_Times
    if hasattr(rest, 'nodes'):
        for seq in rest.nodes:
            # Each seq is a Sequence_Parser with nodes: [named_tuple_field]
            # (COMMA was ignored)
            if hasattr(seq, 'nodes'):
                for child in seq.nodes:
                    if type(child).__name__ == "named_tuple_field":
                        fields.append(child.to_nim())
            elif type(seq).__name__ == "named_tuple_field":
                fields.append(seq.to_nim())
    return "(" + ", ".join(fields) + ")"
