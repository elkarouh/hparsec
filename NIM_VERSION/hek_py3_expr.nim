#!/usr/bin/env nim
## Python 3.14 Expression Parser in Nim using hek_parser combinator framework.

import hek_parsec, tables, strutils, options

# ==============================================================================
# Helper functions
# ==============================================================================

proc vop*(symbol: string): Parser =
  expect(ttOp, symbol)

proc iop*(symbol: string): Parser =
  ignore(expect(ttOp, symbol))

proc ikw*(word: string): Parser =
  ignore(literal(word))

# Visible operators
let
  V_PLUS* = vop("+")
  V_MINUS* = vop("-")
  V_STAR* = vop("*")
  V_SLASH* = vop("/")
  V_PERCENT* = vop("%")
  V_DSLASH* = vop("//")
  V_DSTAR* = vop("**")
  V_TILDE* = vop("~")
  V_AT* = vop("@")
  V_PIPE* = vop("|")
  V_CARET* = vop("^")
  V_AMPER* = vop("&")
  V_LSHIFT* = vop("<<")
  V_RSHIFT* = vop(">>")
  V_LT* = vop("<")
  V_GT* = vop(">")
  V_EQ* = vop("==")
  V_NE* = vop("!=")
  V_LE* = vop("<=")
  V_GE* = vop(">=")
  V_colonEQUAL* = vop(":=")
  V_colon* = vop(":")

# Visible keywords
let
  K_AND* = literal("and")
  K_OR* = literal("or")
  K_NOT* = literal("not")
  K_IN* = literal("in")
  K_IS* = literal("is")

# Ignored keywords
let
  I_IF* = ikw("if")
  I_ELSE* = ikw("else")
  I_LAMBDA* = ikw("lambda")
  I_AWAIT* = ikw("await")
  I_YIELD* = ikw("yield")
  I_FROM* = ikw("from")
  I_FOR* = ikw("for")
  I_ASYNC* = ikw("async")

# Visible ellipsis
let V_ELLIPSIS* = vop("...")

# Keyword literals
let
  K_NONE* = literal("None")
  K_TRUE* = literal("True")
  K_FALSE* = literal("False")

# ==============================================================================
# Forward declarations
# ==============================================================================

var
  expression* = forward("expression")
  expressions* = forward("expressions")
  named_expression* = forward("named_expression")
  disjunction* = forward("disjunction")
  conjunction* = forward("conjunction")
  inversion* = forward("inversion")
  comparison* = forward("comparison")
  bitor_expr* = forward("bitor_expr")
  bitxor_expr* = forward("bitxor_expr")
  bitand_expr* = forward("bitand_expr")
  shift_expr* = forward("shift_expr")
  sum_expr* = forward("sum_expr")
  term* = forward("term")
  factor* = forward("factor")
  power* = forward("power")
  await_primary* = forward("await_primary")
  primary* = forward("primary")
  trailer* = forward("trailer")
  atom* = forward("atom")
  lambda_expr* = forward("lambda_expr")
  yield_expr* = forward("yield_expr")
  star_expression* = forward("star_expression")
  star_expressions* = forward("star_expressions")
  slices* = forward("slices")
  slice_expr* = forward("slice_expr")
  arguments* = forward("arguments")
  arg* = forward("arg")
  dictmaker* = forward("dictmaker")
  setmaker* = forward("setmaker")
  listcomp* = forward("listcomp")
  dictcomp* = forward("dictcomp")
  setcomp* = forward("setcomp")
  genexpr* = forward("genexpr")
  for_if_clauses* = forward("for_if_clauses")
  for_if_clause* = forward("for_if_clause")

# ==============================================================================
# Grammar rules
# ==============================================================================

# --- atom ---
let
  ellipsis_lit = V_ELLIPSIS
  paren_group = lparen + (yield_expr | expressions | named_expression) + rparen
  empty_paren = lparen + rparen
  list_display = lbracket + (listcomp | star_expressions) + rbracket
  empty_list = lbracket + rbracket
  dict_display = lbrace + (dictcomp | dictmaker) + rbrace
  set_display = lbrace + (setcomp | setmaker) + rbrace
  empty_dict = lbrace + rbrace
  str_concat = stringLit + stringLit.repOneOrMore

atom <- (
  empty_paren | paren_group | empty_list | list_display | empty_dict | dict_display |
  set_display | ellipsis_lit | K_NONE | K_TRUE | K_FALSE | ident | number | str_concat |
  stringLit
)

# --- trailer ---
let
  call_trailer = lparen + arguments.repZeroOrMore + rparen
  slice_trailer = lbracket + slices + rbracket
  attr_trailer = dot + ident

trailer <- call_trailer | slice_trailer | attr_trailer

# --- primary ---
primary <- atom + trailer.repZeroOrMore

# --- await_primary ---
let await_expr = I_AWAIT + primary
await_primary <- await_expr | primary

# --- power ---
let power_rhs = V_DSTAR + factor
power <- await_primary + power_rhs.repZeroOrMore

# --- factor ---
let
  unary_plus = iop("+") + factor
  unary_minus = iop("-") + factor
  unary_tilde = iop("~") + factor

factor <- unary_plus | unary_minus | unary_tilde | power

# --- term through bitor ---
let
  term_ops = (V_STAR | V_SLASH | V_DSLASH | V_PERCENT | V_AT) + factor
  sum_ops = (V_PLUS | V_MINUS) + term
  shift_ops = (V_LSHIFT | V_RSHIFT) + sum_expr
  bitand_ops = V_AMPER + shift_expr
  bitxor_ops = V_CARET + bitand_expr
  bitor_ops = V_PIPE + bitxor_expr

term <- factor + term_ops.repZeroOrMore
sum_expr <- term + sum_ops.repZeroOrMore
shift_expr <- sum_expr + shift_ops.repZeroOrMore
bitand_expr <- shift_expr + bitand_ops.repZeroOrMore
bitxor_expr <- bitand_expr + bitxor_ops.repZeroOrMore
bitor_expr <- bitxor_expr + bitor_ops.repZeroOrMore

# --- comparison ---
let
  not_in_op = K_NOT + K_IN
  is_not_op = K_IS + K_NOT
  comp_op =
    V_EQ | V_NE | V_LE | V_LT | V_GE | V_GT | not_in_op | is_not_op | K_IN | K_IS

comparison <- bitor_expr + (comp_op + bitor_expr).repZeroOrMore

# --- inversion ---
let not_prefix = ikw("not") + inversion
inversion <- not_prefix | comparison

# --- conjunction / disjunction ---
conjunction <- inversion + (K_AND + inversion).repZeroOrMore
disjunction <- conjunction + (K_OR + conjunction).repZeroOrMore

# --- named_expression ---
let walrus = ident + V_colonEQUAL + expression
named_expression <- walrus | expression

# --- lambda ---
let
  lambda_params = ident + (comma + ident).repZeroOrMore
  lambda_body = colon + expression

lambda_expr <- I_LAMBDA + lambda_params.repZeroOrMore + lambda_body

# --- expression ---
let conditional = disjunction + I_IF + disjunction + I_ELSE + expression
expression <- conditional | lambda_expr | disjunction

# --- expressions ---
expressions <- expression + (comma + expression).repZeroOrMore + comma.repZeroOrMore

# --- yield ---
let
  yield_from = I_YIELD + I_FROM + expression
  yield_val = I_YIELD + star_expressions.repZeroOrMore

yield_expr <- yield_from | yield_val

# --- star expressions ---
let
  star_single = sstar + bitor_expr
  star_expr_comma = star_expression + comma

star_expression <- star_single | expression
star_expressions <- star_expr_comma.repOneOrMore + comma.repZeroOrMore

# --- slices ---
let
  slice_3 = expression + V_colon + expression + V_colon + expression
  slice_3ns = expression + V_colon + V_colon + expression
  slice_3nn = V_colon + expression + V_colon + expression
  slice_3bare = V_colon + V_colon + expression
  slice_2 = expression + V_colon + expression
  slice_1_start = expression + V_colon
  slice_1_stop = V_colon + expression
  slice_bare = V_colon
  slice_full =
    slice_3 | slice_3ns | slice_3nn | slice_3bare | slice_2 | slice_1_start |
    slice_1_stop | slice_bare

slice_expr <- slice_full | named_expression
slices <- slice_expr + (comma + slice_expr).repZeroOrMore + comma.repZeroOrMore

# --- arguments ---
let
  kwarg = ident + iop("=") + expression
  star_arg = sstar + expression
  dstar_arg = iop("**") + expression
  arg_def = kwarg | dstar_arg | star_arg | expression
  arg_comma = arg + comma

arg <- arg_def
arguments <- arg + arg_comma.repZeroOrMore + comma.repZeroOrMore

# --- comprehensions ---
let
  target = ident + (comma + ident).repZeroOrMore
  for_simple = I_FOR + target + ikw("in") + disjunction
  for_if_clause_def = for_simple + (I_IF + disjunction).repZeroOrMore

for_if_clause <- for_if_clause_def
for_if_clauses <- for_if_clause.repOneOrMore

listcomp <- named_expression + for_if_clauses
genexpr <- named_expression + for_if_clauses
dictcomp <- expression + colon + expression + for_if_clauses
setcomp <- expression + for_if_clauses

# --- dict/set makers ---
let
  kvpair = expression + V_colon + expression
  kvpair_comma = kvpair + comma

dictmaker <- kvpair + kvpair_comma.repZeroOrMore + comma.repZeroOrMore
setmaker <-
  star_expression + (comma + star_expression).repZeroOrMore + comma.repZeroOrMore

# ==============================================================================
# toPy transforms
# ==============================================================================

# Leaf tokens
registerTransform(
  "number",
  proc(n: AstNode): string =
    n.value,
)
registerTransform(
  "stringLit",
  proc(n: AstNode): string =
    n.value,
)
registerTransform(
  "ident",
  proc(n: AstNode): string =
    n.value,
)
registerTransform(
  "K_NONE",
  proc(n: AstNode): string =
    "None",
)
registerTransform(
  "K_TRUE",
  proc(n: AstNode): string =
    "True",
)
registerTransform(
  "K_FALSE",
  proc(n: AstNode): string =
    "False",
)
registerTransform(
  "V_ELLIPSIS",
  proc(n: AstNode): string =
    "...",
)

# Operators
proc opToPy(n: AstNode): string =
  if n.kind == nkLeaf:
    n.value
  elif n.kind == nkList and n.children.len > 0:
    n.children[0].value
  else:
    ""

for opName in [
  "V_PLUS", "V_MINUS", "V_STAR", "V_SLASH", "V_PERCENT", "V_DSLASH", "V_DSTAR",
  "V_TILDE", "V_AT", "V_PIPE", "V_CARET", "V_AMPER", "V_LSHIFT", "V_RSHIFT", "V_LT",
  "V_GT", "V_EQ", "V_NE", "V_LE", "V_GE", "V_colonEQUAL", "sstar", "K_AND", "K_OR",
  "K_NOT", "K_IN", "K_IS",
]:
  registerTransform(opName, opToPy)

# Binary operator helper
proc binopToPy(n: AstNode): string =
  var parts: seq[string] = @[n.children[0].transform("binop_base")]
  if n.children.len > 1:
    let opsNode = n.children[1]
    if opsNode.kind == nkList:
      for seq in opsNode.children:
        if seq.kind == nkList and seq.children.len >= 2:
          let op = seq.children[0].transform("op")
          let right = seq.children[1].transform("binop_right")
          parts.add(op)
          parts.add(right)
  if parts.len == 1:
    return parts[0]
  result = parts[0]
  var i = 1
  while i < parts.len:
    result = "(" & result & " " & parts[i] & " " & parts[i + 1] & ")"
    i += 2

# Register binary ops
registerTransform("term", binopToPy)
registerTransform("sum_expr", binopToPy)
registerTransform("shift_expr", binopToPy)
registerTransform("bitand_expr", binopToPy)
registerTransform("bitxor_expr", binopToPy)
registerTransform("bitor_expr", binopToPy)
registerTransform("conjunction", binopToPy)
registerTransform("disjunction", binopToPy)

# Comparison
registerTransform(
  "not_in_op",
  proc(n: AstNode): string =
    "not in",
)
registerTransform(
  "is_not_op",
  proc(n: AstNode): string =
    "is not",
)
registerTransform(
  "comp_op",
  proc(n: AstNode): string =
    n.children[0].transform("comp_op_child"),
)

registerTransform(
  "comparison",
  proc(n: AstNode): string =
    var parts: seq[string] = @[n.children[0].transform("bitor_expr")]
    if n.children.len > 1:
      let opsNode = n.children[1]
      if opsNode.kind == nkList:
        for seq in opsNode.children:
          if seq.kind == nkList and seq.children.len >= 2:
            parts.add(seq.children[0].transform("comp_op"))
            parts.add(seq.children[1].transform("bitor_expr"))
    if parts.len == 1:
      parts[0]
    else:
      "(" & parts.join(" ") & ")",
)

# Atom containers
registerTransform(
  "empty_paren",
  proc(n: AstNode): string =
    "()",
)
registerTransform(
  "paren_group",
  proc(n: AstNode): string =
    let inner = n.children[0].transform("paren_group_inner")
    if inner.startsWith("(") and inner.endsWith(")"):
      inner
    else:
      "(" & inner & ")",
)
registerTransform(
  "empty_list",
  proc(n: AstNode): string =
    "[]",
)
registerTransform(
  "list_display",
  proc(n: AstNode): string =
    "[" & n.children[0].transform("list_display_inner") & "]",
)
registerTransform(
  "empty_dict",
  proc(n: AstNode): string =
    "{}",
)
registerTransform(
  "dict_display",
  proc(n: AstNode): string =
    "{" & n.children[0].transform("dict_display_inner") & "}",
)
registerTransform(
  "set_display",
  proc(n: AstNode): string =
    "{" & n.children[0].transform("set_display_inner") & "}",
)
registerTransform(
  "atom",
  proc(n: AstNode): string =
    n.children[0].transform("atom_child"),
)

# Trailers
registerTransform(
  "call_trailer",
  proc(n: AstNode): string =
    if n.children.len > 0 and n.children[0].children.len > 0:
      "(" & n.children[0].children[0].transform("args") & ")"
    else:
      "()",
)
registerTransform(
  "slice_trailer",
  proc(n: AstNode): string =
    "[" & n.children[0].transform("slices") & "]",
)
registerTransform(
  "attr_trailer",
  proc(n: AstNode): string =
    "." & n.children[0].value,
)
registerTransform(
  "trailer",
  proc(n: AstNode): string =
    n.children[0].transform("trailer_child"),
)

# Primary
registerTransform(
  "primary",
  proc(n: AstNode): string =
    var result = n.children[0].transform("primary_base")
    if n.children.len > 1:
      for tr in n.children[1].children:
        result.add(tr.transform("trailer_child"))
    result,
)

# Await
registerTransform(
  "await_expr",
  proc(n: AstNode): string =
    "await " & n.children[0].transform("primary"),
)
registerTransform(
  "await_primary",
  proc(n: AstNode): string =
    n.children[0].transform("await_primary_child"),
)

# Power
registerTransform(
  "power_rhs",
  proc(n: AstNode): string =
    "** " & n.children[1].transform("factor"),
)
registerTransform(
  "power",
  proc(n: AstNode): string =
    var result = n.children[0].transform("await_primary")
    for i in 1 ..< n.children.len:
      let node = n.children[i]
      if node.children.len > 0:
        let first = node.children[0]
        if first.kind == nkList:
          for seq in first.children:
            if seq.kind == nkList and seq.children.len >= 2:
              let exp = seq.children[1].transform("factor")
              result = "(" & result & " ** " & exp & ")"
    result,
)

# Factor
registerTransform(
  "unary_plus",
  proc(n: AstNode): string =
    "(+" & n.children[0].transform("factor") & ")",
)
registerTransform(
  "unary_minus",
  proc(n: AstNode): string =
    "(-" & n.children[0].transform("factor") & ")",
)
registerTransform(
  "unary_tilde",
  proc(n: AstNode): string =
    "(~" & n.children[0].transform("factor") & ")",
)
registerTransform(
  "factor",
  proc(n: AstNode): string =
    n.children[0].transform("factor_child"),
)

# Inversion
registerTransform(
  "not_prefix",
  proc(n: AstNode): string =
    "(not " & n.children[0].transform("inversion") & ")",
)
registerTransform(
  "inversion",
  proc(n: AstNode): string =
    n.children[0].transform("inversion_child"),
)

# Walrus
registerTransform(
  "walrus",
  proc(n: AstNode): string =
    "(" & n.children[0].value & " := " & n.children[1].transform("expression") & ")",
)
registerTransform(
  "named_expression",
  proc(n: AstNode): string =
    n.children[0].transform("named_expr_child"),
)

# Conditional
registerTransform(
  "conditional",
  proc(n: AstNode): string =
    "(" & n.children[0].transform("disjunction") & " if " &
      n.children[1].transform("disjunction") & " else " &
      n.children[2].transform("expression") & ")",
)

# Lambda
registerTransform(
  "lambda_params",
  proc(n: AstNode): string =
    var parts: seq[string] = @[n.children[0].value]
    if n.children.len > 1:
      for seq in n.children[1].children:
        if seq.kind == nkList and seq.children.len > 0:
          parts.add(seq.children[0].value)
    parts.join(", "),
)

registerTransform(
  "lambda_expr",
  proc(n: AstNode): string =
    var params = ""
    var bodyIdx = 0
    if n.children.len >= 2:
      let paramsNode = n.children[0]
      if paramsNode.kind == nkList and paramsNode.children.len > 0:
        params = paramsNode.children[0].transform("lambda_params")
      bodyIdx = 1
    let body = n.children[bodyIdx].transform("expression")
    "(lambda " & params & ": " & body & ")",
)

# Expression
registerTransform(
  "expression",
  proc(n: AstNode): string =
    n.children[0].transform("expression_child"),
)

# Expressions
registerTransform(
  "expressions",
  proc(n: AstNode): string =
    var parts: seq[string] = @[n.children[0].transform("expression")]
    if n.children.len > 1:
      for node in n.children[1].children:
        if node.kind == nkList and node.children.len > 0:
          parts.add(node.children[0].transform("expression"))
    parts.join(", "),
)

# Yield
registerTransform(
  "yield_from",
  proc(n: AstNode): string =
    "(yield from " & n.children[0].transform("expression") & ")",
)
registerTransform(
  "yield_val",
  proc(n: AstNode): string =
    if n.children.len > 0 and n.children[0].kind == nkList and
        n.children[0].children.len > 0:
      "(yield " & n.children[0].children[0].transform("star_expressions") & ")"
    elif n.children.len > 0:
      "(yield " & n.children[0].transform("star_expressions") & ")"
    else:
      "(yield)",
)
registerTransform(
  "yield_expr",
  proc(n: AstNode): string =
    n.children[0].transform("yield_expr_child"),
)

# Star expressions
registerTransform(
  "star_single",
  proc(n: AstNode): string =
    "*" & n.children[1].transform("bitor_expr"),
)
registerTransform(
  "star_expression",
  proc(n: AstNode): string =
    n.children[0].transform("star_expr_child"),
)
registerTransform(
  "star_expressions",
  proc(n: AstNode): string =
    var parts: seq[string] = @[n.children[0].transform("star_expression")]
    if n.children.len > 1:
      for node in n.children[1].children:
        if node.kind == nkList and node.children.len > 0:
          parts.add(node.children[0].transform("star_expression"))
    parts.join(", "),
)

# Slices
registerTransform(
  "slice_3",
  proc(n: AstNode): string =
    n.children[0].transform("expression") & ":" & n.children[2].transform("expression") &
      ":" & n.children[4].transform("expression"),
)
registerTransform(
  "slice_3ns",
  proc(n: AstNode): string =
    n.children[0].transform("expression") & "::" & n.children[3].transform("expression"),
)
registerTransform(
  "slice_3nn",
  proc(n: AstNode): string =
    ":" & n.children[1].transform("expression") & ":" &
      n.children[3].transform("expression"),
)
registerTransform(
  "slice_3bare",
  proc(n: AstNode): string =
    "::" & n.children[2].transform("expression"),
)
registerTransform(
  "slice_2",
  proc(n: AstNode): string =
    n.children[0].transform("expression") & ":" & n.children[2].transform("expression"),
)
registerTransform(
  "slice_1_start",
  proc(n: AstNode): string =
    n.children[0].transform("expression") & ":",
)
registerTransform(
  "slice_1_stop",
  proc(n: AstNode): string =
    ":" & n.children[1].transform("expression"),
)
registerTransform(
  "slice_bare",
  proc(n: AstNode): string =
    ":",
)
registerTransform(
  "slice_full",
  proc(n: AstNode): string =
    n.children[0].transform("slice_child"),
)
registerTransform(
  "slice_expr",
  proc(n: AstNode): string =
    n.children[0].transform("slice_expr_child"),
)
registerTransform(
  "slices",
  proc(n: AstNode): string =
    var parts: seq[string] = @[n.children[0].transform("slice_expr")]
    if n.children.len > 1:
      for node in n.children[1].children:
        if node.kind == nkList and node.children.len > 0:
          parts.add(node.children[0].transform("slice_expr"))
    parts.join(", "),
)

# Arguments
registerTransform(
  "kwarg",
  proc(n: AstNode): string =
    n.children[0].value & "=" & n.children[1].transform("expression"),
)
registerTransform(
  "star_arg",
  proc(n: AstNode): string =
    "*" & n.children[1].transform("expression"),
)
registerTransform(
  "dstar_arg",
  proc(n: AstNode): string =
    "**" & n.children[0].transform("expression"),
)
registerTransform(
  "arg",
  proc(n: AstNode): string =
    n.children[0].transform("arg_child"),
)
registerTransform(
  "arguments",
  proc(n: AstNode): string =
    var parts: seq[string]
    if n.children[0].kind == nkList:
      for child in n.children[0].children:
        parts.add(child.transform("arg"))
    else:
      parts = @[n.children[0].transform("arg")]
    if n.children.len > 1:
      for node in n.children[1].children:
        if node.kind == nkList and node.children.len > 0:
          parts.add(node.children[0].transform("arg"))
    parts.join(", "),
)

# Comprehensions
registerTransform(
  "target",
  proc(n: AstNode): string =
    var parts: seq[string] = @[n.children[0].value]
    if n.children.len > 1:
      for seq in n.children[1].children:
        if seq.kind == nkList and seq.children.len > 0:
          parts.add(seq.children[0].value)
    parts.join(", "),
)

registerTransform(
  "for_if_clause",
  proc(n: AstNode): string =
    var result =
      "for " & n.children[0].transform("target") & " in " &
      n.children[1].transform("disjunction")
    if n.children.len > 2:
      for node in n.children[2].children:
        if node.kind == nkList:
          for f in node.children:
            result.add(" if " & f.transform("disjunction"))
    result,
)

registerTransform(
  "for_if_clauses",
  proc(n: AstNode): string =
    var parts: seq[string]
    for n in n.children:
      if n.kind == nkLeaf:
        parts.add(n.value)
      elif n.kind == nkList:
        for nn in n.children:
          if nn.kind == nkLeaf:
            parts.add(nn.value)
    parts.join(" "),
)

registerTransform(
  "listcomp",
  proc(n: AstNode): string =
    n.children[0].transform("named_expression") & " " &
      n.children[1].transform("for_if_clauses"),
)
registerTransform(
  "genexpr",
  proc(n: AstNode): string =
    n.children[0].transform("named_expression") & " " &
      n.children[1].transform("for_if_clauses"),
)
registerTransform(
  "dictcomp",
  proc(n: AstNode): string =
    n.children[0].transform("expression") & ": " & n.children[1].transform("expression") &
      " " & n.children[2].transform("for_if_clauses"),
)
registerTransform(
  "setcomp",
  proc(n: AstNode): string =
    n.children[0].transform("expression") & " " &
      n.children[1].transform("for_if_clauses"),
)

# Dict/set makers
registerTransform(
  "V_colon",
  proc(n: AstNode): string =
    ":",
)
registerTransform(
  "kvpair",
  proc(n: AstNode): string =
    n.children[0].transform("expression") & ": " & n.children[2].transform("expression"),
)
registerTransform(
  "dictmaker",
  proc(n: AstNode): string =
    var parts: seq[string] = @[n.children[0].transform("kvpair")]
    if n.children.len > 2:
      for node in n.children[2].children:
        if node.kind == nkList and node.children.len > 0:
          parts.add(node.children[0].transform("kvpair"))
    parts.join(", "),
)
registerTransform(
  "setmaker",
  proc(n: AstNode): string =
    var parts: seq[string] = @[n.children[0].transform("star_expression")]
    if n.children.len > 1:
      for node in n.children[1].children:
        if node.kind == nkList and node.children.len > 0:
          parts.add(node.children[0].transform("star_expression"))
    parts.join(", "),
)

# ==============================================================================
# Public API
# ==============================================================================

proc parseExpr*(code: string): AstNode =
  let stream = code.toTokenStream
  let result = expression.parse(stream)
  if result.isSome: result.get.ast else: nil

# ==============================================================================
# Tests
# ==============================================================================

when isMainModule: # Transforms need AST node naming support
  echo "============================================================"
  echo "Python 3.14 Expression Parser Tests"
  echo "============================================================"

  type Test = tuple[code: string, expected: string]
  let tests = [
    ("42", "42"),
    ("3.14", "3.14"),
    ("\"hello\"", "\"hello\""),
    ("'world'", "'world'"),
    ("None", "None"),
    ("True", "True"),
    ("False", "False"),
    ("...", "..."),
    ("1 + 2", "(1 + 2)"),
    ("1 + 2 * 3", "(1 + (2 * 3))"),
    ("(1 + 2) * 3", "((1 + 2) * 3)"),
    ("10 / 3", "(10 / 3)"),
    ("a @ b", "(a @ b)"),
    ("-x", "(-x)"),
    ("+x", "(+x)"),
    ("~x", "(~x)"),
    ("not x", "(not x)"),
    ("x ** 2", "(x ** 2)"),
    ("x < y", "(x < y)"),
    ("x == y", "(x == y)"),
    ("x != y", "(x != y)"),
    ("x | y", "(x | y)"),
    ("x ^ y", "(x ^ y)"),
    ("x & y", "(x & y)"),
    ("x << 2", "(x << 2)"),
    ("x >> 1", "(x >> 1)"),
    ("x and y", "(x and y)"),
    ("x or y", "(x or y)"),
    ("a if b else c", "(a if b else c)"),
    ("lambda x: x + 1", "(lambda x: (x + 1))"),
    ("f(x)", "f(x)"),
    ("f(x, y)", "f(x, y)"),
    ("a[i]", "a[i]"),
    ("obj.attr", "obj.attr"),
    ("f(x).y", "f(x).y"),
    ("[1, 2, 3]", "[1, 2, 3]"),
    ("[]", "[]"),
    ("()", "()"),
    ("{1, 2, 3}", "{1, 2, 3}"),
    ("{1: 2, 3: 4}", "{1: 2, 3: 4}"),
    ("f(x=1)", "f(x=1)"),
    ("f(*args)", "f(*args)"),
    ("f(**kwargs)", "f(**kwargs)"),
    ("[x for x in xs]", "[x for x in xs]"),
    ("{x for x in xs}", "{x for x in xs}"),
    ("a[1:2]", "a[1:2]"),
    ("await f()", "await f()"),
  ]

  var passed = 0
  var failed = 0

  for test in tests:
    let (code, expected) = test
    try:
      let result = parseExpr(code)
      if result != nil:
        let output = result.transform("expression")
        if output == expected:
          echo "  PASS: ", code, " -> ", output
          inc passed
        else:
          echo "  MISMATCH: ", code
          echo "    expected: ", expected
          echo "    got:      ", output
          inc failed
      else:
        echo "  FAIL: ", code, " -> parse returned nil"
        inc failed
    except Exception as e:
      echo "  ERROR: ", code, " -> ", e.msg
      inc failed

  echo "============================================================"
  echo "Results: ", passed, " passed, ", failed, " failed"
