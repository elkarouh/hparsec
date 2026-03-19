#!/usr/bin/env python3
"""Python 3.14 Expression Parser using hek_parsec combinator framework.

Implements the Python 3.14 expression grammar with correct operator
precedence, rewritten from PEG left-recursive form into iterative
right-recursive form suitable for hek_parsec.

Precedence (low to high):
    lambda, if/else, :=, or, and, not, comparisons, |, ^, &, <</>>,
    +/-, */%//@, unary +/-/~, **, await, atom+trailers

New in Python 3.x (vs 2.7):
    - walrus operator:  x := expr
    - await expression: await f()
    - matmul operator:  a @ b
    - f-strings:        f"hello {name}"
    - ellipsis literal: ...
    - set literals:     {1, 2, 3}
    - comprehensions:   [x for x in xs], {k:v for k,v in d}, {x for x in s}
    - star expressions: *x in calls and displays
    - extended slicing:  a[1:2:3]
    - yield expressions: yield x, yield from x

Removed from Python 2:
    - <> operator, backtick repr, 123L long literals

Usage:
    ast, rest = expression.parse(Input("1 + 2 * 3"))
    print(ast.to_py())  # (1 + (2 * 3))
"""

import sys, os
_dir = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(_dir, ".."))
sys.path.insert(0, os.path.join(_dir, "..", "HPYTHON_GRAMMAR"))

from py3expr import *
from hek_parsec import method, ParserState



def _get_bracket_start(node):
    """Extract the (line, col) start position from a bracket node."""
    if hasattr(node, 'nodes') and node.nodes:
        tok = node.nodes[0]
        if hasattr(tok, 'start'):
            return tok.start
    if hasattr(node, 'start'):
        return node.start
    return None




###############################################################################
# Helper: left-associative binary operator to_py
###############################################################################


def binop_to_py(self, prec=None, my_prec=None):
    """Generic to_py for left-associative binary operators.

    Due to Sequence flattening, inner rule nodes may be inlined.
    e.g. sum_expr parsing 'a * b + c' produces:
      nodes = [power(a), Several_Times[(*,b)], Several_Times[(+,c)]]
    where the first Several_Times is from term (inner) and the second
    is from sum_expr (this level).

    Strategy: find the LAST Several_Times with (op, operand) pairs —
    that's ours. Everything before it is the base (first operand),
    reconstructed by calling binop_to_py on a synthetic node.

    Args:
        prec: parent context's precedence (None = no wrapping needed)
        my_prec: this operator's precedence level
    """
    # Find the last Several_Times that has (op, operand) pairs
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
        # No operator repetitions, just delegate to child
        return self.nodes[0].to_py(prec)

    # Reconstruct the base from nodes before last_st_idx
    # Left child gets my_prec (same precedence, left-assoc = no parens)
    left_prec = my_prec
    if last_st_idx == 1:
        result = self.nodes[0].to_py(left_prec)
    else:
        # Inner nodes were flattened; rebuild by calling binop_to_py
        # on a mock with just the prefix nodes
        class _Mock:
            pass

        mock = _Mock()
        mock.nodes = self.nodes[:last_st_idx]
        result = binop_to_py(mock, left_prec, my_prec)

    # Apply our (op, operand) pairs
    # Right child gets my_prec+1 (forces parens for same-precedence right operands)
    right_prec = my_prec + 1 if my_prec is not None else None
    st = self.nodes[last_st_idx]
    for seq in st.nodes:
        if hasattr(seq, "nodes") and len(seq.nodes) >= 2:
            op = seq.nodes[0].to_py()
            right = seq.nodes[1].to_py(right_prec)
            result = f"{result} {op} {right}"

    # Only wrap in parens if parent context requires higher precedence
    if prec is not None and my_prec is not None and my_prec < prec:
        return f"({result})"
    return result


###############################################################################
# to_py() methods
###############################################################################


# --- leaf tokens ---
@method(NUMBER)
def to_py(self, prec=None):
    """NUMBER: a numeric literal token."""
    return self.node


@method(STRING)
def to_py(self, prec=None):
    """STRING: a string literal token."""
    return self.node


@method(fstring)
def to_py(self, prec=None):
    """fstring: FSTRING_START FSTRING_MIDDLE? ('{' expr '}' FSTRING_MIDDLE?)* FSTRING_END

    Reassemble by collecting the raw token strings from all nodes.
    FSTRING_START/MIDDLE/END nodes are Fmap nodes (str); expression nodes have to_py().
    OP nodes for { and } are Fmap nodes (str).
    """
    parts = []
    def _collect(node):
        tname = type(node).__name__
        if tname == "Fmap":
            parts.append(node.node)
        elif tname in ("Several_Times", "Sequence_Parser"):
            for child in node.nodes:
                _collect(child)
        elif hasattr(node, "to_py"):
            parts.append(node.to_py())
        elif hasattr(node, "node"):
            parts.append(node.node)
    for node in self.nodes:
        _collect(node)
    return "".join(parts)


@method(IDENTIFIER)
def to_py(self, prec=None):
    """IDENTIFIER: a name token (filtered by str.isidentifier)."""
    name = self.node
    # Resolve tick attributes: Type__tick__First -> first value of subrange/enum
    if "__tick__" in name:
        type_name, _, attr = name.partition("__tick__")
        info = ParserState.tick_types.get(type_name)
        if info and attr in info:
            val = info[attr]
            return str(val)
        # Enum next/prev: Type'Next -> Type(Type.value + 1)
        if attr == "Next":
            return f"{type_name}({type_name}.value + 1)"
        elif attr == "Prev":
            return f"{type_name}({type_name}.value - 1)"
    return name


@method(K_NONE)
def to_py(self, prec=None):
    """K_NONE: 'None'"""
    return "None"


@method(K_TRUE)
def to_py(self, prec=None):
    """K_TRUE: 'True'"""
    return "True"


@method(K_FALSE)
def to_py(self, prec=None):
    """K_FALSE: 'False'"""
    return "False"


@method(ellipsis_lit)
def to_py(self, prec=None):
    """ellipsis_lit: '...'"""
    return "..."


# Visible operators — all just return their string
for _p in [
    V_PLUS,
    V_MINUS,
    V_STAR,
    V_SLASH,
    V_PERCENT,
    V_DSLASH,
    V_DSTAR,
    V_TILDE,
    V_AT,
    V_PIPE,
    V_CARET,
    V_AMPER,
    V_LSHIFT,
    V_RSHIFT,
    V_LT,
    V_GT,
    V_EQ,
    V_NE,
    V_LE,
    V_GE,
    V_COLONEQUAL,
    SSTAR,
    K_AND,
    K_OR,
    K_NOT,
    K_IN,
    K_IS,
]:

    @method(_p)
    def to_py(self, prec=None):
        """Visible operator token: returns operator string unchanged."""
        return self.node


# --- str_concat ---
@method(str_concat)
def to_py(self, prec=None):
    """str_concat: STRING STRING+"""
    parts = [self.nodes[0].to_py()]
    rep = self.nodes[1]
    if hasattr(rep, "nodes"):
        parts.extend(n.to_py() for n in rep.nodes)
    else:
        parts.append(rep.to_py())
    return " ".join(parts)


# --- atom containers ---

# Registry: frozenset of field names -> type name, for named tuple constructor emission
_named_tuple_registry = {}  # {frozenset(field_names): type_name}

def _register_named_tuple(type_name, field_names):
    """Register a NamedTuple type so named_tuple_lit can emit constructors."""
    _named_tuple_registry[frozenset(field_names)] = type_name

def _lookup_named_tuple(field_names):
    """Look up a NamedTuple type by its field names."""
    return _named_tuple_registry.get(frozenset(field_names))

def _has_named_tuple(node):
    """Check if node tree contains named_tuple_field nodes needing transformation."""
    if type(node).__name__ == "named_tuple_field":
        return True
    if hasattr(node, "nodes"):
        return any(_has_named_tuple(c) for c in node.nodes)
    return False

@method(empty_paren)
def to_py(self, prec=None):
    """empty_paren: '(' ')'"""
    return "()"


@method(paren_group)
def to_py(self, prec=None):
    """paren_group: '(' (yield_expr | walrus | expressions) ')'
    Explicit parens from source — always preserved."""
    from hek_tokenize import get_multiline_brackets
    pos = _get_bracket_start(self.nodes[0])
    ml = get_multiline_brackets()
    if pos and pos in ml and not _has_named_tuple(self):
        return ml[pos]
    return f"({self.nodes[1].to_py()})"


@method(empty_list)
def to_py(self, prec=None):
    """empty_list: '[' ']'"""
    return "[]"


@method(list_display)
def to_py(self, prec=None):
    """list_display: '[' (listcomp | star_expressions) ']'"""
    from hek_tokenize import get_multiline_brackets
    pos = _get_bracket_start(self.nodes[0])
    ml = get_multiline_brackets()
    if pos and pos in ml and not _has_named_tuple(self):
        return ml[pos]
    return f"[{self.nodes[1].to_py()}]"


@method(empty_set)
def to_py(self, prec=None):
    """empty_set: '{' '}' -> Python: set()

    HPython treats {} as an empty set literal.  Python's {} creates an empty
    dict, so we always emit set() here.  Use type annotations on the variable
    to convey the element type; the Nim backend reads those to pick the right
    Nim initialiser.
    """
    return "set()"


@method(empty_dict)
def to_py(self, prec=None):
    """empty_dict: '{' ':' '}' -> Python: {}

    HPython uses {:} as the empty dict literal to free up {} for empty sets.
    """
    return "{}"


@method(dict_display)
def to_py(self, prec=None):
    """dict_display: '{' (dictcomp | dictmaker) '}'"""
    from hek_tokenize import get_multiline_brackets
    pos = _get_bracket_start(self.nodes[0])
    ml = get_multiline_brackets()
    if pos and pos in ml:
        if not _has_named_tuple(self):
            return ml[pos]
    return "{" + self.nodes[1].to_py() + "}"


@method(enum_array_display)
def to_py(self, prec=None):
    """enum_array_display: '[' enum_key ':' value (',' enum_key ':' value)* ']' -> Python: dict {K: V, ...}"""
    return "{" + self.nodes[1].to_py() + "}"


@method(set_display)
def to_py(self, prec=None):
    """set_display: '{' (setcomp | setmaker) '}'"""
    from hek_tokenize import get_multiline_brackets
    pos = _get_bracket_start(self.nodes[0])
    ml = get_multiline_brackets()
    if pos and pos in ml and not _has_named_tuple(self):
        return ml[pos]
    return "{" + self.nodes[1].to_py() + "}"


@method(atom)
def to_py(self, prec=None):
    """atom: empty_paren | paren_group | empty_list | list_display
    | empty_set | empty_dict | dict_display | set_display | '...'
    | 'None' | 'True' | 'False' | IDENTIFIER | NUMBER
    | str_concat | STRING"""
    return self.nodes[0].to_py(prec)


# --- trailers ---
@method(call_trailer)
def to_py(self, prec=None):
    """call_trailer: '(' arguments? ')'"""
    from hek_tokenize import get_multiline_brackets
    pos = _get_bracket_start(self.nodes[0])
    ml = get_multiline_brackets()
    if pos and pos in ml and not _has_named_tuple(self):
        return ml[pos]
    if len(self.nodes) > 1 and hasattr(self.nodes[1], "nodes") and self.nodes[1].nodes:
        return "(" + self.nodes[1].nodes[0].to_py() + ")"
    elif len(self.nodes) > 1 and hasattr(self.nodes[1], "to_py"):
        return "(" + self.nodes[1].to_py() + ")"
    return "()"


@method(slice_trailer)
def to_py(self, prec=None):
    """slice_trailer: '[' slices ']'"""
    return "[" + self.nodes[0].to_py() + "]"


@method(attr_trailer)
def to_py(self, prec=None):
    """attr_trailer: '.' IDENTIFIER"""
    attr_name = self.nodes[0].node if hasattr(self.nodes[0], 'node') else str(self.nodes[0])
    # Handle tick attributes on expressions: .field'Next / .field'Prev
    if "__tick__" in attr_name:
        base, _, tick_attr = attr_name.partition("__tick__")
        if tick_attr in ("Next", "Prev"):
            # Store tick info for primary.to_py() to wrap the expression
            self._tick_base = base
            self._tick_attr = tick_attr
            return "." + base  # just emit .field, primary will wrap
    return "." + self.nodes[0].to_py()


@method(trailer)
def to_py(self, prec=None):
    """trailer: call_trailer | slice_trailer | attr_trailer"""
    return self.nodes[0].to_py()


# --- primary: atom + trailer[:] ---
@method(primary)
def to_py(self, prec=None):
    """primary: atom trailer*"""
    result = self.nodes[0].to_py()
    if len(self.nodes) > 1 and hasattr(self.nodes[1], "nodes") and self.nodes[1].nodes:
        for tr in self.nodes[1].nodes:
            result += tr.to_py()
            # Handle tick attributes: wrap expr.field with type(expr.field)(expr.field.value +/- 1)
            if hasattr(tr, '_tick_attr'):
                op = "+" if tr._tick_attr == "Next" else "-"
                result = f"type({result})({result}.value {op} 1)"
    return result


# --- await ---
@method(await_expr)
def to_py(self, prec=None):
    """await_expr: 'await' primary"""
    return f"await {self.nodes[0].to_py()}"


@method(await_primary)
def to_py(self, prec=None):
    """await_primary: await_expr | primary"""
    return self.nodes[0].to_py(prec)


# --- range expression (.., ..<) ---
@method(range_incl_op)
def to_py(self, prec=None):
    """range_incl_op: '..' (inclusive range operator) -> Python: used in range(lo, hi + 1)"""
    return ".."

@method(range_excl_op)
def to_py(self, prec=None):
    """range_excl_op: '..<' (exclusive upper bound) -> Python: used in range(lo, hi)"""
    return "..<"

@method(range_expr)
def to_py(self, prec=None):
    """range_expr: bitor_expr (('..' | '..<') bitor_expr)? -> Python: 'lo .. hi' -> range(lo, hi+1); 'lo ..< hi' -> range(lo, hi)"""
    # lo .. hi  -> range(lo, hi + 1)  (inclusive)
    # lo ..< hi -> range(lo, hi)      (exclusive)
    lo = self.nodes[0].to_py(prec)
    # Check if there's a range operator (Several_Times node with content)
    if len(self.nodes) < 2:
        return lo
    st = self.nodes[1]
    if not hasattr(st, 'nodes') or not st.nodes:
        return lo
    # st.nodes[0] is a Sequence_Parser: [range_op, bitor_expr]
    seq = st.nodes[0]
    if not hasattr(seq, 'nodes') or len(seq.nodes) < 2:
        return lo
    range_op_node = seq.nodes[0]
    hi = seq.nodes[1].to_py(prec)
    # Detect exclusive (..<) vs inclusive (..)
    is_exclusive = (hasattr(range_op_node, 'nodes')
        and any(hasattr(n, 'node') and str(n.node) == '<'
                for n in range_op_node.nodes))
    if is_exclusive:
        return f"range({lo}, {hi})"
    else:
        return f"range({lo}, {hi} + 1)"


# --- power ---
@method(power_rhs)
def to_py(self, prec=None):
    """power_rhs: '**' factor"""
    return f"** {self.nodes[1].to_py(prec)}"


@method(power)
def to_py(self, prec=None):
    """power: await_primary power_rhs*  (right-associative)"""
    has_power = False
    for node in self.nodes[1:]:
        if not hasattr(node, "nodes") or not node.nodes:
            continue
        first = node.nodes[0]
        if type(first).__name__ == "power_rhs":
            has_power = True
            break

    if not has_power:
        # No ** operator, just delegate
        result = self.nodes[0].to_py(prec)
        for node in self.nodes[1:]:
            if not hasattr(node, "nodes") or not node.nodes:
                continue
            for tr in node.nodes:
                result += tr.to_py()
        return result

    # Right-associative: pass PREC_POWER+1 to left, PREC_POWER to right
    result = self.nodes[0].to_py(PREC_POWER + 1)
    for node in self.nodes[1:]:
        if not hasattr(node, "nodes") or not node.nodes:
            continue
        first = node.nodes[0]
        fname = type(first).__name__
        if fname == "power_rhs":
            exponents = [seq.nodes[1].to_py(PREC_POWER) for seq in node.nodes]
            for exp in reversed(exponents):
                result = f"{result} ** {exp}"
        elif fname in (
            "call_trailer",
            "index_trailer",
            "slice_trailer",
            "attr_trailer",
            "trailer",
        ):
            for tr in node.nodes:
                result += tr.to_py()
    if prec is not None and PREC_POWER < prec:
        return f"({result})"
    return result


# --- factor (unary) ---
@method(unary_plus)
def to_py(self, prec=None):
    """unary_plus: '+' factor"""
    result = f"+{self.nodes[0].to_py(PREC_UNARY)}"
    if prec is not None and PREC_UNARY < prec:
        return f"({result})"
    return result


@method(unary_minus)
def to_py(self, prec=None):
    """unary_minus: '-' factor"""
    result = f"-{self.nodes[0].to_py(PREC_UNARY)}"
    if prec is not None and PREC_UNARY < prec:
        return f"({result})"
    return result


@method(unary_tilde)
def to_py(self, prec=None):
    """unary_tilde: '~' factor"""
    result = f"~{self.nodes[0].to_py(PREC_UNARY)}"
    if prec is not None and PREC_UNARY < prec:
        return f"({result})"
    return result


@method(factor)
def to_py(self, prec=None):
    """factor: unary_plus | unary_minus | unary_tilde | power"""
    return self.nodes[0].to_py(prec)


# --- left-associative binary ops ---
@method(term)
def to_py(self, prec=None):
    """term: factor (('*' | '/' | '//' | '%' | '@') factor)*"""
    return binop_to_py(self, prec, PREC_TERM)


@method(sum_expr)
def to_py(self, prec=None):
    """sum_expr: term (('+' | '-') term)*"""
    return binop_to_py(self, prec, PREC_ARITH)


@method(shift_expr)
def to_py(self, prec=None):
    """shift_expr: sum_expr (('<<' | '>>') sum_expr)*"""
    return binop_to_py(self, prec, PREC_SHIFT)


@method(bitand_expr)
def to_py(self, prec=None):
    """bitand_expr: shift_expr ('&' shift_expr)*"""
    return binop_to_py(self, prec, PREC_BAND)


@method(bitxor_expr)
def to_py(self, prec=None):
    """bitxor_expr: bitand_expr ('^' bitand_expr)*"""
    return binop_to_py(self, prec, PREC_BXOR)


@method(bitor_expr)
def to_py(self, prec=None):
    """bitor_expr: bitxor_expr ('|' bitxor_expr)*"""
    return binop_to_py(self, prec, PREC_BOR)


# --- comparison ---
@method(not_in_op)
def to_py(self, prec=None):
    """not_in_op: 'not' 'in'"""
    return "not in"


@method(is_not_op)
def to_py(self, prec=None):
    """is_not_op: 'is' 'not'"""
    return "is not"


@method(comp_op)
def to_py(self, prec=None):
    """comp_op: '==' | '!=' | '<=' | '<' | '>=' | '>'
    | not_in_op | is_not_op | 'in' | 'is'"""
    return self.nodes[0].to_py()


_COMP_OPS = {"==", "!=", "<", ">", "<=", ">=", "in", "is", "not in", "is not"}


@method(comparison)
def to_py(self, prec=None):
    """comparison: bitor_expr (comp_op bitor_expr)*  (chained, not nested)"""
    # Find the LAST Several_Times whose first pair's operator is a comp_op
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
        # Check if this is a range expression (2 .. n or 2 ..< n)
        # that was flattened into comparison from range_expr
        for node in self.nodes:
            if (type(node).__name__ == "Several_Times"
                    and hasattr(node, "nodes") and node.nodes):
                seq = node.nodes[0]
                if hasattr(seq, "nodes") and len(seq.nodes) >= 2:
                    op_node = seq.nodes[0]
                    op_name = type(op_node).__name__
                    if op_name in ("range_incl_op", "range_excl_op"):
                        lo = self.nodes[0].to_py(prec)
                        hi = seq.nodes[1].to_py(prec)
                        if op_name == "range_excl_op":
                            return f"range({lo}, {hi})"
                        else:
                            return f"range({lo}, {hi} + 1)"
        # No comparison ops — delegate to binop_to_py for inner reconstruction
        return binop_to_py(self, prec, PREC_CMP)

    # Reconstruct base from nodes before the comparison Several_Times
    operand_prec = PREC_CMP + 1
    if last_comp_idx == 1:
        base = self.nodes[0].to_py(operand_prec)
    else:
        # Reconstruct the base expression. Pass None as my_prec to avoid
        # incorrect wrapping - the inner binop_to_py will handle precedence.
        class _Mock:
            pass

        mock = _Mock()
        mock.nodes = self.nodes[:last_comp_idx]
        base = binop_to_py(mock, None, None)

    # Chain comparison operators (no nesting): a < b < c -> a < b < c
    chain = base
    st = self.nodes[last_comp_idx]
    for seq in st.nodes:
        if hasattr(seq, "nodes") and len(seq.nodes) >= 2:
            op = seq.nodes[0].to_py()
            # Handle 'in lo .. hi' / 'in lo ..< hi' -> 'lo <= x <= hi' / 'lo <= x < hi'
            if op == "in" and len(seq.nodes) >= 4:
                lo = seq.nodes[1].to_py(operand_prec)
                range_op_node = seq.nodes[2]
                hi = seq.nodes[3].to_py(operand_prec)
                is_exclusive = (hasattr(range_op_node, 'nodes')
                    and any(hasattr(n, 'node') and str(n.node) == '<'
                            for n in range_op_node.nodes))
                hi_op = "<" if is_exclusive else "<="
                chain = f"{lo} <= {chain} {hi_op} {hi}"
                continue
            right = seq.nodes[1].to_py(operand_prec)
            chain += f" {op} {right}"
    if prec is not None and PREC_CMP < prec:
        return f"({chain})"
    return chain


# --- inversion ---
@method(not_prefix)
def to_py(self, prec=None):
    """not_prefix: 'not' inversion"""
    result = f"not {self.nodes[0].to_py(PREC_NOT)}"
    if prec is not None and PREC_NOT < prec:
        return f"({result})"
    return result


@method(inversion)
def to_py(self, prec=None):
    """inversion: not_prefix | comparison"""
    return self.nodes[0].to_py(prec)


# --- conjunction / disjunction ---
@method(conjunction)
def to_py(self, prec=None):
    """conjunction: inversion ('and' inversion)*"""
    return binop_to_py(self, prec, PREC_AND)


@method(disjunction)
def to_py(self, prec=None):
    """disjunction: conjunction ('or' conjunction)*"""
    return binop_to_py(self, prec, PREC_OR)


# --- walrus / named_expression ---
@method(walrus)
def to_py(self, prec=None):
    """walrus: IDENTIFIER ':=' expression — nodes: [IDENTIFIER, V_COLONEQUAL, expression]"""
    result = f"{self.nodes[0].to_py()} := {self.nodes[2].to_py()}"
    if prec is not None and PREC_WALRUS < prec:
        return f"({result})"
    return result


@method(named_expression)
def to_py(self, prec=None):
    """named_expression: walrus | expression"""
    return self.nodes[0].to_py(prec)


# --- conditional ---
@method(conditional)
def to_py(self, prec=None):
    """conditional: disjunction 'if' disjunction 'else' expression"""
    result = f"{self.nodes[0].to_py()} if {self.nodes[1].to_py()} else {self.nodes[2].to_py()}"
    if prec is not None and PREC_CONDITIONAL < prec:
        return f"({result})"
    return result


# --- lambda ---
@method(lambda_param)
def to_py(self, prec=None):
    """lambda_param: IDENTIFIER ['=' expression]"""
    name = self.nodes[0].to_py()
    if len(self.nodes) > 1 and hasattr(self.nodes[1], "nodes") and self.nodes[1].nodes:
        # Optional part matched: Several_Times containing one Sequence_Parser (iop("=") + expression)
        seq = self.nodes[1].nodes[0]
        # iop("=") is ignored, so seq.nodes[0] is the expression
        default = seq.nodes[0].to_py()
        return f"{name}={default}"
    return name


@method(lambda_star)
def to_py(self, prec=None):
    """lambda_star: '*' IDENTIFIER — nodes: [SSTAR('*'), IDENTIFIER]"""
    return f"*{self.nodes[1].to_py()}"


@method(lambda_dstar)
def to_py(self, prec=None):
    """lambda_dstar: '**' IDENTIFIER"""
    return f"**{self.nodes[0].to_py()}"


@method(lambda_params_entry)
def to_py(self, prec=None):
    """lambda_params_entry: lambda_dstar | lambda_star | lambda_param"""
    return self.nodes[0].to_py()


@method(lambda_params)
def to_py(self, prec=None):
    """lambda_params: lambda_params_entry (',' lambda_params_entry)*"""
    parts = [self.nodes[0].to_py()]
    if len(self.nodes) > 1 and hasattr(self.nodes[1], "nodes"):
        for seq in self.nodes[1].nodes:
            if hasattr(seq, "nodes") and seq.nodes:
                parts.append(seq.nodes[0].to_py())
    return ", ".join(parts)


@method(lambda_expr)
def to_py(self, prec=None):
    """lambda_expr: 'lambda' lambda_params? ':' expression"""
    if len(self.nodes) >= 2:
        params_st = self.nodes[0]
        if hasattr(params_st, "nodes") and params_st.nodes:
            params = params_st.nodes[0].to_py()
        else:
            params = ""
        body = self.nodes[1].to_py()
        result = f"lambda {params}: {body}"
    else:
        body = self.nodes[0].to_py()
        result = f"lambda: {body}"
    if prec is not None and PREC_CONDITIONAL < prec:
        return f"({result})"
    return result


# --- expression ---
@method(expression)
def to_py(self, prec=None):
    """expression: conditional | lambda_expr | disjunction"""
    return self.nodes[0].to_py(prec)


# --- expressions ---
@method(expressions)
def to_py(self, prec=None):
    """expressions: expression (',' expression)* ','?"""
    parts = [self.nodes[0].to_py()]
    trailing_comma = False
    for node in self.nodes[1:]:
        if not hasattr(node, "nodes") or not node.nodes:
            continue
        found_pair = False
        for seq in node.nodes:
            if hasattr(seq, "nodes") and len(seq.nodes) >= 1:
                parts.append(seq.nodes[0].to_py())
                found_pair = True
        if not found_pair:
            # Several_Times from COMMA[:] — trailing comma
            trailing_comma = True
    result = ", ".join(parts)
    if len(parts) == 1 and trailing_comma:
        result += ","
    return result


# --- yield ---
@method(yield_from)
def to_py(self, prec=None):
    """yield_from: 'yield' 'from' expression"""
    return f"yield from {self.nodes[0].to_py()}"


@method(yield_val)
def to_py(self, prec=None):
    """yield_val: 'yield' star_expressions?"""
    if self.nodes and hasattr(self.nodes[0], "nodes") and self.nodes[0].nodes:
        return f"yield {self.nodes[0].nodes[0].to_py()}"
    elif self.nodes:
        return f"yield {self.nodes[0].to_py()}"
    return "yield"


@method(yield_expr)
def to_py(self, prec=None):
    """yield_expr: yield_from | yield_val"""
    return self.nodes[0].to_py()


# --- star expressions ---
@method(star_single)
def to_py(self, prec=None):
    """star_single: '*' bitor_expr"""
    return f"*{self.nodes[1].to_py()}"


@method(star_expression)
def to_py(self, prec=None):
    """star_expression: star_single | expression"""
    return self.nodes[0].to_py(prec)


@method(star_expressions)
def to_py(self, prec=None):
    """star_expressions: star_expression (',' star_expression)* ','?"""
    parts = [self.nodes[0].to_py()]
    for node in self.nodes[1:]:
        if not hasattr(node, "nodes") or not node.nodes:
            continue
        for seq in node.nodes:
            if hasattr(seq, "nodes") and len(seq.nodes) >= 1:
                parts.append(seq.nodes[0].to_py())
    return ", ".join(parts)


# --- slices ---
@method(slice_3)
def to_py(self, prec=None):
    """slice_3: expression ':' expression ':' expression"""
    return f"{self.nodes[0].to_py()}:{self.nodes[2].to_py()}:{self.nodes[4].to_py()}"


@method(slice_3ns)
def to_py(self, prec=None):
    """slice_3ns: expression ':' ':' expression  (no stop)"""
    return f"{self.nodes[0].to_py()}::{self.nodes[3].to_py()}"


@method(slice_3nn)
def to_py(self, prec=None):
    """slice_3nn: ':' expression ':' expression  (no start)"""
    return f":{self.nodes[1].to_py()}:{self.nodes[3].to_py()}"


@method(slice_3bare)
def to_py(self, prec=None):
    """slice_3bare: ':' ':' expression  (no start, no stop)"""
    return f"::{self.nodes[2].to_py()}"


@method(slice_2)
def to_py(self, prec=None):
    """slice_2: expression ':' expression"""
    return f"{self.nodes[0].to_py()}:{self.nodes[2].to_py()}"


@method(slice_1_start)
def to_py(self, prec=None):
    """slice_1_start: expression ':'"""
    return f"{self.nodes[0].to_py()}:"


@method(slice_1_stop)
def to_py(self, prec=None):
    """slice_1_stop: ':' expression"""
    return f":{self.nodes[1].to_py()}"


@method(slice_bare)
def to_py(self, prec=None):
    """slice_bare: ':'"""
    return ":"


@method(slice_full)
def to_py(self, prec=None):
    """slice_full: slice_3 | slice_3ns | slice_3nn | slice_3bare
    | slice_2 | slice_1_start | slice_1_stop | slice_bare"""
    return self.nodes[0].to_py()


@method(slice_expr)
def to_py(self, prec=None):
    """slice_expr: slice_full | named_expression"""
    return self.nodes[0].to_py()


@method(slices)
def to_py(self, prec=None):
    """slices: slice_expr (',' slice_expr)* ','?"""
    parts = [self.nodes[0].to_py()]
    for node in self.nodes[1:]:
        if not hasattr(node, "nodes") or not node.nodes:
            continue
        for seq in node.nodes:
            if hasattr(seq, "nodes") and len(seq.nodes) >= 1:
                parts.append(seq.nodes[0].to_py())
    return ", ".join(parts)


# --- arguments ---
@method(kwarg)
def to_py(self, prec=None):
    """kwarg: IDENTIFIER '=' expression"""
    return f"{self.nodes[0].to_py()}={self.nodes[1].to_py()}"


@method(star_arg)
def to_py(self, prec=None):
    """star_arg: '*' expression"""
    return f"*{self.nodes[1].to_py()}"


@method(dstar_arg)
def to_py(self, prec=None):
    """dstar_arg: '**' expression"""
    return f"**{self.nodes[0].to_py()}"


@method(arg)
def to_py(self, prec=None):
    """arg: kwarg | dstar_arg | star_arg | expression"""
    return self.nodes[0].to_py()


@method(arguments)
def to_py(self, prec=None):
    """arguments: arg (',' arg)* ','?"""
    parts = [self.nodes[0].to_py()]
    for node in self.nodes[1:]:
        if not hasattr(node, "nodes") or not node.nodes:
            continue
        for seq in node.nodes:
            if hasattr(seq, "nodes") and len(seq.nodes) >= 1:
                parts.append(seq.nodes[0].to_py())
    return ", ".join(parts)


# --- comprehensions ---
@method(target)
def to_py(self, prec=None):
    """target: IDENTIFIER (',' IDENTIFIER)*"""
    parts = [self.nodes[0].to_py()]
    if len(self.nodes) > 1 and hasattr(self.nodes[1], "nodes"):
        for seq in self.nodes[1].nodes:
            if hasattr(seq, "nodes") and len(seq.nodes) >= 1:
                parts.append(seq.nodes[0].to_py())
    return ", ".join(parts)


@method(for_if_clause)
def to_py(self, prec=None):
    """for_if_clause: 'for' target 'in' disjunction ('if' disjunction)*"""
    tgt = self.nodes[0].to_py()
    iterable = self.nodes[1].to_py()
    result = f"for {tgt} in {iterable}"
    # nodes[2] is Several_Times of Sequence_Parser(I_IF + disjunction).
    # I_IF is ignored so each Sequence_Parser has exactly one node: the disjunction.
    if len(self.nodes) > 2:
        st = self.nodes[2]
        if hasattr(st, "nodes"):
            for seq in st.nodes:
                if hasattr(seq, "nodes") and seq.nodes:
                    result += f" if {seq.nodes[0].to_py()}"
                elif hasattr(seq, "to_py"):
                    result += f" if {seq.to_py()}"
    return result


@method(for_if_clauses)
def to_py(self, prec=None):
    """for_if_clauses: for_if_clause+"""
    parts = []
    for n in self.nodes:
        if hasattr(n, "to_py"):
            parts.append(n.to_py())
        elif hasattr(n, "nodes"):
            for nn in n.nodes:
                if hasattr(nn, "to_py"):
                    parts.append(nn.to_py())
    return " ".join(parts)


@method(listcomp)
def to_py(self, prec=None):
    """listcomp: named_expression for_if_clauses"""
    return f"{self.nodes[0].to_py()} {self.nodes[1].to_py()}"


@method(genexpr)
def to_py(self, prec=None):
    """genexpr: named_expression for_if_clauses"""
    return f"{self.nodes[0].to_py()} {self.nodes[1].to_py()}"


@method(dictcomp)
def to_py(self, prec=None):
    """dictcomp: expression ':' expression for_if_clauses"""
    return f"{self.nodes[0].to_py()}: {self.nodes[1].to_py()} {self.nodes[2].to_py()}"


@method(setcomp)
def to_py(self, prec=None):
    """setcomp: expression for_if_clauses"""
    return f"{self.nodes[0].to_py()} {self.nodes[1].to_py()}"


# --- dict/set makers ---
@method(V_COLON)
def to_py(self, prec=None):
    """V_COLON: ':'  (visible colon token)"""
    return ":"


@method(kvpair)
def to_py(self, prec=None):
    """kvpair: expression ':' expression"""
    return f"{self.nodes[0].to_py()}: {self.nodes[2].to_py()}"


@method(dictmaker)
def to_py(self, prec=None):
    """dictmaker: kvpair (',' kvpair)* ','?"""
    first_pair = f"{self.nodes[0].to_py()}: {self.nodes[2].to_py()}"
    parts = [first_pair]
    for node in self.nodes[3:]:
        if not hasattr(node, "nodes") or not node.nodes:
            continue
        for seq in node.nodes:
            if hasattr(seq, "nodes") and len(seq.nodes) >= 1:
                # Each seq inside Several_Times is a kvpair
                parts.append(seq.nodes[0].to_py())
    return ", ".join(parts)


@method(setmaker)
def to_py(self, prec=None):
    """setmaker: star_expression (',' star_expression)* ','?"""
    parts = [self.nodes[0].to_py()]
    for node in self.nodes[1:]:
        if not hasattr(node, "nodes") or not node.nodes:
            continue
        for seq in node.nodes:
            if hasattr(seq, "nodes") and len(seq.nodes) >= 1:
                parts.append(seq.nodes[0].to_py())
    return ", ".join(parts)



###############################################################################
# Public API
###############################################################################


def parse_expr(code):
    """Parse a Python 3.14 expression and return the AST node."""
    ParserState.reset()
    stream = Input(code)
    result = expression.parse(stream)
    if not result:
        return None
    return result[0]


###############################################################################
# Tests
###############################################################################

if __name__ == "__main__":
    print("=" * 60)
    print("Python 3.14 Expression Parser Tests")
    print("=" * 60)

    tests = [
        # --- Literals ---
        ("42", "42"),
        ("3.14", "3.14"),
        ('"hello"', '"hello"'),
        ("'world'", "'world'"),
        ("None", "None"),
        ("True", "True"),
        ("False", "False"),
        ("...", "..."),
        # --- Arithmetic ---
        ("1 + 2", "1 + 2"),
        ("1 + 2 * 3", "1 + 2 * 3"),
        ("(1 + 2) * 3", "(1 + 2) * 3"),
        ("10 / 3", "10 / 3"),
        ("10 // 3", "10 // 3"),
        ("10 % 3", "10 % 3"),
        ("a @ b", "a @ b"),
        # --- Unary ---
        ("-x", "-x"),
        ("+x", "+x"),
        ("~x", "~x"),
        ("not x", "not x"),
        # --- Power (right-associative) ---
        ("x ** 2", "x ** 2"),
        # --- Comparison ---
        ("x < y", "x < y"),
        ("x == y", "x == y"),
        ("x != y", "x != y"),
        ("x <= y", "x <= y"),
        ("x >= y", "x >= y"),
        # --- Bitwise ---
        ("x | y", "x | y"),
        ("x ^ y", "x ^ y"),
        ("x & y", "x & y"),
        ("x << 2", "x << 2"),
        ("x >> 1", "x >> 1"),
        # --- Boolean ---
        ("x and y", "x and y"),
        ("x or y", "x or y"),
        ("x and y or z", "x and y or z"),
        ("not x and y", "not x and y"),
        # --- Conditional ---
        ("a if b else c", "a if b else c"),
        # --- Lambda ---
        ("lambda x: x + 1", "lambda x: x + 1"),
        ("lambda x, y: x + y", "lambda x, y: x + y"),
        # --- Calls, subscripts, attributes ---
        ("f(x)", "f(x)"),
        ("f(x, y)", "f(x, y)"),
        ("a[i]", "a[i]"),
        ("obj.attr", "obj.attr"),
        ("f(x).y", "f(x).y"),
        # --- Containers ---
        ("[1, 2, 3]", "[1, 2, 3]"),
        ("[]", "[]"),
        ("()", "()"),
        # --- String concat ---
        ('"a" "b"', '"a" "b"'),
        # --- Python 3 specifics ---
        ("{1, 2, 3}", "{1, 2, 3}"),
        ("{1: 2, 3: 4}", "{1: 2, 3: 4}"),
        ("f(x=1)", "f(x=1)"),
        ("f(*args)", "f(*args)"),
        ("f(**kwargs)", "f(**kwargs)"),
        ("f(a, *b, **c)", "f(a, *b, **c)"),
        # --- Comprehensions ---
        ("[x for x in xs]", "[x for x in xs]"),
        ("{x for x in xs}", "{x for x in xs}"),
        # --- Slicing ---
        ("a[1:2]", "a[1:2]"),
        # --- Await ---
        ("await f()", "await f()"),
    ]

    passed = failed = 0
    for code, expected in tests:
        try:
            result = parse_expr(code)
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

    # ==================================================================


@method(named_tuple_field)
def to_py(self, prec=None):
    """named_tuple_field: IDENTIFIER ':' expression (HPython named-tuple field literal) -> Python: just the value (positional)"""
    # In Python, named tuple fields become positional: just emit the value
    val = self.nodes[2].to_py()
    return val

@method(named_tuple_lit)
def to_py(self, prec=None):
    """named_tuple_lit: '(' named_tuple_field (',' named_tuple_field)* ')' -> Python: TypeName(field=val, ...) if type known, else (val, ...)"""
    # Collect field names and values
    def _extract_field(node):
        """Extract (name, value) from a named_tuple_field node."""
        name = str(node.nodes[0].nodes[0]) if hasattr(node.nodes[0], 'nodes') else str(node.nodes[0])
        val = node.nodes[2].to_py()
        return name, val
    first_name, first_val = _extract_field(self.nodes[1])
    field_names = [first_name]
    field_vals = [first_val]
    rest = self.nodes[2]  # Several_Times
    if hasattr(rest, 'nodes'):
        for seq in rest.nodes:
            if hasattr(seq, 'nodes'):
                for child in seq.nodes:
                    if type(child).__name__ == "named_tuple_field":
                        n, v = _extract_field(child)
                        field_names.append(n)
                        field_vals.append(v)
            elif type(seq).__name__ == "named_tuple_field":
                n, v = _extract_field(seq)
                field_names.append(n)
                field_vals.append(v)
    # Look up if these fields match a known NamedTuple type
    type_name = _lookup_named_tuple(field_names)
    if type_name:
        # Emit as NamedTuple constructor: TypeName(field=val, ...)
        args = ", ".join(f"{n}={v}" for n, v in zip(field_names, field_vals))
        return f"{type_name}({args})"
    # Fallback: plain tuple with just the values
    return "(" + ", ".join(field_vals) + ")"
