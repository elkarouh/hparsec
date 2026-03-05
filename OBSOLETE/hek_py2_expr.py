#!/usr/bin/env python3
"""Python 2.7 Expression Parser using hek_parser combinator framework.

Implements the full Python 2.7 expression grammar with correct operator
precedence. Each precedence level is a separate parser rule.

Precedence (low to high):
    lambda, if/else, or, and, not, comparisons, |, ^, &, <</>>,
    +/-, */%//, unary +/-/~, **, atom+trailers

Python 2 specific features:
    - <> operator (alternative to !=)
    - backtick repr: `expr`
    - Long literals: 123L (handled by Python tokenizer as NAME suffix)

Usage:
    ast, rest = test.parse(Input("1 + 2 * 3"))
    print(ast.to_py())  # (1 + (2 * 3))
"""

import tokenize as tkn

from hek_parser import (
    COLON,
    COMMA,
    DOT,
    IDENTIFIER,
    LBRACE,
    LBRACKET,
    LPAREN,
    NUMBER,
    RBRACE,
    RBRACKET,
    RPAREN,
    STRING,
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

###############################################################################
# Operator helpers
###############################################################################


def vop(symbol):
    """Visible operator: matches and keeps the string in the AST."""
    return expect(tkn.OP, symbol)


def iop(symbol):
    """Ignored operator: matches but filtered from AST nodes."""
    return ignore(expect(tkn.OP, symbol))


def ikw(word):
    """Ignored keyword: matches but filtered from AST nodes."""
    return ignore(literal(word))


# Visible operators (kept in AST for op extraction in to_py)
V_PLUS = vop("+")
V_MINUS = vop("-")
V_STAR = vop("*")
V_SLASH = vop("/")
V_PERCENT = vop("%")
V_DSLASH = vop("//")
V_DSTAR = vop("**")
V_TILDE = vop("~")
V_PIPE = vop("|")
V_CARET = vop("^")
V_AMPER = vop("&")
V_LSHIFT = vop("<<")
V_RSHIFT = vop(">>")
V_LT = vop("<")
V_GT = vop(">")
V_EQ = vop("==")
V_NE = vop("!=")
V_LE = vop("<=")
V_GE = vop(">=")
V_LTGT = vop("<>")

# Visible keywords (used as operators where we need the string)
K_AND = literal("and")
K_OR = literal("or")
K_NOT = literal("not")
K_IN = literal("in")
K_IS = literal("is")

# Ignored keywords (structural, not needed in AST)
I_IF = ikw("if")
I_ELSE = ikw("else")
I_LAMBDA = ikw("lambda")

# Keyword literals
K_NONE = literal("None")
K_TRUE = literal("True")
K_FALSE = literal("False")

# Backtick (Python tokenizer emits ERRORTOKEN for backtick)
BACKTICK = ignore(expect(tkn.ERRORTOKEN, "`"))

###############################################################################
# Forward declarations
###############################################################################

test = fw("test")
testlist = fw("testlist")
or_test = fw("or_test")
and_test = fw("and_test")
not_test = fw("not_test")
comparison = fw("comparison")
bitor_expr = fw("bitor_expr")
bitxor_expr = fw("bitxor_expr")
bitand_expr = fw("bitand_expr")
shift_expr = fw("shift_expr")
arith_expr = fw("arith_expr")
term = fw("term")
factor = fw("factor")
power = fw("power")
atom_expr = fw("atom_expr")
trailer = fw("trailer")
atom = fw("atom")
lambda_expr = fw("lambda_expr")
dictmaker = fw("dictmaker")
arglist = fw("arglist")

###############################################################################
# Grammar rules (bottom-up, highest precedence first)
###############################################################################

# --- atom ---
paren_expr = LPAREN + testlist + RPAREN
empty_paren = LPAREN + RPAREN
list_expr = LBRACKET + testlist + RBRACKET
empty_list = LBRACKET + RBRACKET
dict_expr = LBRACE + dictmaker + RBRACE
empty_dict = LBRACE + RBRACE
repr_expr = BACKTICK + test + BACKTICK
str_concat = STRING + STRING[1:]

atom = (
    empty_paren
    | paren_expr
    | empty_list
    | list_expr
    | empty_dict
    | dict_expr
    | repr_expr
    | K_NONE
    | K_TRUE
    | K_FALSE
    | IDENTIFIER
    | NUMBER
    | str_concat
    | STRING
)

# --- trailer ---
call_trailer = LPAREN + arglist[:] + RPAREN
index_trailer = LBRACKET + test + RBRACKET
attr_trailer = DOT + IDENTIFIER

trailer = call_trailer | index_trailer | attr_trailer

# --- atom_expr: atom followed by zero or more trailers ---
atom_expr = atom + trailer[:]

# --- power: atom_expr ['**' factor] (right-associative) ---
power_rhs = V_DSTAR + factor
power = atom_expr + power_rhs[:]

# --- factor: unary +/-/~ or power ---
unary_plus = iop("+") + factor
unary_minus = iop("-") + factor
unary_tilde = iop("~") + factor
factor = unary_plus | unary_minus | unary_tilde | power

# --- term through bitor: left-associative binary ops ---
term = factor + ((V_STAR | V_SLASH | V_PERCENT | V_DSLASH) + factor)[:]
arith_expr = term + ((V_PLUS | V_MINUS) + term)[:]
shift_expr = arith_expr + ((V_LSHIFT | V_RSHIFT) + arith_expr)[:]
bitand_expr = shift_expr + (V_AMPER + shift_expr)[:]
bitxor_expr = bitand_expr + (V_CARET + bitand_expr)[:]
bitor_expr = bitxor_expr + (V_PIPE + bitxor_expr)[:]

# --- comparison operators ---
not_in_op = K_NOT + K_IN
is_not_op = K_IS + K_NOT
comp_op = (
    V_LT
    | V_GT
    | V_EQ
    | V_NE
    | V_LE
    | V_GE
    | V_LTGT
    | not_in_op
    | is_not_op
    | K_IN
    | K_IS
)

# --- comparison: bitor (comp_op bitor)* ---
comparison = bitor_expr + (comp_op + bitor_expr)[:]

# --- not_test: 'not' not_test | comparison ---
not_prefix = ikw("not") + not_test
not_test = not_prefix | comparison

# --- and_test / or_test ---
and_test = not_test + (K_AND + not_test)[:]
or_test = and_test + (K_OR + and_test)[:]

# --- lambda: 'lambda' [params] ':' test ---
lambda_params = IDENTIFIER + (COMMA + IDENTIFIER)[:]
lambda_expr = I_LAMBDA + lambda_params[:] + COLON + test

# --- test: or_test 'if' or_test 'else' test | lambda | or_test ---
conditional = or_test + I_IF + or_test + I_ELSE + test
test = conditional | lambda_expr | or_test

# --- testlist: test (',' test)* [','] ---
testlist = test + (COMMA + test)[:] + COMMA[:]

# --- dictmaker: test ':' test (',' test ':' test)* [','] ---
dict_pair = test + COLON + test
dictmaker = dict_pair + (COMMA + dict_pair)[:] + COMMA[:]

# --- arglist: test (',' test)* [','] ---
arglist = test + (COMMA + test)[:] + COMMA[:]

###############################################################################
# to_py() methods
###############################################################################


# --- leaf tokens ---
@method(NUMBER)
def to_py(self):
    return self.node


@method(STRING)
def to_py(self):
    return self.node


@method(IDENTIFIER)
def to_py(self):
    return self.node


@method(K_NONE)
def to_py(self):
    return "None"


@method(K_TRUE)
def to_py(self):
    return "True"


@method(K_FALSE)
def to_py(self):
    return "False"


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
    V_LTGT,
    K_AND,
    K_OR,
    K_NOT,
    K_IN,
    K_IS,
]:

    @method(_p)
    def to_py(self):
        return self.node


# --- str_concat ---
@method(str_concat)
def to_py(self):
    parts = [self.nodes[0].to_py()]
    rep = self.nodes[1]
    if hasattr(rep, "nodes"):
        parts.extend(n.to_py() for n in rep.nodes)
    else:
        parts.append(rep.to_py())
    return " ".join(parts)


# --- atom containers ---
@method(empty_paren)
def to_py(self):
    return "()"


@method(paren_expr)
def to_py(self):
    return self.nodes[0].to_py()


@method(empty_list)
def to_py(self):
    return "[]"


@method(list_expr)
def to_py(self):
    return "[" + self.nodes[0].to_py() + "]"


@method(empty_dict)
def to_py(self):
    return "{}"


@method(dict_expr)
def to_py(self):
    return "{" + self.nodes[0].to_py() + "}"


@method(repr_expr)
def to_py(self):
    return "`" + self.nodes[0].to_py() + "`"


@method(atom)
def to_py(self):
    return self.nodes[0].to_py()


# --- trailers ---
@method(call_trailer)
def to_py(self):
    # nodes[0] is Several_Times of arglist (0 or 1 match)
    if self.nodes and hasattr(self.nodes[0], "nodes") and self.nodes[0].nodes:
        return "(" + self.nodes[0].nodes[0].to_py() + ")"
    elif self.nodes and hasattr(self.nodes[0], "to_py"):
        return "(" + self.nodes[0].to_py() + ")"
    return "()"


@method(index_trailer)
def to_py(self):
    return "[" + self.nodes[0].to_py() + "]"


@method(attr_trailer)
def to_py(self):
    return "." + self.nodes[0].to_py()


@method(trailer)
def to_py(self):
    return self.nodes[0].to_py()


# --- atom_expr: atom + trailer[:] ---
# nodes[0] = atom, optional nodes[1] = Several_Times of trailers
@method(atom_expr)
def to_py(self):
    result = self.nodes[0].to_py()
    if len(self.nodes) > 1 and hasattr(self.nodes[1], "nodes") and self.nodes[1].nodes:
        for tr in self.nodes[1].nodes:
            result += tr.to_py()
    return result


@method(power_rhs)
def to_py(self):
    return f"** {self.nodes[1].to_py()}"


# --- power ---
# Due to Sequence flattening, nodes may vary depending on whether
# atom_expr had trailers and whether ** was present.
# We scan nodes[1:] and distinguish by child type name.
@method(power)
def to_py(self):
    result = self.nodes[0].to_py()
    for node in self.nodes[1:]:
        if not hasattr(node, "nodes") or not node.nodes:
            continue
        first = node.nodes[0]
        fname = type(first).__name__
        if fname == "power_rhs":
            # power_rhs.nodes = [V_DSTAR_str, factor]
            exponents = [seq.nodes[1].to_py() for seq in node.nodes]
            for exp in reversed(exponents):
                result = f"({result} ** {exp})"
        elif fname in ("call_trailer", "index_trailer", "attr_trailer", "trailer"):
            for tr in node.nodes:
                result += tr.to_py()
    return result


# --- factor (unary): iop removed, so nodes = [operand] ---
@method(unary_plus)
def to_py(self):
    return f"(+{self.nodes[0].to_py()})"


@method(unary_minus)
def to_py(self):
    return f"(-{self.nodes[0].to_py()})"


@method(unary_tilde)
def to_py(self):
    return f"(~{self.nodes[0].to_py()})"


@method(factor)
def to_py(self):
    return self.nodes[0].to_py()


# --- left-associative binary ops: nodes[0] = base, nodes[1] = Several_Times of (op, operand) ---
def binop_to_py(self):
    """Generic to_py for left-associative binary operators.

    Due to Sequence flattening, nodes layout may vary. We take nodes[0]
    as the base and scan remaining nodes for Several_Times containing
    (op, operand) pairs.
    """
    result = self.nodes[0].to_py()
    for node in self.nodes[1:]:
        if not hasattr(node, "nodes") or not node.nodes:
            continue
        for seq in node.nodes:
            if hasattr(seq, "nodes") and len(seq.nodes) >= 2:
                op = seq.nodes[0].to_py()
                right = seq.nodes[1].to_py()
                result = f"({result} {op} {right})"
    return result


@method(term)
def to_py(self):
    return binop_to_py(self)


@method(arith_expr)
def to_py(self):
    return binop_to_py(self)


@method(shift_expr)
def to_py(self):
    return binop_to_py(self)


@method(bitand_expr)
def to_py(self):
    return binop_to_py(self)


@method(bitxor_expr)
def to_py(self):
    return binop_to_py(self)


@method(bitor_expr)
def to_py(self):
    return binop_to_py(self)


# --- comparison ---
@method(not_in_op)
def to_py(self):
    return "not in"


@method(is_not_op)
def to_py(self):
    return "is not"


@method(comp_op)
def to_py(self):
    return self.nodes[0].to_py()


@method(comparison)
def to_py(self):
    return binop_to_py(self)


# --- not_test: ikw('not') removed, so not_prefix.nodes = [operand] ---
@method(not_prefix)
def to_py(self):
    return f"(not {self.nodes[0].to_py()})"


@method(not_test)
def to_py(self):
    return self.nodes[0].to_py()


# --- and_test / or_test ---
@method(and_test)
def to_py(self):
    return binop_to_py(self)


@method(or_test)
def to_py(self):
    return binop_to_py(self)


# --- conditional: or_test (I_IF removed) or_test (I_ELSE removed) test ---
# nodes = [value, condition, orelse]
@method(conditional)
def to_py(self):
    return f"({self.nodes[0].to_py()} if {self.nodes[1].to_py()} else {self.nodes[2].to_py()})"


# --- lambda: I_LAMBDA removed, params[:] + COLON(ignored) + test ---
@method(lambda_params)
def to_py(self):
    parts = [self.nodes[0].to_py()]
    if len(self.nodes) > 1 and hasattr(self.nodes[1], "nodes"):
        for seq in self.nodes[1].nodes:
            parts.append(seq.nodes[0].to_py())
    return ", ".join(parts)


@method(lambda_expr)
def to_py(self):
    # nodes[0] = Several_Times of lambda_params (0 or 1 match)
    # nodes[1] = body (test)
    # But if params matched, nodes[0] is Several_Times; if not, nodes[0] is the body
    if len(self.nodes) >= 2:
        params_st = self.nodes[0]
        if hasattr(params_st, "nodes") and params_st.nodes:
            params = params_st.nodes[0].to_py()
        else:
            params = ""
        body = self.nodes[1].to_py()
        return f"(lambda {params}: {body})"
    else:
        body = self.nodes[0].to_py()
        return f"(lambda: {body})"


@method(test)
def to_py(self):
    return self.nodes[0].to_py()


# --- testlist ---
@method(testlist)
def to_py(self):
    parts = [self.nodes[0].to_py()]
    if len(self.nodes) > 1 and hasattr(self.nodes[1], "nodes") and self.nodes[1].nodes:
        for seq in self.nodes[1].nodes:
            parts.append(seq.nodes[0].to_py())
    if len(parts) == 1:
        if len(self.nodes) > 2 and self.nodes[2] is not None:
            return f"({parts[0]},)"
        return parts[0]
    return ", ".join(parts)


# --- dictmaker ---
@method(dict_pair)
def to_py(self):
    return f"{self.nodes[0].to_py()}: {self.nodes[1].to_py()}"


@method(dictmaker)
def to_py(self):
    parts = [self.nodes[0].to_py()]
    if len(self.nodes) > 1 and hasattr(self.nodes[1], "nodes") and self.nodes[1].nodes:
        for seq in self.nodes[1].nodes:
            parts.append(seq.nodes[0].to_py())
    return ", ".join(parts)


# --- arglist ---
@method(arglist)
def to_py(self):
    parts = [self.nodes[0].to_py()]
    if len(self.nodes) > 1 and hasattr(self.nodes[1], "nodes") and self.nodes[1].nodes:
        for seq in self.nodes[1].nodes:
            parts.append(seq.nodes[0].to_py())
    return ", ".join(parts)


###############################################################################
# Public API
###############################################################################


def parse_expr(code):
    """Parse a Python 2 expression and return the AST node."""
    ParserState.reset()
    stream = Input(code)
    result = test.parse(stream)
    if not result:
        return None
    return result[0]


###############################################################################
# Tests
###############################################################################

if __name__ == "__main__":
    print("=" * 60)
    print("Python 2.7 Expression Parser Tests")
    print("=" * 60)

    tests = [
        # Literals
        ("42", "42"),
        ("3.14", "3.14"),
        ('"hello"', '"hello"'),
        ("'world'", "'world'"),
        ("None", "None"),
        ("True", "True"),
        ("False", "False"),
        # Arithmetic
        ("1 + 2", "(1 + 2)"),
        ("1 + 2 * 3", "(1 + (2 * 3))"),
        ("(1 + 2) * 3", "((1 + 2) * 3)"),
        ("10 / 3", "(10 / 3)"),
        ("10 // 3", "(10 // 3)"),
        ("10 % 3", "(10 % 3)"),
        # Unary
        ("-x", "(-x)"),
        ("+x", "(+x)"),
        ("~x", "(~x)"),
        ("not x", "(not x)"),
        # Power (right-associative)
        ("x ** 2", "(x ** 2)"),
        # Comparison
        ("x < y", "(x < y)"),
        ("x == y", "(x == y)"),
        ("x != y", "(x != y)"),
        ("x <= y", "(x <= y)"),
        ("x >= y", "(x >= y)"),
        # Bitwise
        ("x | y", "(x | y)"),
        ("x ^ y", "(x ^ y)"),
        ("x & y", "(x & y)"),
        ("x << 2", "(x << 2)"),
        ("x >> 1", "(x >> 1)"),
        # Boolean
        ("x and y", "(x and y)"),
        ("x or y", "(x or y)"),
        ("x and y or z", "((x and y) or z)"),
        ("not x and y", "((not x) and y)"),
        # Conditional
        ("a if b else c", "(a if b else c)"),
        # Lambda
        ("lambda x: x + 1", "(lambda x: (x + 1))"),
        ("lambda x, y: x + y", "(lambda x, y: (x + y))"),
        # Calls, subscripts, attributes
        ("f(x)", "f(x)"),
        ("f(x, y)", "f(x, y)"),
        ("a[i]", "a[i]"),
        ("obj.attr", "obj.attr"),
        ("f(x).y", "f(x).y"),
        # Containers
        ("[1, 2, 3]", "[1, 2, 3]"),
        ("[]", "[]"),
        ("()", "()"),
        # String concat
        ('"a" "b"', '"a" "b"'),
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
