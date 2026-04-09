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
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import tokenize as tkn
import token as _tok_mod

from hek_parsec import (
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
    SSTAR,
    STRING,
    Input,
    Parser,
    ParserState,
    expect,
    expect_type,
    expect_node,
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


# --- Node-preserving brackets for multi-line source preservation ---
import token as tkn_mod
LPAREN_NODE = expect_node(tkn_mod.OP, "(")
LBRACKET_NODE = expect_node(tkn_mod.OP, "[")
LBRACE_NODE = expect_node(tkn_mod.OP, "{")
###############################################################################
# Precedence levels for minimal parenthesization
###############################################################################

PREC_WALRUS = 0
PREC_CONDITIONAL = 3
PREC_OR = 4
PREC_AND = 5
PREC_NOT = 6
PREC_CMP = 7
PREC_BOR = 8
PREC_BXOR = 9
PREC_BAND = 10
PREC_SHIFT = 11
PREC_ARITH = 12
PREC_TERM = 13
PREC_UNARY = 14
PREC_POWER = 15
PREC_ATOM = 99


# Visible operators (kept in AST for op extraction in to_py)
V_PLUS = vop("+")
V_MINUS = vop("-")
V_STAR = vop("*")
V_SLASH = vop("/")
V_PERCENT = vop("%")
V_DSLASH = vop("//")
V_DSTAR = vop("**")
V_TILDE = vop("~")
V_AT = vop("@")
V_PIPE = vop("|")
V_CARET = vop("^")
V_AMPER = vop("&")
V_LSHIFT = vop("<<")
V_RSHIFT = vop(">>")
V_LT = vop("<")
V_DOT = vop(".")
V_GT = vop(">")
V_EQ = vop("==")
V_NE = vop("!=")
V_LE = vop("<=")
V_GE = vop(">=")
V_COLONEQUAL = vop(":=")
V_COLON = vop(":")

# Visible keywords (used as operators where we need the string)
K_AND = literal("and")
K_OR = literal("or")
K_NOT = literal("not")
K_IN = literal("in")
K_IS = literal("is")

# Ignored keywords (structural, filtered from nodes)
I_IF = ikw("if")
I_ELSE = ikw("else")
I_LAMBDA = ikw("lambda")
I_AWAIT = ikw("await")
I_YIELD = ikw("yield")
I_FROM = ikw("from")
I_FOR = ikw("for")
I_ASYNC = ikw("async")

# Visible ellipsis (hek_parsec's ELLIPSIS is ignored; we need the value)
V_ELLIPSIS = expect(tkn.OP, "...")

# Keyword literals
K_NONE = literal("None")
K_TRUE = literal("True")
K_FALSE = literal("False")

###############################################################################
# Forward declarations
###############################################################################

expression = fw("expression")
expressions = fw("expressions")
named_expression = fw("named_expression")
walrus = fw("walrus")
disjunction = fw("disjunction")
conjunction = fw("conjunction")
inversion = fw("inversion")
file_test = fw("file_test")
comparison = fw("comparison")
bitor_expr = fw("bitor_expr")
range_expr = fw("range_expr")
bitxor_expr = fw("bitxor_expr")
bitand_expr = fw("bitand_expr")
shift_expr = fw("shift_expr")
sum_expr = fw("sum_expr")
term = fw("term")
factor = fw("factor")
power = fw("power")
await_primary = fw("await_primary")
primary = fw("primary")
trailer = fw("trailer")
atom = fw("atom")
lambda_expr = fw("lambda_expr")
yield_expr = fw("yield_expr")
star_expression = fw("star_expression")
star_expressions = fw("star_expressions")
slices = fw("slices")
slice_expr = fw("slice_expr")
arguments = fw("arguments")
arg = fw("arg")
dictmaker = fw("dictmaker")
setmaker = fw("setmaker")
listcomp = fw("listcomp")
dictcomp = fw("dictcomp")
setcomp = fw("setcomp")
genexpr = fw("genexpr")
for_if_clauses = fw("for_if_clauses")
for_if_clause = fw("for_if_clause")
fstring = fw("fstring")
###############################################################################
# Grammar rules (bottom-up, highest precedence first)
###############################################################################

# --- f-string: FSTRING_START FSTRING_MIDDLE? ('{' expression '}' FSTRING_MIDDLE?)* FSTRING_END ---
# Python 3.12+ tokenises f"hello {name}" as:
#   FSTRING_START f"  FSTRING_MIDDLE hello   OP {  NAME name  OP }  FSTRING_END "
# We collect the raw token strings and reassemble them verbatim.
_FSTRING_START  = fmap(lambda tok: tok.string, filt(lambda tok: tok.type == _tok_mod.FSTRING_START,  shift))
_FSTRING_MIDDLE = fmap(lambda tok: tok.string, filt(lambda tok: tok.type == _tok_mod.FSTRING_MIDDLE, shift))
_FSTRING_END    = fmap(lambda tok: tok.string, filt(lambda tok: tok.type == _tok_mod.FSTRING_END,    shift))
_FSTRING_LBRACE = fmap(lambda tok: tok.string, filt(lambda tok: tok.type == tkn.OP and tok.string == "{", shift))
_FSTRING_RBRACE = fmap(lambda tok: tok.string, filt(lambda tok: tok.type == tkn.OP and tok.string == "}", shift))
_FSTRING_BANG   = fmap(lambda tok: tok.string, filt(lambda tok: tok.type == tkn.OP and tok.string == "!", shift))
_FSTRING_CONV   = fmap(lambda tok: tok.string, filt(lambda tok: tok.type == tkn.NAME and tok.string in ("r", "s", "a"), shift))
_FSTRING_COLON  = fmap(lambda tok: tok.string, filt(lambda tok: tok.type == tkn.OP and tok.string == ":", shift))
# Optional conversion: !r / !s / !a
_fstring_conversion = _FSTRING_BANG + _FSTRING_CONV
# Optional format spec: : FSTRING_MIDDLE (the spec itself is a FSTRING_MIDDLE token)
_fstring_format_spec = _FSTRING_COLON + _FSTRING_MIDDLE[:]
# One interpolation: { expression [!r] [: spec] }
_fstring_interp = _FSTRING_LBRACE + expression + _fstring_conversion[:] + _fstring_format_spec[:] + _FSTRING_RBRACE
# Interp + middle chunk (middle is optional after each interpolation)
_fstring_chunk  = _fstring_interp + _FSTRING_MIDDLE[:]
fstring = _FSTRING_START + _FSTRING_MIDDLE[:] + _fstring_chunk[:] + _FSTRING_END

# --- atom ---
ellipsis_lit = V_ELLIPSIS
# Named tuple literal: (name:value, name:value, ...) — Nim-style
named_tuple_field = IDENTIFIER + V_COLON + expression
named_tuple_lit = LPAREN_NODE + named_tuple_field + (COMMA + named_tuple_field)[1:] + COMMA[:] + RPAREN
paren_group = LPAREN_NODE + (yield_expr | walrus | expressions) + RPAREN
empty_paren = LPAREN + RPAREN
list_display = LBRACKET_NODE + (listcomp | star_expressions) + RBRACKET
enum_array_display = LBRACKET_NODE + dictmaker + RBRACKET
empty_list = LBRACKET + RBRACKET
dict_display = LBRACE_NODE + (dictcomp | dictmaker) + RBRACE
set_display = LBRACE_NODE + (setcomp | setmaker) + RBRACE
empty_set  = LBRACE + RBRACE           # {}   -> empty set
empty_dict = LBRACE + COLON + RBRACE  # {:}  -> empty dict
str_concat = STRING + STRING[1:]

atom = (
    empty_paren
    | named_tuple_lit
    | paren_group
    | empty_list
    | enum_array_display
    | list_display
    | empty_set
    | empty_dict
    | dict_display
    | set_display
    | ellipsis_lit
    | K_NONE
    | K_TRUE
    | K_FALSE
    | IDENTIFIER
    | NUMBER
    | fstring
    | str_concat
    | STRING
)

# --- trailer ---
call_trailer = LPAREN_NODE + arguments[:] + RPAREN
slice_trailer = LBRACKET + slices + RBRACKET
attr_trailer = DOT + IDENTIFIER

trailer = call_trailer | slice_trailer | attr_trailer

# --- primary: atom followed by zero or more trailers ---
primary = atom + trailer[:]

# --- await_primary ---
await_expr = I_AWAIT + primary
await_primary = await_expr | primary

# --- power: await_primary ['**' factor] (right-associative) ---
power_rhs = V_DSTAR + factor
power = await_primary + power_rhs[:]

# --- factor: unary +/-/~ or power ---
unary_plus = iop("+") + factor
unary_minus = iop("-") + factor
unary_tilde = iop("~") + factor
factor = unary_plus | unary_minus | unary_tilde | power

# --- term through bitor: left-associative binary ops ---
term = factor + ((V_STAR | V_SLASH | V_DSLASH | V_PERCENT | V_AT) + factor)[:]
sum_expr = term + ((V_PLUS | V_MINUS) + term)[:]
shift_expr = sum_expr + ((V_LSHIFT | V_RSHIFT) + sum_expr)[:]
bitand_expr = shift_expr + (V_AMPER + shift_expr)[:]
bitxor_expr = bitand_expr + (V_CARET + bitand_expr)[:]
bitor_expr = bitxor_expr + (V_PIPE + bitxor_expr)[:]

# --- range expression: expr '..' expr  or  expr '..<' expr ---
range_excl_op = V_DOT + V_DOT + V_LT   # ..<
range_incl_op = V_DOT + V_DOT           # ..
range_expr = bitor_expr + ((range_excl_op | range_incl_op) + bitor_expr)[:]

# --- bash file-test unary operators: -e FILE, -f FILE, etc. ---
# The tokenizer rewrites '-e FILE' -> '__bash_test_e__ FILE' so the parser
# sees a plain IDENTIFIER followed by a primary expression.
# IDENTIFIER returns a plain string, so filt tests the string directly.
_bash_test_op = filt(
    lambda name: name.startswith("__bash_test_") and name.endswith("__"),
    IDENTIFIER
)
file_test = _bash_test_op + primary

# --- comparison operators ---
not_in_op = K_NOT + K_IN
is_not_op = K_IS + K_NOT
# Bash file-comparison operators: FILE1 -nt FILE2 / FILE1 -ot FILE2
# The tokenizer rewrites '-nt' -> '__bash_nt__' and '-ot' -> '__bash_ot__'.
bash_nt_op = filt(lambda name: name == "__bash_nt__", IDENTIFIER)
bash_ot_op = filt(lambda name: name == "__bash_ot__", IDENTIFIER)
comp_op = V_EQ | V_NE | V_LE | V_LT | V_GE | V_GT | not_in_op | is_not_op | K_IN | K_IS | bash_nt_op | bash_ot_op

# --- 'in' with range: x in 1 .. n  or  x in 1 ..< n ---
# Must be tried before plain comp_op so 'in' eagerly grabs the range bounds.
in_range_excl = fw("in_range_excl")
in_range_incl = fw("in_range_incl")
in_range_excl = K_IN + bitor_expr + range_excl_op + bitor_expr   # in lo ..< hi
in_range_incl = K_IN + bitor_expr + range_incl_op + bitor_expr   # in lo .. hi

# --- comparison ---
comparison = range_expr + (in_range_excl | in_range_incl | comp_op + range_expr)[:]

# --- inversion: 'not' inversion | file_test | comparison ---
not_prefix = ikw("not") + inversion
inversion = not_prefix | file_test | comparison

# --- conjunction / disjunction ---
conjunction = inversion + (K_AND + inversion)[:]
disjunction = conjunction + (K_OR + conjunction)[:]

# --- named_expression: NAME ':=' expression | expression ---
walrus = IDENTIFIER + V_COLONEQUAL + expression
named_expression = walrus | expression

# --- lambda ---
# lambda_param: IDENTIFIER ['=' expression]
lambda_param = IDENTIFIER + (iop("=") + expression)[:]
# lambda_star: '*' IDENTIFIER  — *args
lambda_star = SSTAR + IDENTIFIER
# lambda_dstar: '**' IDENTIFIER  — **kwargs
lambda_dstar = iop("**") + IDENTIFIER
lambda_params_entry = lambda_dstar | lambda_star | lambda_param
lambda_params = lambda_params_entry + (COMMA + lambda_params_entry)[:]
lambda_expr = I_LAMBDA + lambda_params[:] + COLON + expression

# --- expression: conditional | lambda | disjunction ---
conditional = disjunction + I_IF + disjunction + I_ELSE + expression
expression = conditional | lambda_expr | disjunction


# --- expressions: expression (',' expression)* [','] ---
expressions = expression + (COMMA + expression)[:] + COMMA[:]

# --- yield ---
yield_from = I_YIELD + I_FROM + expression
yield_val = I_YIELD + star_expressions[:]
yield_expr = yield_from | yield_val

# --- star expressions ---
star_single = SSTAR + bitor_expr
star_expression = star_single | expression
star_expressions = star_expression + (COMMA + star_expression)[:] + COMMA[:]

# --- slices ---
# slice: [expr] ':' [expr] [':' [expr]] | named_expression
# Use V_COLON (visible) so colon nodes aren't lost to filtering
slice_3 = expression + V_COLON + expression + V_COLON + expression  # a:b:c
slice_3ns = expression + V_COLON + V_COLON + expression  # a::c
slice_3nn = V_COLON + expression + V_COLON + expression  # :b:c
slice_3bare = V_COLON + V_COLON + expression  # ::c
slice_2 = expression + V_COLON + expression  # a:b
slice_1_start = expression + V_COLON  # a:
slice_1_stop = V_COLON + expression  # :b
slice_bare = V_COLON  # :
slice_full = (
    slice_3
    | slice_3ns
    | slice_3nn
    | slice_3bare
    | slice_2
    | slice_1_start
    | slice_1_stop
    | slice_bare
)
slice_expr = slice_full | named_expression
slices = slice_expr + (COMMA + slice_expr)[:] + COMMA[:]

# --- arguments (simplified) ---
kwarg = IDENTIFIER + iop("=") + expression
star_arg = SSTAR + expression
dstar_arg = iop("**") + expression
# genexpr_arg: a lone genexpr as sole argument e.g. sum(x for x in xs).
# Must come before 'expression' since genexpr starts with an expression.
genexpr_arg = genexpr
arg = kwarg | dstar_arg | star_arg | genexpr_arg | expression
arguments = arg + (COMMA + arg)[:] + COMMA[:]

# --- comprehension targets (restricted: no 'in'/'not in' comparisons) ---
# target is just identifiers and tuples of identifiers, not full expressions
target = IDENTIFIER + (COMMA + IDENTIFIER)[:]

# --- comprehensions ---
for_simple = I_FOR + target + ikw("in") + disjunction
for_if_clause = for_simple + (I_IF + disjunction)[:]
for_if_clauses = for_if_clause[1:]

listcomp = named_expression + for_if_clauses
genexpr = named_expression + for_if_clauses
dictcomp = expression + COLON + expression + for_if_clauses
setcomp = expression + for_if_clauses

# --- dict/set makers ---
kvpair = expression + V_COLON + expression
dictmaker = kvpair + (COMMA + kvpair)[:] + COMMA[:]
setmaker = star_expression + (COMMA + star_expression)[:] + COMMA[:]


def parse_expr(code):
    """Parse a Python 3.14 expression and return the AST node."""
    ParserState.reset()
    stream = Input(code)
    result = expression.parse(stream)
    if not result:
        return None
    return result[0]


