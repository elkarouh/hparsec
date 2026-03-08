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

import sys
sys.path.insert(0, "..")

from hek_parsec import method
from hek_py3_expr import *  # noqa: F403 — need all parser rule names
from hek_py3_expr import (
    PREC_WALRUS, PREC_CONDITIONAL, PREC_OR, PREC_AND, PREC_NOT,
    PREC_CMP, PREC_BOR, PREC_BXOR, PREC_BAND, PREC_SHIFT,
    PREC_ARITH, PREC_TERM, PREC_UNARY, PREC_POWER, PREC_ATOM,
    _COMP_OPS, _get_bracket_start, parse_expr,
)

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
            py_op = seq.nodes[0].to_py()
            nim_op = _PY_OP_TO_NIM.get(py_op, py_op)
            right = seq.nodes[1].to_nim(right_prec)
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
    return self.node


@method(IDENTIFIER)
def to_nim(self, prec=None):
    return self.node


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
    return "newTable()"


@method(dict_display)
def to_nim(self, prec=None):
    inner_node = self.nodes[1]
    # If inner is a dictcomp, collect() handles it — no {} wrapper
    if type(inner_node).__name__ == "dictcomp":
        return inner_node.to_nim()
    return "{" + inner_node.to_nim() + "}.toTable"


@method(set_display)
def to_nim(self, prec=None):
    inner_node = self.nodes[1]
    # If inner is a setcomp, collect() handles it — no {} wrapper
    if type(inner_node).__name__ == "setcomp":
        return inner_node.to_nim()
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
    return "[" + self.nodes[0].to_nim() + "]"


@method(attr_trailer)
def to_nim(self, prec=None):
    return "." + self.nodes[0].to_nim()


@method(trailer)
def to_nim(self, prec=None):
    return self.nodes[0].to_nim()


@method(primary)
def to_nim(self, prec=None):
    result = self.nodes[0].to_nim()
    if len(self.nodes) > 1 and hasattr(self.nodes[1], "nodes") and self.nodes[1].nodes:
        for tr in self.nodes[1].nodes:
            result += tr.to_nim()
    return result


# --- await ---
@method(await_expr)
def to_nim(self, prec=None):
    return f"await {self.nodes[0].to_nim()}"


@method(await_primary)
def to_nim(self, prec=None):
    return self.nodes[0].to_nim(prec)


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
                and hasattr(first_seq.nodes[0], "to_py")
                and first_seq.nodes[0].to_py() in _COMP_OPS
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
            py_op = seq.nodes[0].to_py()
            nim_op = _PY_OP_TO_NIM.get(py_op, py_op)
            right = seq.nodes[1].to_nim(operand_prec)
            chain += f" {nim_op} {right}"
    if prec is not None and PREC_CMP < prec:
        return f"({chain})"
    return chain


# --- inversion ---
@method(not_prefix)
def to_nim(self, prec=None):
    result = f"not {self.nodes[0].to_nim(PREC_NOT)}"
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
        return f"yield {self.nodes[0].nodes[0].to_nim()}"
    elif self.nodes:
        return f"yield {self.nodes[0].to_nim()}"
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
    expr = self.nodes[0].to_nim()
    clauses = self.nodes[1].to_nim()
    return f"collect({clauses}: {expr})"


@method(genexpr)
def to_nim(self, prec=None):
    # (expr for x in xs) -> iterator: for x in xs: yield expr
    expr = self.nodes[0].to_nim()
    clauses = self.nodes[1].to_nim()
    return f"collect({clauses}: {expr})"


@method(dictcomp)
def to_nim(self, prec=None):
    # {k: v for ...} -> collect(initTable, for ...: {k: v})
    key = self.nodes[0].to_nim()
    val = self.nodes[1].to_nim()
    clauses = self.nodes[2].to_nim()
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
    print("=" * 60)
    print("Python -> Nim Expression Translation Tests")
    print("=" * 60)

# Nim translation tests
# ==================================================================
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
    ("{}", "newTable()"),
    ("{1: 2, 3: 4}", "{1: 2, 3: 4}.toTable"),
    ("{1, 2, 3}", "{1, 2, 3}.toHashSet"),
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
