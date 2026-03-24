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

_COMP_OPS = {"==", "!=", "<", ">", "<=", ">=", "in", "is", "not in", "is not", "isnot", "notin",
             "__bash_nt__", "__bash_ot__"}

def _nim_expr_type(expr):
    """Infer the Nim type of an already-emitted expression string.

    Walks the expression left-to-right using the symbol table and structural
    rules, returning a Nim type string or None if unknown.

    Handles:
      name              -> symbol table lookup
      name[i]           -> element type of seq[T] / string
      name.field        -> field type from known shapes (shell_result, etc.)
      name.method()     -> return type of known string/seq methods
      chained:  name[i].strip()  name.output.strip()  etc.

    Returns None rather than guessing wrong, so callers fall back safely.
    """
    import re as _re

    _SHELL_RESULT_FIELDS = {
        "output": "string",
        "stdout": "string",
        "stderr": "string",
        "code":   "int",
    }
    _STRING_METHODS_RETURN_STRING = {
        "strip", "lstrip", "rstrip", "upper", "lower", "title",
        "replace", "join", "format", "removePrefix", "removeSuffix",
    }

    def _seq_elem(t):
        m = _re.match(r"seq\[(.+)\]$", t)
        if m:
            return m.group(1)
        if t == "string":
            return "string"
        return None

    def _resolve(s):
        s = s.strip()
        if s.startswith("(") and s.endswith(")"):
            s = s[1:-1].strip()

        # method call: base.method(args)
        call_m = _re.match(r"^(.+?)\.([A-Za-z_]\w*)\(.*\)$", s)
        if call_m:
            base_type = _resolve(call_m.group(1))
            method = call_m.group(2)
            if base_type == "string" and method in _STRING_METHODS_RETURN_STRING:
                return "string"
            if base_type and base_type.startswith("seq[") and method == "join":
                return "string"
            return None

        # field access: base.field  (simple identifier on both sides)
        dot_m = _re.match(r"^([A-Za-z_]\w*)\.([A-Za-z_]\w*)$", s)
        if dot_m:
            base_name, field = dot_m.group(1), dot_m.group(2)
            sym = ParserState.symbol_table.lookup(base_name)
            if sym:
                bt = sym.get("type") or ""
                if bt == "shell_result":
                    return _SHELL_RESULT_FIELDS.get(field)
                if bt.startswith("seq[") and field == "len":
                    return "int"
                if bt == "string" and field == "len":
                    return "int"
            return None

        # subscript: base[index]
        sub_m = _re.match(r"^(.+)\[[^\[\]]+\]$", s)
        if sub_m:
            base_type = _resolve(sub_m.group(1))
            if base_type:
                return _seq_elem(base_type)
            return None

        # plain identifier
        if _re.match(r"^[A-Za-z_]\w*$", s):
            sym = ParserState.symbol_table.lookup(s)
            if sym:
                return sym.get("type")
            return None

        return None

    return _resolve(expr)


def _nim_truthiness(expr):
    """Convert a Nim expression to an explicit boolean if needed.

    In Nim, strings and seqs have no implicit bool conversion.
    Uses _nim_expr_type to resolve the type of arbitrary expressions
    (names, subscripts, field access, method calls, chains).
    Returns the expression unchanged for unknown or non-string types.
    """
    _STRING_LIKE = ("string", "seq[", "str", "PriorityQueue", "FifoQueue",
                    "LifoQueue", "HashSet", "Table", "Deque")
    t = _nim_expr_type(expr)
    if t and any(t.startswith(p) for p in _STRING_LIKE):
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


_INT_TYPES = {"int", "int8", "int16", "int32", "int64", "uint", "uint8",
              "uint16", "uint32", "uint64", "bool"}

def _nim_type_of(expr_str):
    """Best-effort type lookup for a Nim expression string."""
    sym = ParserState.symbol_table.lookup(expr_str)
    if sym:
        return sym.get("type") or ""
    return ""

def _is_pipe_not_bitor(operands):
    """Return True if any operand is clearly non-integer (string, custom type)."""
    for op in operands:
        if op.startswith('"') or op.startswith('fmt"'):
            return True
        t = _nim_type_of(op)
        if t and t not in _INT_TYPES:
            return True
    return False


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
            # seq/string concatenation: + -> & when operand is seq or string
            if nim_op == "+":
                left_is_seq = result.startswith("@[")
                right_is_seq = right.startswith("@[")
                left_is_str = (result.startswith('"') or result.startswith('fmt"')
                               or result.endswith('.join("")') or result.endswith(".join(\"\")"))
                right_is_str = (right.startswith('"') or right.startswith('fmt"')
                                or right.endswith('.join("")') or right.endswith(".join(\"\")"))
                # field access on typed object (e.g. self.off where off: string)
                if not left_is_str and "." in result:
                    _field = result.rsplit(".", 1)[-1]
                    _fsym = ParserState.symbol_table.lookup(_field)
                    if _fsym and (_fsym.get("type") or "") in ("string", "str"):
                        left_is_str = True
                if not right_is_str and "." in right:
                    _field = right.rsplit(".", 1)[-1]
                    _fsym = ParserState.symbol_table.lookup(_field)
                    if _fsym and (_fsym.get("type") or "") in ("string", "str"):
                        right_is_str = True
                if not (left_is_seq or right_is_seq or left_is_str or right_is_str):
                    # Check symbol table for seq/string-typed variables
                    lsym = ParserState.symbol_table.lookup(result)
                    rsym = ParserState.symbol_table.lookup(right)
                    ltype = (lsym.get("type") or "") if lsym else ""
                    rtype = (rsym.get("type") or "") if rsym else ""
                    left_is_seq = ltype.startswith("seq[")
                    right_is_seq = rtype.startswith("seq[")
                    left_is_str = ltype in ("string", "str")
                    right_is_str = rtype in ("string", "str")
                if left_is_seq or right_is_seq or left_is_str or right_is_str:
                    nim_op = "&"
            # string repetition: "x" * n -> repeat("x", n)
            # Single-char strings: "x" -> 'x' so repeat works as char repeat
            if nim_op == "*":
                left_is_str  = result.startswith('"') or result.startswith("'")
                right_is_str = right.startswith('"') or right.startswith("'")
                if left_is_str:
                    ParserState.nim_imports.add("strutils")
                    # Use char literal if possible (avoids nested quote issues in fmt strings)
                    _rs = result
                    if (_rs.startswith('"') and _rs.endswith('"') and len(_rs) == 3) or \
                       (_rs.startswith("'") and _rs.endswith("'") and len(_rs) == 3):
                        _rs = f"'{_rs[1]}'"
                    result = f"repeat({_rs}, {right})"
                    continue
                if right_is_str:
                    ParserState.nim_imports.add("strutils")
                    _rs = right
                    if (_rs.startswith('"') and _rs.endswith('"') and len(_rs) == 3) or \
                       (_rs.startswith("'") and _rs.endswith("'") and len(_rs) == 3):
                        _rs = f"'{_rs[1]}'"
                    result = f"repeat({_rs}, {result})"
                    continue
            # | stays as | when operands are non-integer (e.g. string | Style pipe)
            if nim_op == "or" and py_op == "|" and _is_pipe_not_bitor([result, right]):
                nim_op = "|"
            result = f"{result} {nim_op} {right}"

    if prec is not None and my_prec is not None and my_prec < prec:
        return f"({result})"
    return result


# --- leaf tokens: to_nim ---
@method(NUMBER)
def to_nim(self, prec=None):
    """NUMBER: numeric literal -> unchanged"""
    return self.node


@method(STRING)
def to_nim(self, prec=None):
    """STRING: string literal -> Nim: single-quoted strings become double-quoted; triple-quoted become ## doc-comments.
    If the entire string content is a __bash_*__ placeholder (e.g. "$1" tokenised as "__bash_arg1__"),
    emit the Nim call directly (paramStr(1) etc.) instead of a string literal."""
    s = self.node
    # Convert triple-quoted strings to Nim ## comments
    triple_dq = chr(34)*3
    triple_sq = chr(39)*3
    if s.startswith(triple_dq) or s.startswith(triple_sq):
        inner = s[3:-3]
        comment_lines = ["## " + line for line in inner.strip().splitlines()]
        return chr(10).join(comment_lines)
    # Unwrap single- or double-quoted string and check for a bash placeholder
    if (s.startswith(chr(34)) and s.endswith(chr(34)) and len(s) > 2) or \
       (s.startswith(chr(39)) and s.endswith(chr(39)) and len(s) > 2):
        inner = s[1:-1]
        if inner.startswith("__bash_") and inner.endswith("__"):
            from hek_nim_parser import _bash_to_nim
            return _bash_to_nim(inner)
    # Nim uses double quotes for strings; single quotes are char literals
    if s.startswith(chr(39)) and s.endswith(chr(39)) and len(s) > 2:
        inner = s[1:-1]
        inner = inner.replace(chr(34), chr(92) + chr(34))
        s = chr(34) + inner + chr(34)
    # Replace embedded __bash_env_NAME__ placeholders with literal $NAME text
    import re as _re_str
    if "__bash_env_" in s:
        s = _re_str.sub(r'__bash_env_(\w+)__', r'$\1', s)
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
    """IDENTIFIER: name token -> Nim: mapped via _PY_IDENT_TO_NIM; tick attributes (Type__tick__X) resolved"""
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
        # General value tick attributes
        elif attr == "len" or attr == "Length":
            return type_name + ".len"
        elif attr == "Size":
            return type_name + ".sizeof"
        # Unknown tick attribute — emit as method call
        return type_name + "." + attr
    return _PY_IDENT_TO_NIM.get(name, name)


@method(K_NONE)
def to_nim(self, prec=None):
    """K_NONE: 'None' -> Nim: 'nil'"""
    return "nil"


@method(K_TRUE)
def to_nim(self, prec=None):
    """K_TRUE: 'True' -> Nim: 'true'"""
    return "true"


@method(K_FALSE)
def to_nim(self, prec=None):
    """K_FALSE: 'False' -> Nim: 'false'"""
    return "false"


@method(ellipsis_lit)
def to_nim(self, prec=None):
    """ellipsis_lit: '...' -> unchanged"""
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
        """Visible operator token -> Nim: translated via _PY_OP_TO_NIM (e.g. ** -> ^, // -> div, & -> and)."""
        return _PY_OP_TO_NIM.get(self.node, self.node)


@method(V_COLON)
def to_nim(self, prec=None):
    """V_COLON: visible ':' operator token"""
    return ":"


@method(not_in_op)
def to_nim(self, prec=None):
    """not_in_op: 'not' 'in' -> Nim: 'notin'"""
    return "notin"


@method(is_not_op)
def to_nim(self, prec=None):
    """is_not_op: 'is' 'not' -> Nim: 'isnot'"""
    return "isnot"


@method(comp_op)
def to_nim(self, prec=None):
    """comp_op: '==' | '!=' | '<=' | '<' | '>=' | '>' | not_in_op | is_not_op | 'in' | 'is'"""
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
    # Fix \xNN escapes in literal portions of fmt strings — Nim's fmt macro
    # does not process \xNN hex escapes, so we replace them with \e (for \x1b)
    # or embed the literal character for other values.
    import re as _re_fstr
    def _fix_hex_escapes(s):
        # Only replace in literal portions (outside {} interpolations)
        out = []
        depth = 0
        i = 0
        while i < len(s):
            if s[i] == '{' and i + 1 < len(s) and s[i+1] != '{':
                depth += 1
                out.append(s[i])
            elif s[i] == '}' and depth > 0:
                depth -= 1
                out.append(s[i])
            elif depth == 0 and s[i] == '\\' and i + 3 < len(s) and s[i+1] == 'x':
                hex_str = s[i+2:i+4]
                if all(c in '0123456789abcdefABCDEF' for c in hex_str):
                    ch = chr(int(hex_str, 16))
                    out.append(ch)
                    i += 4
                    continue
                else:
                    out.append(s[i])
            else:
                out.append(s[i])
            i += 1
        return ''.join(out)
    # Apply only to the string content (between outer quotes)
    if result.startswith('fmt"') and result.endswith('"'):
        result = 'fmt"' + _fix_hex_escapes(result[4:-1]) + '"'
    return result


# --- str_concat ---
@method(str_concat)
def to_nim(self, prec=None):
    """str_concat: STRING STRING+ -> Nim: joined with '&'"""
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
    """empty_paren: '(' ')' -> Nim: '()'"""
    return "()"


@method(paren_group)
def to_nim(self, prec=None):
    """paren_group: '(' (yield_expr | walrus | expressions) ')' -> Nim: '(expr)'"""
    return f"({self.nodes[1].to_nim()})"


@method(empty_list)
def to_nim(self, prec=None):
    """empty_list: '[' ']' -> Nim: '@[]'"""
    return "@[]"


@method(list_display)
def to_nim(self, prec=None):
    """list_display: '[' (listcomp | star_expressions) ']' -> Nim: '@[...]' or sequence comprehension"""
    inner_node = self.nodes[1]
    # If inner is a listcomp, collect() handles it — no @[] wrapper
    if type(inner_node).__name__ == "listcomp":
        return inner_node.to_nim()
    return f"@[{inner_node.to_nim()}]"


@method(empty_set)
def to_nim(self, prec=None):
    """empty_set: '{' '}' -> Nim: set[T]{} for ordinal types; initHashSet[T]() for hash sets.

    Returns the sentinel string "initHashSet()" so that the enclosing
    assignment statement (ann_assign_stmt / decl_ann_assign_stmt) can
    substitute the correct type-parameterised form by inspecting the
    declared annotation — exactly the same post-processing pattern used for
    initTable() / empty dicts.

    Dispatch table (based on the Nim annotation of the LHS variable):
      set[T]         -> {}              (built-in ordinal set literal)
      HashSet[T]     -> initHashSet[T]()
      unknown/bare   -> initHashSet()   (fallback)
    """
    # Sentinel — picked up by ann_assign_stmt / decl_ann_assign_stmt
    return "initHashSet()"


@method(empty_dict)
def to_nim(self, prec=None):
    """empty_dict: '{' ':' '}' -> Nim: initTable() (requires tables import)

    HPython uses {:} as the empty dict literal.  Returns the sentinel string
    "initTable()" so that the enclosing assignment statement can substitute
    the correct type-parameterised form (initTable[K, V]()) from the annotation.
    """
    ParserState.nim_imports.add("tables")
    return "initTable()"


@method(dict_display)
def to_nim(self, prec=None):
    """dict_display: '{' (dictcomp | dictmaker) '}' -> Nim: '{k: v}.toTable'"""
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
    """set_display: '{' (setcomp | setmaker) '}' -> Nim: toHashSet([...]) or ordinal set literal"""
    inner_node = self.nodes[1]
    # If inner is a setcomp, collect() handles it — no {} wrapper
    if type(inner_node).__name__ == "setcomp":
        return inner_node.to_nim()
    # Infer element type from first element
    first_elem = inner_node.nodes[0] if hasattr(inner_node, "nodes") and inner_node.nodes else inner_node
    elem_type = _infer_literal_nim_type(first_elem)
    if elem_type and _is_nim_ordinal(elem_type):
        return "{" + inner_node.to_nim() + "}"
    return "[" + inner_node.to_nim() + "].toHashSet"


@method(atom)
def to_nim(self, prec=None):
    """atom: empty_paren | paren_group | empty_list | list_display | empty_set | empty_dict | dict_display | set_display | '...' | 'None' | 'True' | 'False' | IDENTIFIER | NUMBER | str_concat | STRING"""
    return self.nodes[0].to_nim(prec)


# --- trailers ---
@method(call_trailer)
def to_nim(self, prec=None):
    """call_trailer: '(' arguments? ')' -> Nim: method call or proc call"""
    if len(self.nodes) > 1 and hasattr(self.nodes[1], "nodes") and self.nodes[1].nodes:
        return "(" + self.nodes[1].nodes[0].to_nim() + ")"
    elif len(self.nodes) > 1 and hasattr(self.nodes[1], "to_nim"):
        return "(" + self.nodes[1].to_nim() + ")"
    return "()"


@method(slice_trailer)
def to_nim(self, prec=None):
    """slice_trailer: '[' slices ']' -> Nim: Python slice a[x:y] -> a[x..<y] or a[x..y]"""
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
               "replace": "replace", "find": "find", "index": "find"},
}

@method(attr_trailer)
def to_nim(self, prec=None):
    """attr_trailer: '.' IDENTIFIER -> Nim: '.field'; tick attrs (.field'Next) handled specially"""
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
    """trailer: call_trailer | slice_trailer | attr_trailer"""
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
    "index": "find",
}

def _translate_method(obj_name, method_name):
    """Translate a Python method name based on the object's type from the symbol table."""
    sym = ParserState.symbol_table.lookup(obj_name)
    # For subscript expressions like "tbl[key]", look up the base variable
    if sym is None and "[" in obj_name:
        base_var = obj_name[:obj_name.index("[")]
        base_sym = ParserState.symbol_table.lookup(base_var)
        if base_sym:
            base_type = base_sym.get("type", "") or ""
            # Table[K, V][key] -> V; seq[T][i] -> T
            import re as _re_tm
            _seq_m = _re_tm.match(r'^seq\[(.+)\]$', base_type)
            _tbl_m = _re_tm.match(r'^Table\[.+,\s*(.+)\]$', base_type)
            if _seq_m:
                elem_type = _seq_m.group(1)
                # Treat as seq for method dispatch
                sym = {"type": f"seq[{elem_type}]"}
            elif _tbl_m:
                val_type = _tbl_m.group(1)
                sym = {"type": val_type}
    # For attribute chains like "self.G", try looking up the last field name
    if sym is None and "." in obj_name:
        field = obj_name.rsplit(".", 1)[-1]
        sym = ParserState.symbol_table.lookup(field)
    if sym:
        type_str = sym.get("type", "") or ""
        for prefix, mappings in _PY_METHOD_TO_NIM.items():
            if type_str.startswith(prefix):
                return mappings.get(method_name, method_name)
        # Resolve type aliases: if type_str is a user type, look up its definition
        alias = ParserState.symbol_table.lookup(type_str)
        if alias:
            resolved = alias.get("type", "") or ""
            for prefix, mappings in _PY_METHOD_TO_NIM.items():
                if resolved.startswith(prefix):
                    return mappings.get(method_name, method_name)
        # For PyObject / pyImport module vars, don't apply universal mappings
        if type_str.startswith("_py_module:") or type_str.startswith("_nim_module:"):
            return method_name
    # Fall back to universal mappings.
    # .get(key, default) is exclusively a dict/Table pattern in HPython code —
    # always map it. (nimpy module vars are already handled above via early return.)
    if method_name == "get":
        return "getOrDefault"
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
    """primary: atom trailer* -> Nim: base.trailer1.trailer2..."""
    result = self.nodes[0].to_nim()
    # Map Python builtin names to Nim equivalents
    raw_name = result
    result = _PY_IDENT_TO_NIM.get(result, result)
    # If this is a call to a known class name, add 'new' prefix for Nim constructor
    has_call = (len(self.nodes) > 1 and hasattr(self.nodes[1], "nodes")
                and self.nodes[1].nodes
                and type(self.nodes[1].nodes[0]).__name__ == "call_trailer")
    if has_call:
        # Auto-import for known Nim stdlib functions used as calls
        _NIM_CALL_IMPORTS = {
            "toSeq": "sequtils", "collect": "sugar", "reversed": "algorithm",
            "sorted": "algorithm", "toHashSet": "sets", "initHashSet": "sets",
            "initTable": "tables", "newTable": "tables",
        }
        if raw_name in _NIM_CALL_IMPORTS:
            ParserState.nim_imports.add(_NIM_CALL_IMPORTS[raw_name])

        # Enum constructor: State(s) -> parseEnum[State](s)
        if raw_name not in _PY_IDENT_TO_NIM:
            _sym = ParserState.symbol_table.lookup(raw_name)
            if _sym and _sym.get("type") == "enum":
                call_node = self.nodes[1].nodes[0]
                args = _extract_call_args(call_node)
                rest = "".join(tr.to_nim() for tr in self.nodes[1].nodes[1:])
                ParserState.nim_imports.add("strutils")
                return f"parseEnum[{raw_name}]({', '.join(args)}){rest}"

        # Tuple/object type constructor: TupleType(a, b) -> (field1: a, field2: b)
        #                                ObjectType(a, b) -> ObjectType(field1: a, field2: b)
        if raw_name not in _PY_IDENT_TO_NIM:
            tuple_fields = getattr(ParserState, 'tuple_field_order', {}).get(raw_name)
            obj_fields = getattr(ParserState, 'object_field_order', {}).get(raw_name)
            named_fields = tuple_fields or obj_fields
            if named_fields:
                call_node = self.nodes[1].nodes[0]
                args = _extract_call_args(call_node)
                import re as _re_ctor
                # If args are keyword-style (name = value), convert to colon style directly
                if args and all(_re_ctor.match(r'^\w+ = ', a) for a in args):
                    pairs_parts = [_re_ctor.sub(r'^(\w+) = ', r'\1: ', a, count=1) for a in args]
                    pairs = ", ".join(pairs_parts)
                    rest = "".join(tr.to_nim() for tr in self.nodes[1].nodes[1:])
                    if obj_fields:
                        return f"{raw_name}({pairs}){rest}"
                    else:
                        return f"({pairs}){rest}"
                if len(args) == len(named_fields):
                    ftype_map = ParserState.class_field_types.get(raw_name, {})
                    pairs_parts = []
                    for fn, av in zip(named_fields, args):
                        ftype = ftype_map.get(fn, "")
                        # If field type is a ref object class, cast to that type for proper subtype coercion
                        sym = ParserState.symbol_table.lookup(ftype)
                        if ftype and sym and sym.get("kind") == "class":
                            pairs_parts.append(f"{fn}: {ftype}({av})")
                        else:
                            pairs_parts.append(f"{fn}: {av}")
                    pairs = ", ".join(pairs_parts)
                    rest = "".join(tr.to_nim() for tr in self.nodes[1].nodes[1:])
                    if obj_fields:
                        # Nim object: TypeName(field: val, ...)
                        return f"{raw_name}({pairs}){rest}"
                    else:
                        # Nim tuple: (field: val, ...)
                        return f"({pairs}){rest}"
        # PyObject callable: f(args) where f is a PyObject -> callObject(f, args)
        if raw_name not in _PY_IDENT_TO_NIM:  # skip builtins like str, list, etc.
            sym = ParserState.symbol_table.lookup(raw_name)
            if sym and sym.get("type") == "PyObject":
                call_node = self.nodes[1].nodes[0]
                args = _extract_call_args(call_node)
                all_args = ", ".join([raw_name] + args)
                return f"callObject({all_args})"
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
        if raw_name == "enumerate":
            call_node = self.nodes[1].nodes[0]
            arg = _extract_call_arg(call_node)
            return f"{arg}.pairs"
        if raw_name == "ord":
            call_node = self.nodes[1].nodes[0]
            arg = _extract_call_arg(call_node)
            # Convert string arg to char literal: ord("0") -> ord('0')
            if len(arg) == 3 and arg[0] == chr(34) and arg[2] == chr(34):
                arg = chr(39) + arg[1] + chr(39)
            return f"ord({arg})"
        if raw_name in ("int", "float", "bool"):
            call_node = self.nodes[1].nodes[0]
            arg = _extract_call_arg(call_node)
            _sym = ParserState.symbol_table.lookup(arg)
            _is_str = (
                "__bash_arg" in arg          # $1, $2, etc. (pre-substitution)
                or "paramStr" in arg         # $1, $2, etc. (post-substitution)
                or arg.startswith('"')       # string literal
                or (_sym and _sym.get("type") in ("string", "seq[string]"))
            )
            if _is_str:
                ParserState.nim_imports.add("strutils")
                _parse_fn = {"int": "parseInt", "float": "parseFloat", "bool": "parseBool"}[raw_name]
                return f"{arg}.{_parse_fn}()"
            return f"{raw_name}({arg})"
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
        trailer_list = list(self.nodes[1].nodes)
        skip_next = False
        for i, tr in enumerate(trailer_list):
            if skip_next:
                skip_next = False
                continue
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
                next_tr = trailer_list[i + 1] if i + 1 < len(trailer_list) else None
                # rstrip/lstrip -> strip(chars={...}, leading/trailing=false)
                if method_name in ("rstrip", "lstrip") and next_tr is not None and type(next_tr).__name__ == "call_trailer":
                    raw_arg = _extract_call_arg(next_tr)
                    side = "leading=false" if method_name == "rstrip" else "trailing=false"
                    if raw_arg:
                        char_arg = raw_arg.strip('"').strip("'")
                        result += f".strip(chars={{'{char_arg}'}}, {side})"
                    else:
                        result += f".strip({side})"
                    ParserState.nim_imports.add("strutils")
                    skip_next = True  # consume the call_trailer
                    continue
                # Option-typed field called as proc: insert .get() before call trailer
                if (next_tr is not None
                        and type(next_tr).__name__ == "call_trailer"
                        and _expr_is_option(result + "." + method_name)):
                    result += "." + method_name + ".get()"
                    ParserState.nim_imports.add("options")
                else:
                    result += "." + method_name
            else:
                result += tr.to_nim()
    # Post-process: translate known Python stdlib patterns to Nim
    result = _translate_stdlib_patterns(result)
    # Regex method calls: regex.match(s) -> s.match(regex), regex.search(s) -> s.find(regex)
    # Only flip single-argument calls; multi-arg calls are already in Nim style.
    import re as _re_rgx
    for _py_m, _nim_m in (("match", "match"), ("search", "find"), ("findall", "findAll")):
        _pat = _re_rgx.compile(r'^(\w+)\.(' + _py_m + r')\((.+)\)$')
        _hit = _pat.match(result)
        if _hit:
            _rgx_var, _, _str_arg = _hit.group(1), _hit.group(2), _hit.group(3)
            _sym = ParserState.symbol_table.lookup(_rgx_var)
            _typ = (_sym.get("type") or "") if _sym else ""
            if _typ == "auto" or _typ == "Regex" or _rgx_var.startswith("RE_") or _rgx_var.startswith("re_"):
                # Only flip if single argument (no top-level comma)
                _depth = 0
                _has_comma = False
                for _ch in _str_arg:
                    if _ch in "([{": _depth += 1
                    elif _ch in ")]}": _depth -= 1
                    elif _ch == "," and _depth == 0: _has_comma = True; break
                if not _has_comma:
                    result = f"{_str_arg}.{_nim_m}({_rgx_var})"
                else:
                    # Two-arg call: RE.match(str, captures) -> str.match(RE, captures)
                    _comma_pos = next(
                        j for j, c in enumerate(_str_arg)
                        if c == "," and sum(
                            1 if x in "([{" else -1 if x in ")]}" else 0
                            for x in _str_arg[:j]
                        ) == 0
                    )
                    _first_arg = _str_arg[:_comma_pos].strip()
                    _rest_args = _str_arg[_comma_pos+1:].strip()
                    result = f"{_first_arg}.{_nim_m}({_rgx_var}, {_rest_args})"
                break
    # Option[T] call-site coercion: wrap non-Option args in some() where param expects Option
    result = _wrap_option_args(result)
    return result


# Python stdlib dotted-access patterns -> Nim equivalents
# These translate Python stdlib calls to native Nim equivalents.
# Only patterns that MUST be native Nim belong here.
_STDLIB_PATTERNS = [
    # (python_pattern, nim_equivalent, nim_import_needed)
    ("os.path.exists",    "fileExists",      "os"),
    ("os.path.isfile",    "fileExists",      "os"),
    ("os.path.isdir",     "dirExists",       "os"),
    ("os.path.join",      "joinPath",        "os"),
    ("os.path.basename",  "lastPathPart",    "os"),
    ("os.path.dirname",   "parentDir",       "os"),
    ("os.path.abspath",   "absolutePath",    "os"),
    ("os.path.splitext",  "splitFile",       "os"),
    ("os.getcwd",         "getCurrentDir",   "os"),
    ("os.chdir",          "setCurrentDir",   "os"),
    ("os.listdir",        "toSeq(walkDir",   "os"),  # wraps arg
    ("os.makedirs",       "createDir",       "os"),
    ("os.mkdir",          "createDir",       "os"),
    ("os.remove",         "removeFile",      "os"),
    ("os.unlink",         "removeFile",      "os"),
    ("os.rmdir",          "removeDir",       "os"),
    ("os.rename",         "moveFile",        "os"),
    ("os.getenv",         "getEnv",          "os"),
    ("os.environ.get",    "getEnv",          "os"),
    ("time.perf_counter", "cpuTime",         "times"),
    ("time.monotonic",    "cpuTime",         "times"),
    ("time.time",         "epochTime",       "times"),
    ("time.sleep",        "sleep",           "os"),
    ("sys.exit",          "quit",            None),
    ("sys.stderr.write",  "stderr.writeLine", "std/syncio"),
    ("sys.stdout.write",  "stdout.write",    "std/syncio"),
]

# Module-qualified function call translation using _PY_MODULE_FUNC_TO_NIM.
# Imports hek_nim_stmt lazily to avoid circular imports.
def _translate_module_call(module_local, func_name, args_str):
    """Translate module.func(args) -> Nim equivalent, or None if not mappable.

    Uses the symbol table to look up whether `module_local` is a registered
    native module (_nim_module:X or _sys_native), then looks up the function
    in _PY_MODULE_FUNC_TO_NIM.

    Returns the translated Nim string, or None if no mapping exists.
    """
    sym = ParserState.symbol_table.lookup(module_local)
    if not sym:
        return None
    sym_type = sym.get("type", "") or ""

    # Determine the Python module name
    if sym_type == "_sys_native":
        py_module = "sys"
    elif sym_type.startswith("_nim_module:"):
        py_module = sym_type[len("_nim_module:"):]
    else:
        return None  # pyImport module or unknown — don't translate

    # Look up in function table (import lazily to avoid circular dep)
    try:
        from hek_nim_stmt import _PY_MODULE_FUNC_TO_NIM, _PY_MODULE_TO_NIM
    except ImportError:
        return None

    func_map = _PY_MODULE_FUNC_TO_NIM.get(py_module, {})
    template = func_map.get(func_name)
    if template is None:
        return None

    # Add required Nim import
    nim_mod = _PY_MODULE_TO_NIM.get(py_module)
    if nim_mod and nim_mod not in ("_sys_native",):
        ParserState.nim_imports.add(nim_mod)

    # Parse args_str into individual positional args (simple split on ', ')
    # Good enough for most stdlib calls; complex nested args fall back to pyImport.
    import re as _re
    # Strip surrounding parentheses
    inner = args_str.strip()
    if inner.startswith("(") and inner.endswith(")"):
        inner = inner[1:-1].strip()

    # Split on top-level commas
    args = []
    depth = 0
    cur = []
    for ch in inner:
        if ch in "([{":
            depth += 1
            cur.append(ch)
        elif ch in ")]}":
            depth -= 1
            cur.append(ch)
        elif ch == "," and depth == 0:
            args.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    if cur:
        args.append("".join(cur).strip())
    args = [a for a in args if a]

    # Substitute {arg0}, {arg1}, …, {args} in template
    result = template
    result = result.replace("{args}", ", ".join(args))
    for i, a in enumerate(args):
        result = result.replace(f"{{arg{i}}}", a)
    return result


def _wrap_option_args(expr):
    """Wrap call arguments in some() where the proc parameter expects Option[T].

    Only applies to procs registered in ParserState.proc_param_types.
    Example: newRegion(both) -> newRegion(some(both))
    """
    import re as _re
    m = _re.match(r"^([A-Za-z_]\w*)\((.+)\)$", expr, _re.DOTALL)
    if not m:
        return expr
    proc_name = m.group(1)
    args_str = m.group(2)
    param_types = ParserState.proc_param_types.get(proc_name)
    if not param_types:
        return expr
    # Split args on top-level commas
    args = []
    depth = 0
    cur = []
    for ch in args_str:
        if ch in "([{":
            depth += 1
            cur.append(ch)
        elif ch in ")]}":
            depth -= 1
            cur.append(ch)
        elif ch == "," and depth == 0:
            args.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    if cur:
        args.append("".join(cur).strip())
    if len(args) != len(param_types):
        return expr
    new_args = []
    changed = False
    for arg, ptype in zip(args, param_types):
        if "Option[" in ptype and not arg.startswith("some(") and not arg.startswith("none(") and arg != "nil":
            ParserState.nim_imports.add("options")
            new_args.append(f"some({arg})")
            changed = True
        else:
            new_args.append(arg)
    if not changed:
        return expr
    return f"{proc_name}({', '.join(new_args)})"


def _translate_stdlib_patterns(expr):
    """Post-process a fully-emitted expression string.

    Applies pattern-based and module-call-based translations to convert
    Python stdlib calls to their native Nim equivalents.
    """
    import re as _re

    # --- 1. Pattern table (exact or prefix match) ---
    for py_pattern, nim_equiv, nim_import in _STDLIB_PATTERNS:
        if expr == py_pattern:
            if nim_import:
                ParserState.nim_imports.add(nim_import)
            return nim_equiv
        if expr.startswith(py_pattern + "("):
            if nim_import:
                ParserState.nim_imports.add(nim_import)
            return nim_equiv + expr[len(py_pattern):]
        if expr.startswith(py_pattern + "["):
            if nim_import:
                ParserState.nim_imports.add(nim_import)
            return nim_equiv + expr[len(py_pattern):]

    # --- 2. Module-qualified call: local.func(args) ---
    call_m = _re.match(r"^([A-Za-z_]\w*)\.([A-Za-z_]\w*)(\(.*\))$", expr, _re.DOTALL)
    if call_m:
        module_local, func_name, args_str = call_m.group(1), call_m.group(2), call_m.group(3)
        translated = _translate_module_call(module_local, func_name, args_str)
        if translated is not None:
            return translated

    # --- 3. sys attribute access (no call) ---
    sys_attr_m = _re.match(r"^([A-Za-z_]\w*)\.(argv|version|platform|modules|path)(.*)$", expr)
    if sys_attr_m:
        local, attr, rest = sys_attr_m.group(1), sys_attr_m.group(2), sys_attr_m.group(3)
        sym = ParserState.symbol_table.lookup(local)
        if sym and sym.get("type") == "_sys_native":
            _SYS_ATTR = {
                "argv":     "commandLineParams()",
                "version":  "NimVersion",
                "platform": "hostOS",
                "path":     "getEnv(\"PATH\").split(PathSep)",
            }
            if attr in _SYS_ATTR:
                ParserState.nim_imports.add("os")
                return _SYS_ATTR[attr] + rest

    # --- 4. 'sep'.join(x) -> x.join("sep") ---
    m = _re.match(r"^(.+)\.join\((.+)\)$", expr)
    if m:
        sep, arg = m.group(1), m.group(2)
        ParserState.nim_imports.add("strutils")
        if len(sep) == 3 and sep[0] == "'" and sep[-1] == "'":
            sep = "$" + sep
        elif len(sep) == 3 and sep[0] == '"' and sep[-1] == '"':
            sep = "$'" + sep[1] + "'"
        return f"{arg}.join({sep})"

    # --- 5. f.readlines() -> f.readAll().splitLines() ---
    if expr.endswith(".readlines()"):
        obj = expr[:-len(".readlines()")]
        ParserState.nim_imports.add("strutils")
        return f"{obj}.readAll().splitLines()"

    # --- 5b. x.split() (no args) -> x.splitWhitespace() ---
    # Python split() with no args splits on any whitespace run; Nim split() splits on each char
    if expr.endswith(".split()"):
        obj = expr[:-len(".split()")]
        ParserState.nim_imports.add("strutils")
        return f"{obj}.splitWhitespace()"

    # --- 5c. x.isdigit() -> x.allCharsInSet({'0'..'9'}) ---
    # Python str.isdigit() checks all chars are digits; Nim has no direct equivalent
    if expr.endswith(".isdigit()"):
        obj = expr[:-len(".isdigit()")]
        ParserState.nim_imports.add("strutils")
        return f"({obj}).len > 0 and ({obj}).allCharsInSet({{'0'..'9'}})"

    # --- 5d. x.get(key, default) -> x.getOrDefault(key, default) ---
    _get_m = _re.match(r'^(.+)\.get\((.+)\)$', expr)
    if _get_m:
        obj, args = _get_m.group(1), _get_m.group(2)
        ParserState.nim_imports.add("tables")
        return f"{obj}.getOrDefault({args})"

    # --- 6. sorted(X.items()) / sorted(X.pairs()) -> toSeq(X.pairs).sortedByIt(it[0]) ---
    _sorted_m = _re.match(r'^sorted\((.+)\.(items|pairs)\(\)\)$', expr)
    if _sorted_m:
        ParserState.nim_imports.add("algorithm")
        ParserState.nim_imports.add("sequtils")
        return f"toSeq({_sorted_m.group(1)}.pairs).sortedByIt(it[0])"

    # --- 7. sorted(X) -> X.sorted ---
    _sorted_plain = _re.match(r'^sorted\((.+)\)$', expr)
    if _sorted_plain:
        ParserState.nim_imports.add("algorithm")
        return f"{_sorted_plain.group(1)}.sorted"

    return expr


# --- await ---
@method(await_expr)
def to_nim(self, prec=None):
    """await_expr: 'await' primary -> Nim: 'await primary' (requires asyncdispatch)"""
    return f"await {self.nodes[0].to_nim()}"


@method(await_primary)
def to_nim(self, prec=None):
    """await_primary: await_expr | primary"""
    return self.nodes[0].to_nim(prec)


# --- bash file-test operators ---
# Mapping from bash flag letter to (nim_func, nim_import)
_BASH_FILE_TEST_NIM = {
    "e": ("fileExists",        "os"),   # -e: exists (file or dir)
    "f": ("fileExists",        "os"),   # -f: regular file
    "d": ("dirExists",         "os"),   # -d: directory
    "L": ("symlinkExists",     "os"),   # -L: symbolic link
    "r": ("(fpUserRead  in getFilePermissions", "os"),   # -r: readable
    "w": ("(fpUserWrite in getFilePermissions", "os"),   # -w: writable
    "x": ("(fpUserExec  in getFilePermissions", "os"),   # -x: executable
    "s": ("(getFileSize(",     "os"),   # -s: non-empty
    "c": ("(pcDevice  == getFileInfo(",  "os"),  # -c: char device
    "b": ("(pcDir     == getFileInfo(",  "os"),  # -b: block device (approx)
    "p": ("(pcLinkToDir == getFileInfo(", "os"), # -p: named pipe (approx)
    "S": ("(pcFile    == getFileInfo(",  "os"),  # -S: socket (approx)
}

@method(file_test)
def to_nim(self, prec=None):
    """file_test: __bash_test_X__ primary -> Nim os file-test call.

    -e/-f  -> fileExists(path)
    -d     -> dirExists(path)
    -L     -> symlinkExists(path)
    -r/-w/-x -> fpUserRead/Write/Exec in getFilePermissions(path)
    -s     -> getFileSize(path) > 0
    -nt/-ot handled in comparison via bash_nt_op / bash_ot_op
    """
    op_name = self.nodes[0].node   # e.g. '__bash_test_e__'
    flag = op_name[len("__bash_test_"):-2]  # e.g. 'e'
    path = self.nodes[1].to_nim()
    ParserState.nim_imports.add("os")
    if flag in ("e", "f"):
        return f"fileExists({path})"
    elif flag == "d":
        return f"dirExists({path})"
    elif flag == "L":
        return f"symlinkExists({path})"
    elif flag == "r":
        return f"(fpUserRead in getFilePermissions({path}))"
    elif flag == "w":
        return f"(fpUserWrite in getFilePermissions({path}))"
    elif flag == "x":
        return f"(fpUserExec in getFilePermissions({path}))"
    elif flag == "s":
        return f"(getFileSize({path}) > 0)"
    else:
        # -c, -b, -p, -S: no clean Nim equivalent — emit a comment
        return f"(true) # TODO: -{flag} {path} not supported in Nim"


@method(bash_nt_op)
def to_nim(self, prec=None):
    """bash_nt_op: __bash_nt__ -> emitted as part of comparison to_nim"""
    return "__bash_nt__"


@method(bash_ot_op)
def to_nim(self, prec=None):
    """bash_ot_op: __bash_ot__ -> emitted as part of comparison to_nim"""
    return "__bash_ot__"


# --- range expression (.., ..<) ---
@method(range_incl_op)
def to_nim(self, prec=None):
    """range_incl_op: '..' (inclusive range operator) -> Nim: '..'"""
    return ".."

@method(range_excl_op)
def to_nim(self, prec=None):
    """range_excl_op: '..<' (exclusive upper bound) -> Nim: '..<'"""
    return "..<"

@method(range_expr)
def to_nim(self, prec=None):
    """range_expr: bitor_expr (('..' | '..<') bitor_expr)? -> Nim: lo .. hi or lo ..< hi

    Due to the '+' combinator flattening, the bitor_expr's own Several_Times
    nodes (containing arithmetic operators like *, /, +, etc.) end up as direct
    children of range_expr alongside the range operator Several_Times.  We must
    distinguish them:

    - Sequence_Parser whose first child is range_incl_op / range_excl_op
      → emit as range: "lo .. hi" or "lo ..< hi"
    - Sequence_Parser whose first child is an arithmetic operator
      → emit as binary op: "left op right"
    - range_incl_op / range_excl_op node directly
      → emit the operator text
    """
    result = self.nodes[0].to_nim(prec)
    for node in self.nodes[1:]:
        if not hasattr(node, 'nodes') or not node.nodes:
            continue
        for seq in node.nodes:
            tname = type(seq).__name__
            if tname in ("range_incl_op", "range_excl_op"):
                # Bare range operator node — append its text
                result += " " + seq.to_nim(prec)
            elif tname == "Sequence_Parser" and hasattr(seq, 'nodes') and seq.nodes:
                first = seq.nodes[0]
                first_tname = type(first).__name__
                if first_tname in ("range_incl_op", "range_excl_op"):
                    # Range pair: (range_op, right_bitor_expr)
                    right = seq.nodes[1].to_nim(prec) if len(seq.nodes) > 1 else ""
                    result += " " + first.to_nim(prec) + " " + right
                else:
                    # Arithmetic pair from the flattened bitor_expr: (op, right)
                    # Emit as "op right" appended to the accumulator
                    op_str = getattr(first, 'node', None)
                    if op_str is None and hasattr(first, 'nodes') and first.nodes:
                        op_str = getattr(first.nodes[0], 'node', str(first.nodes[0]))
                    nim_op = _PY_OP_TO_NIM.get(str(op_str), str(op_str)) if op_str else ""
                    right = seq.nodes[1].to_nim(prec) if len(seq.nodes) > 1 else ""
                    # seq concat: + -> & when operand is seq literal
                    if nim_op == "+" and (right.startswith("@[") or result.startswith("@[")):
                        nim_op = "&"
                    # string repeat: "x" * n -> repeat("x", n)
                    if nim_op == "*":
                        if result.startswith('"') or result.startswith("'"):
                            ParserState.nim_imports.add("strutils")
                            result = f"repeat({result}, {right})"
                            continue
                        if right.startswith('"') or right.startswith("'"):
                            ParserState.nim_imports.add("strutils")
                            result = f"repeat({right}, {result})"
                            continue
                    result += f" {nim_op} {right}"
            else:
                result += seq.to_nim(prec) if hasattr(seq, 'to_nim') else ""
    return result


# --- power ---
@method(power_rhs)
def to_nim(self, prec=None):
    """power_rhs: '**' factor -> Nim: '^ factor' (power uses ^ in Nim)"""
    return f"^ {self.nodes[1].to_nim(prec)}"


@method(power)
def to_nim(self, prec=None):
    """power: await_primary power_rhs* (right-associative) -> Nim: ** -> ^"""
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
    """unary_plus: '+' factor -> Nim: '+factor'"""
    result = f"+{self.nodes[0].to_nim(PREC_UNARY)}"
    if prec is not None and PREC_UNARY < prec:
        return f"({result})"
    return result


@method(unary_minus)
def to_nim(self, prec=None):
    """unary_minus: '-' factor -> Nim: '-factor'"""
    result = f"-{self.nodes[0].to_nim(PREC_UNARY)}"
    if prec is not None and PREC_UNARY < prec:
        return f"({result})"
    return result


@method(unary_tilde)
def to_nim(self, prec=None):
    """unary_tilde: '~' factor -> Nim: 'not factor'"""
    result = f"not {self.nodes[0].to_nim(PREC_UNARY)}"
    if prec is not None and PREC_UNARY < prec:
        return f"({result})"
    return result


@method(factor)
def to_nim(self, prec=None):
    """factor: unary_plus | unary_minus | unary_tilde | power"""
    return self.nodes[0].to_nim(prec)


# --- left-associative binary ops ---
@method(term)
def to_nim(self, prec=None):
    """term: factor (('*' | '/' | '//' | '%' | '@') factor)* -> Nim: // -> div, % -> mod"""
    return binop_to_nim(self, prec, PREC_TERM)


@method(sum_expr)
def to_nim(self, prec=None):
    """sum_expr: term (('+' | '-') term)* -> Nim: str/seq '+' may become '&'"""
    return binop_to_nim(self, prec, PREC_ARITH)


@method(shift_expr)
def to_nim(self, prec=None):
    """shift_expr: sum_expr (('<<' | '>>') sum_expr)* -> Nim: << -> shl, >> -> shr"""
    return binop_to_nim(self, prec, PREC_SHIFT)


@method(bitand_expr)
def to_nim(self, prec=None):
    """bitand_expr: shift_expr ('&' shift_expr)* -> Nim: '&' -> 'and'"""
    return binop_to_nim(self, prec, PREC_BAND)


@method(bitxor_expr)
def to_nim(self, prec=None):
    """bitxor_expr: bitand_expr ('^' bitand_expr)* -> Nim: '^' -> 'xor'"""
    return binop_to_nim(self, prec, PREC_BXOR)


@method(bitor_expr)
def to_nim(self, prec=None):
    """bitor_expr: bitxor_expr ('|' bitxor_expr)* -> Nim: '|' -> 'or' (or '|' for custom types)"""
    # Collect operand strings before translation to check types
    operands = []
    if hasattr(self.nodes[0], "to_nim"):
        operands.append(self.nodes[0].to_nim())
    for seq in self.nodes[1:]:
        if hasattr(seq, "nodes") and len(seq.nodes) >= 2 and hasattr(seq.nodes[1], "to_nim"):
            operands.append(seq.nodes[1].to_nim())
    result = binop_to_nim(self, prec, PREC_BOR)
    if " or " in result and _is_pipe_not_bitor(operands):
        result = result.replace(" or ", " | ")
    return result


def _expr_is_option(expr_str):
    """Return True if expr_str refers to an Option[...]-typed variable or attribute.

    Handles:
    - Plain names: look up in symbol table
    - Attribute access like "self.predicate": look up field in class_field_types
      for the current class (tracked by ParserState._current_class_name)
    """
    import re as _re
    # Plain name lookup
    sym = ParserState.symbol_table.lookup(expr_str)
    if sym and "Option[" in (sym.get("type") or ""):
        return True
    # Attribute access: obj.field
    m = _re.match(r"(\w+)\.(\w+)$", expr_str)
    if m:
        field_name = m.group(2)
        class_name = getattr(ParserState, "_current_class_name", None)
        if class_name:
            fields = ParserState.class_field_types.get(class_name, {})
            ftype = fields.get(field_name)
            if ftype and "Option[" in ftype:
                return True
        # Also search all classes for this field name
        for cname, fmap in ParserState.class_field_types.items():
            ftype = fmap.get(field_name)
            if ftype and "Option[" in ftype:
                return True
    return False


# --- comparison ---
@method(comparison)
def to_nim(self, prec=None):
    """comparison: bitor_expr (comp_op bitor_expr)* -> Nim: 'not in' -> 'notin', 'is not' -> 'isnot'; range 'in x .. y' -> 'x <= v and v <= y'"""
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
            # Bash file-comparison: f1 -nt f2 / f1 -ot f2
            if py_op in ("__bash_nt__", "__bash_ot__"):
                right = seq.nodes[1].to_nim(operand_prec)
                ParserState.nim_imports.add("times")
                cmp_op = ">" if py_op == "__bash_nt__" else "<"
                chain = (f"(getLastModificationTime({chain})"
                         f" {cmp_op} getLastModificationTime({right}))")
                continue
            nim_op = _PY_OP_TO_NIM.get(py_op, py_op)
            right = seq.nodes[1].to_nim(operand_prec)
            # | stays as | when operands are non-integer (e.g. string | Style pipe)
            if nim_op == "or" and py_op == "|" and _is_pipe_not_bitor([chain, right]):
                nim_op = "|"
            # x in (a, b, ...) — Python tuple literal → Nim array literal [a, b, ...]
            if nim_op in ("in", "notin") and right.startswith("(") and right.endswith(")"):
                right = "[" + right[1:-1] + "]"
            # Option-aware: x is/== None -> x.isNone, x is not/!= None -> x.isSome
            if right == "nil" and nim_op in ("isnot", "is", "==", "!="):
                is_option = _expr_is_option(chain)
                if is_option:
                    ParserState.nim_imports.add("options")
                    if nim_op in ("isnot", "!="):
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
    """not_prefix: 'not' inversion -> Nim: 'not inversion'"""
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
    """inversion: not_prefix | comparison"""
    return self.nodes[0].to_nim(prec)


# --- conjunction / disjunction ---
@method(conjunction)
def to_nim(self, prec=None):
    """conjunction: inversion ('and' inversion)* -> Nim: 'and' unchanged"""
    return binop_to_nim(self, prec, PREC_AND)


@method(disjunction)
def to_nim(self, prec=None):
    """disjunction: conjunction ('or' conjunction)* -> Nim: 'or' unchanged"""
    return binop_to_nim(self, prec, PREC_OR)


# --- walrus ---
@method(walrus)
def to_nim(self, prec=None):
    """walrus: IDENTIFIER ':=' expression -> Nim: IDENTIFIER = expression (no walrus in Nim)"""
    # Nim has no walrus; emit as assignment
    name = self.nodes[0].to_nim()
    val = self.nodes[2].to_nim()
    result = f"{name} = {val}"
    if prec is not None and PREC_WALRUS < prec:
        return f"({result})"
    return result


@method(named_expression)
def to_nim(self, prec=None):
    """named_expression: walrus | expression"""
    return self.nodes[0].to_nim(prec)


# --- conditional ---
@method(conditional)
def to_nim(self, prec=None):
    """conditional: disjunction 'if' disjunction 'else' expression -> Nim: 'if cond: a else: b'"""
    # Python: value if cond else alt -> Nim: (if cond: value else: alt)
    value = self.nodes[0].to_nim()
    cond = _nim_truthiness(self.nodes[1].to_nim())
    alt = self.nodes[2].to_nim()
    result = f"(if {cond}: {value} else: {alt})"
    return result


# --- lambda ---
@method(lambda_param)
def to_nim(self, prec=None):
    """lambda_param: IDENTIFIER ['=' expression] -> Nim: param declaration in proc"""
    name = self.nodes[0].to_nim()
    if len(self.nodes) > 1 and hasattr(self.nodes[1], "nodes") and self.nodes[1].nodes:
        seq = self.nodes[1].nodes[0]
        default = seq.nodes[0].to_nim()
        return f"{name}: auto = {default}"
    return f"{name}: auto"


@method(lambda_star)
def to_nim(self, prec=None):
    """lambda_star: '*' IDENTIFIER -> Nim: varargs (approximated)"""
    # Nim has no *args; emit as varargs
    return f"{self.nodes[1].to_nim()}: varargs[auto]"


@method(lambda_dstar)
def to_nim(self, prec=None):
    """lambda_dstar: '**' IDENTIFIER -> Nim: (no direct equivalent, emitted as comment)"""
    # Nim has no **kwargs; keep as-is
    return f"**{self.nodes[0].to_nim()}"


@method(lambda_params_entry)
def to_nim(self, prec=None):
    """lambda_params_entry: lambda_dstar | lambda_star | lambda_param"""
    return self.nodes[0].to_nim()


@method(lambda_params)
def to_nim(self, prec=None):
    """lambda_params: lambda_params_entry (',' lambda_params_entry)* -> Nim: comma-separated proc params"""
    parts = [self.nodes[0].to_nim()]
    if len(self.nodes) > 1 and hasattr(self.nodes[1], "nodes"):
        for seq in self.nodes[1].nodes:
            if hasattr(seq, "nodes") and seq.nodes:
                parts.append(seq.nodes[0].to_nim())
    return ", ".join(parts)


@method(lambda_expr)
def to_nim(self, prec=None):
    """lambda_expr: 'lambda' lambda_params? ':' expression -> Nim: 'proc(params): expr'"""
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
    """expression: conditional | lambda_expr | disjunction"""
    return self.nodes[0].to_nim(prec)


# --- expressions ---
@method(expressions)
def to_nim(self, prec=None):
    """expressions: expression (',' expression)* ','? -> Nim: comma-separated; trailing comma omitted"""
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
    """yield_from: 'yield' 'from' expression -> Nim: 'yield expression' (iterator)"""
    # Nim has no yield from; emit as loop
    return f"for _item in {self.nodes[0].to_nim()}: yield _item"


@method(yield_val)
def to_nim(self, prec=None):
    """yield_val: 'yield' star_expressions? -> Nim: 'yield expression'"""
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
    """yield_expr: yield_from | yield_val"""
    return self.nodes[0].to_nim()


# --- star expressions ---
@method(star_single)
def to_nim(self, prec=None):
    """star_single: '*' bitor_expr -> Nim: 'bitor_expr' (spread not directly supported)"""
    return f"*{self.nodes[1].to_nim()}"


@method(star_expression)
def to_nim(self, prec=None):
    """star_expression: star_single | expression"""
    return self.nodes[0].to_nim(prec)


@method(star_expressions)
def to_nim(self, prec=None):
    """star_expressions: star_expression (',' star_expression)* ','?"""
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
    """slice_3: expression ':' expression ':' expression -> Nim: a[lo..hi] with step (approximated)"""
    # a:b:c -> countup(a, b-1, c) — complex; emit as-is for now
    return f"{self.nodes[0].to_nim()}:{self.nodes[2].to_nim()}:{self.nodes[4].to_nim()}"


@method(slice_3ns)
def to_nim(self, prec=None):
    """slice_3ns: expression ':' ':' expression (no stop) -> Nim: a[lo..^1 by step]"""
    return f"{self.nodes[0].to_nim()}::{self.nodes[3].to_nim()}"


@method(slice_3nn)
def to_nim(self, prec=None):
    """slice_3nn: ':' expression ':' expression (no start) -> Nim: a[0..hi by step]"""
    return f":{self.nodes[1].to_nim()}:{self.nodes[3].to_nim()}"


@method(slice_3bare)
def to_nim(self, prec=None):
    """slice_3bare: ':' ':' expression (no start, no stop) -> Nim: step-only slice"""
    return f"::{self.nodes[2].to_nim()}"


@method(slice_2)
def to_nim(self, prec=None):
    """slice_2: expression ':' expression -> Nim: a[lo..<hi] or a[lo..^n] for negative index"""
    lo = self.nodes[0].to_nim()
    hi = self.nodes[2].to_nim()
    # Negative index: a[lo:-n] -> a[lo..^n]
    if hi.startswith("-") and hi[1:].isdigit():
        return f"{lo}..^{hi[1:]}"
    return f"{lo}..<{hi}"


@method(slice_1_start)
def to_nim(self, prec=None):
    """slice_1_start: expression ':' -> Nim: a[lo..^1]"""
    return f"{self.nodes[0].to_nim()}..^1"


@method(slice_1_stop)
def to_nim(self, prec=None):
    """slice_1_stop: ':' expression -> Nim: a[0..<hi]"""
    return f"0..<{self.nodes[1].to_nim()}"


@method(slice_bare)
def to_nim(self, prec=None):
    """slice_bare: ':' (bare slice) -> Nim: a[0..^1]"""
    return ":"


@method(slice_full)
def to_nim(self, prec=None):
    """slice_full: slice_3 | slice_3ns | slice_3nn | slice_3bare | slice_2 | slice_1_start | slice_1_stop | slice_bare"""
    return self.nodes[0].to_nim()


@method(slice_expr)
def to_nim(self, prec=None):
    """slice_expr: slice_full | named_expression"""
    return self.nodes[0].to_nim()


@method(slices)
def to_nim(self, prec=None):
    """slices: slice_expr (',' slice_expr)* ','?"""
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
    """kwarg: IDENTIFIER '=' expression -> Nim: 'name = value'"""
    return f"{self.nodes[0].to_nim()} = {self.nodes[1].to_nim()}"


@method(star_arg)
def to_nim(self, prec=None):
    """star_arg: '*' expression -> Nim: approximated as positional"""
    return f"*{self.nodes[1].to_nim()}"


@method(dstar_arg)
def to_nim(self, prec=None):
    """dstar_arg: '**' expression -> Nim: approximated"""
    return f"**{self.nodes[0].to_nim()}"


@method(arg)
def to_nim(self, prec=None):
    """arg: kwarg | dstar_arg | star_arg | expression"""
    return self.nodes[0].to_nim()


@method(arguments)
def to_nim(self, prec=None):
    """arguments: arg (',' arg)* ','?"""
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
    """genexpr_arg: named_expression (for_if_clauses)? -> Nim: iterator expression argument"""
    return self.nodes[0].to_nim()


# --- comprehensions ---
@method(target)
def to_nim(self, prec=None):
    """target: IDENTIFIER (',' IDENTIFIER)* -> Nim: for-loop target, tuple or single var"""
    parts = [self.nodes[0].to_nim()]
    if len(self.nodes) > 1 and hasattr(self.nodes[1], "nodes"):
        for seq in self.nodes[1].nodes:
            if hasattr(seq, "nodes") and len(seq.nodes) >= 1:
                parts.append(seq.nodes[0].to_nim())
    return ", ".join(parts)


@method(for_if_clause)
def to_nim(self, prec=None):
    """for_if_clause: 'for' target 'in' disjunction ('if' disjunction)* -> Nim: 'for target in iter (if cond)'"""
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
    """for_if_clauses: for_if_clause+ -> Nim: nested for/if clauses (single clause)"""
    parts = _for_if_clauses_parts(self)
    return " ".join(parts)


def _for_if_clauses_parts(node):
    """Return list of individual for_if_clause strings from a for_if_clauses node."""
    parts = []
    for n in node.nodes:
        if hasattr(n, "to_nim"):
            parts.append(n.to_nim())
        elif hasattr(n, "nodes"):
            for nn in n.nodes:
                if hasattr(nn, "to_nim"):
                    parts.append(nn.to_nim())
    return parts


def _build_nested_collect(clause_parts, expr):
    """Build a properly nested collect() expression for multiple for-clauses.

    Single clause:   collect(for x in xs: expr)
    Multiple:        collect(for ship in ships: (for zone in zones_for_ship(ship): zone))
    """
    import re as _re
    # Build from the innermost clause outward
    result = expr
    for i, clause in enumerate(reversed(clause_parts)):
        m = _re.match(r"(for .+ in .+?) if (.+)$", clause)
        is_innermost = (i == 0)
        if m:
            for_part, cond = m.group(1), m.group(2)
            inner = result if is_innermost else f"({result})"
            result = f"{for_part}: (if {cond}: {inner})"
        else:
            inner = result if is_innermost else f"({result})"
            result = f"{clause}: {inner}"
    return f"collect({result})"


@method(listcomp)
def to_nim(self, prec=None):
    """listcomp: named_expression for_if_clauses -> Nim: collect(...) with proper nesting"""
    ParserState.nim_imports.add("sugar")
    expr = self.nodes[0].to_nim()
    clause_parts = _for_if_clauses_parts(self.nodes[1])
    return _build_nested_collect(clause_parts, expr)


@method(genexpr)
def to_nim(self, prec=None):
    """genexpr: named_expression for_if_clauses -> Nim: collect(...) with proper nesting"""
    ParserState.nim_imports.add("sugar")
    expr = self.nodes[0].to_nim()
    clause_parts = _for_if_clauses_parts(self.nodes[1])
    return _build_nested_collect(clause_parts, expr)


@method(dictcomp)
def to_nim(self, prec=None):
    """dictcomp: expression ':' expression for_if_clauses -> Nim: toTable comprehension"""
    key = self.nodes[0].to_nim()
    val = self.nodes[1].to_nim()
    clause_parts = _for_if_clauses_parts(self.nodes[2])
    ParserState.nim_imports.add("sugar")
    ParserState.nim_imports.add("tables")
    inner = _build_nested_collect(clause_parts, f"{{{key}: {val}}}")
    # dictcomp uses collect(initTable, ...)
    return inner.replace("collect(", "collect(initTable, ", 1)


@method(setcomp)
def to_nim(self, prec=None):
    """setcomp: expression for_if_clauses -> Nim: toHashSet comprehension"""
    expr = self.nodes[0].to_nim()
    clause_parts = _for_if_clauses_parts(self.nodes[1])
    inner = _build_nested_collect(clause_parts, expr)
    return inner.replace("collect(", "collect(initHashSet, ", 1)


# --- dict/set makers ---
@method(kvpair)
def to_nim(self, prec=None):
    """kvpair: expression ':' expression -> Nim: 'key: value' pair"""
    return f"{self.nodes[0].to_nim()}: {self.nodes[2].to_nim()}"


@method(dictmaker)
def to_nim(self, prec=None):
    """dictmaker: kvpair (',' kvpair)* ','? -> Nim: key-value pairs for toTable"""
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
    """setmaker: star_expression (',' star_expression)* ','? -> Nim: elements for toHashSet"""
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
        ("{}", "initHashSet()"),
        ("{1: 2, 3: 4}", "{1: 2, 3: 4}.toTable"),
        ("{1, 2, 3}", "[1, 2, 3].toHashSet"),
        ('{"a", "b"}', '["a", "b"].toHashSet'),
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
    """named_tuple_field: IDENTIFIER ':' expression -> Nim: field initializer in object constructor"""
    name = self.nodes[0].to_nim()
    # nodes[1] is V_COLON, nodes[2] is expression
    val = self.nodes[2].to_nim()
    return f"{name}: {val}"

@method(named_tuple_lit)
def to_nim(self, prec=None):
    """named_tuple_lit: '(' named_tuple_field (',' named_tuple_field)* ')' -> Nim: TypeName(field: val, ...)"""
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
