## hek_parser.nim  –  parser combinator framework for recursive descent parsers.

import tables, strutils, sequtils, options, nre

# ─────────────────────────────────────────────────────────────────────────────
# AstNode  (declared first so the memo table type can reference it)
# ─────────────────────────────────────────────────────────────────────────────

type
  AstNodeKind* = enum nkEmpty, nkLeaf, nkList

  AstNode* = ref AstNodeObj
  AstNodeObj = object
    name*: string  # Parser name for transform lookup
    case kind*: AstNodeKind
    of nkEmpty: discard
    of nkLeaf:  value*: string
    of nkList:  children*: seq[AstNode]

proc newEmpty*(name: string = ""): AstNode = AstNode(name: name, kind: nkEmpty)
proc newLeaf*(value: string, name: string = ""): AstNode = AstNode(name: name, kind: nkLeaf, value: value)
proc newList*(children: seq[AstNode] = @[], name: string = ""): AstNode =
  AstNode(name: name, kind: nkList, children: children)

proc first*(n: AstNode): AstNode =
  if n.kind == nkList and n.children.len > 0: n.children[0] else: nil

proc last*(n: AstNode): AstNode =
  if n.kind == nkList and n.children.len > 0: n.children[^1] else: nil

proc len*(n: AstNode): int =
  case n.kind
  of nkList:  n.children.len
  of nkLeaf:  1
  of nkEmpty: 0

iterator items*(n: AstNode): AstNode =
  if n.kind == nkList:
    for c in n.children: yield c

proc `$`*(n: AstNode): string =
  if n == nil: return "<nil>"
  case n.kind
  of nkEmpty: "<empty>"
  of nkLeaf:  n.value
  of nkList:
    if n.children.len == 0: "[]"
    else: "[" & n.children.mapIt($it).join(", ") & "]"

proc treeRepr*(n: AstNode; indent = 0): string =
  ## Multi-line indented tree for debugging.
  if n == nil: return "  ".repeat(indent) & "<nil>"
  let pad = "  ".repeat(indent)
  case n.kind
  of nkEmpty: pad & "<empty>"
  of nkLeaf:  pad & "Leaf(" & n.value.escape & ")"
  of nkList:
    if n.children.len == 0: pad & "List[]"
    else: pad & "List\n" & n.children.mapIt(treeRepr(it, indent+1)).join("\n")

# ─────────────────────────────────────────────────────────────────────────────
# Token
# ─────────────────────────────────────────────────────────────────────────────

type
  TokenType* = enum
    ttName, ttNumber, ttString, ttOp, ttNewline, ttComment, ttError, ttEnd

  Token* = object
    typ*: TokenType
    str*: string
    line*, col*: int

proc `$`*(t: Token): string =
  $t.typ & "(" & t.str.escape & ")@" & $t.line & ":" & $t.col

# ─────────────────────────────────────────────────────────────────────────────
# TokenStream
# ─────────────────────────────────────────────────────────────────────────────

type
  MemoKey = tuple[parserId, pos: int]
  MemoVal = tuple[ast: AstNode; endPos: int; ok: bool]

  TokenStream* = ref object
    tokens*:      seq[Token]
    pos*:         int
    farthestPos*: int   ## highest token index reached (FIX: was col number)
    memos*:       Table[MemoKey, MemoVal]

proc mark*(s: TokenStream): int         = s.pos
proc reset*(s: TokenStream; pos: int)   = s.pos = pos
proc resetMemos*(s: TokenStream)        = s.memos.clear(); s.farthestPos = 0

proc farthestToken*(s: TokenStream): Token =
  ## The furthest token examined – used in ParseError messages.
  let p = min(s.farthestPos, s.tokens.high)
  s.tokens[p]

proc advance(s: TokenStream): Option[Token] =
  ## Consume the next meaningful token, skipping newlines and comments.
  while s.pos < s.tokens.len:
    let tok = s.tokens[s.pos]
    case tok.typ
    of ttNewline, ttComment: inc s.pos
    of ttEnd:                return none(Token)
    else:
      if s.pos > s.farthestPos: s.farthestPos = s.pos  # FIX: index vs index
      inc s.pos
      return some(tok)
  none(Token)

# ─────────────────────────────────────────────────────────────────────────────
# ParseError
# ─────────────────────────────────────────────────────────────────────────────

type ParseError* = object of CatchableError

proc newParseError(s: TokenStream): ref ParseError =
  let tok = s.farthestToken
  newException(ParseError,
    "Parse error at " & $tok.line & ":" & $tok.col &
    " near " & tok.str.escape)

# ─────────────────────────────────────────────────────────────────────────────
# Parser
# ─────────────────────────────────────────────────────────────────────────────

type
  ParseResult* = tuple[ast: AstNode; stream: TokenStream]
  ParseFunc*   = proc(stream: TokenStream): Option[ParseResult] {.closure.}

  Parser* = ref object
    id*:         int
    name*:       string
    parseFn*:    ParseFunc
    subParsers*: seq[Parser]  ## for Sequence/Choice, enables flattening in +/|

# Forward-resolver registry: stores a closure that updates the forward-ref cell
var fwdResolvers: Table[int, proc(r: Parser) {.closure.}]

var nextParserId = 0

proc newParser*(name: string; fn: ParseFunc): Parser =
  inc nextParserId
  Parser(id: nextParserId, name: name, parseFn: fn, subParsers: @[])

proc parse*(p: Parser; s: TokenStream): Option[ParseResult] =
  ## Memoised entry point.  All combinators call this, not parseFn directly.
  let key: MemoKey = (parserId: p.id, pos: s.pos)
  if key in s.memos:
    let m = s.memos[key]
    if m.ok: s.pos = m.endPos; return some((ast: m.ast, stream: s))
    return none(ParseResult)
  let saved = s.pos
  let r = p.parseFn(s)
  if r.isSome:
    s.memos[key] = (ast: r.get.ast, endPos: s.pos, ok: true)
  else:
    s.pos = saved
    s.memos[key] = (ast: nil, endPos: saved, ok: false)
  r

proc parseAll*(p: Parser; s: TokenStream): Option[ParseResult] =
  ## Top-level entry point: clears memos then calls parse.
  s.resetMemos()
  p.parse(s)

# ─────────────────────────────────────────────────────────────────────────────
# Primitive parsers  (FIX: now Parser objects, not bare procs)
# ─────────────────────────────────────────────────────────────────────────────

let shift* = newParser("shift", proc(s: TokenStream): Option[ParseResult] =
  let t = s.advance()
  if t.isSome: some((ast: newLeaf(t.get.str, "token"), stream: s))
  else: none(ParseResult))

let nothing* = newParser("nothing", proc(s: TokenStream): Option[ParseResult] =
  some((ast: newEmpty("parser"), stream: s)))

let fail* = newParser("fail", proc(s: TokenStream): Option[ParseResult] =
  none(ParseResult))

# ─────────────────────────────────────────────────────────────────────────────
# Combinators
# ─────────────────────────────────────────────────────────────────────────────

proc `+`*(a, b: Parser): Parser =
  ## Sequence: match a then b, collecting non-empty results.
  ## Flattens adjacent sequences so a+b+c is a single 3-parser node.
  let flat = (if a.name == "Sequence": a.subParsers else: @[a]) & @[b]
  let p = newParser("Sequence", proc(s: TokenStream): Option[ParseResult] =
    var nodes: seq[AstNode] = @[]
    let saved = s.pos
    for sub in flat:
      let r = sub.parse(s)
      if r.isNone: s.pos = saved; return none(ParseResult)
      let ast = r.get.ast
      if ast != nil and ast.kind != nkEmpty: nodes.add(ast)
    let ast =
      if nodes.len == 0: newEmpty()
      elif nodes.len == 1: nodes[0]
      else: newList(nodes, "sequence")
    some((ast: ast, stream: s)))
  p.subParsers = flat
  p

proc `|`*(a, b: Parser): Parser =
  ## Ordered choice: try a; on failure restore position and try b.
  ## Flattens adjacent choices so a|b|c is a single n-parser node.
  let flat = (if a.name == "Choice": a.subParsers else: @[a]) & @[b]
  let p = newParser("Choice", proc(s: TokenStream): Option[ParseResult] =
    let saved = s.pos
    for sub in flat:
      s.pos = saved
      let r = sub.parse(s)
      if r.isSome: return r
    none(ParseResult))
  p.subParsers = flat
  p

proc `[]`*(p: Parser; range: HSlice[int, int]): Parser =
  ## Repeat p between range.a and range.b times (-1 = unbounded).
  let minT = max(range.a, 0)
  let maxT = range.b
  newParser("Repeat", proc(s: TokenStream): Option[ParseResult] =
    var nodes: seq[AstNode] = @[]
    let saved = s.pos
    while true:
      let iterPos = s.pos                  # FIX: save per-iteration position
      let r = p.parse(s)
      if r.isSome:
        let ast = r.get.ast
        if ast != nil and ast.kind != nkEmpty: nodes.add(ast)
        if maxT >= 0 and nodes.len >= maxT: break
      else:
        s.pos = iterPos                    # FIX: restore only this iteration
        break
    if nodes.len < minT: s.pos = saved; return none(ParseResult)
    some((ast: newList(nodes, "sequence"), stream: s)))

proc `*`*(p: Parser; n: int): Parser =
  ## Match exactly n repetitions.
  p[n .. n]

proc opt*(p: Parser): Parser =
  ## Optional: match zero or one occurrence.  Always succeeds.
  newParser("Opt", proc(s: TokenStream): Option[ParseResult] =
    let saved = s.pos
    let r = p.parse(s)
    if r.isSome: return r
    s.pos = saved
    some((ast: newEmpty("parser"), stream: s)))

proc `~`*(p: Parser): Parser =
  ## Negative lookahead: succeeds (consuming nothing) only when p fails.
  newParser("NegLookahead", proc(s: TokenStream): Option[ParseResult] =
    let saved = s.pos
    let r = p.parse(s)
    s.pos = saved
    if r.isSome: none(ParseResult)
    else: some((ast: newEmpty("parser"), stream: s)))

proc peek*(p: Parser): Parser =
  ## Positive lookahead: succeeds (consuming nothing) when p would match.
  newParser("PosLookahead", proc(s: TokenStream): Option[ParseResult] =
    let saved = s.pos
    let r = p.parse(s)
    s.pos = saved
    if r.isSome: some((ast: newEmpty("parser"), stream: s))
    else: none(ParseResult))

proc ignore*(p: Parser): Parser =
  ## Match p but produce nkEmpty so sequence drops the result.
  newParser("Ignore", proc(s: TokenStream): Option[ParseResult] =
    let r = p.parse(s)
    if r.isSome: some((ast: newEmpty("parser"), stream: s))
    else: none(ParseResult))

proc sep*(item, delim: Parser): Parser =
  ## Separated list: item (delim item)*.
  ## e.g. sep(ident, comma) parses "a, b, c" → List[a, b, c].
  ## Requires at least one item; wrap in opt() for zero-or-more.
  let rest = ignore(delim) + item
  newParser("Sep", proc(s: TokenStream): Option[ParseResult] =
    let r0 = item.parse(s)
    if r0.isNone: return none(ParseResult)
    var nodes: seq[AstNode] = @[r0.get.ast]
    while true:
      let saved = s.pos
      let r = rest.parse(s)
      if r.isNone: s.pos = saved; break
      let ast = r.get.ast
      if ast != nil and ast.kind != nkEmpty: nodes.add(ast)
    some((ast: newList(nodes, "sequence"), stream: s)))

proc cut*(p: Parser): Parser =
  ## Committed branch: if p fails, raise ParseError instead of backtracking.
  ## Use as: keyword + cut(body) – once keyword matched, body must succeed.
  newParser("Cut_" & p.name, proc(s: TokenStream): Option[ParseResult] =
    let r = p.parse(s)
    if r.isNone: raise s.newParseError()
    r)

proc filt*(predicate: proc(n: AstNode): bool {.closure.}; p: Parser): Parser =
  ## Filter: succeed only when p matches AND predicate(ast) is true.
  newParser("Filter", proc(s: TokenStream): Option[ParseResult] =
    let saved = s.pos
    let r = p.parse(s)
    if r.isSome and predicate(r.get.ast): return r
    s.pos = saved
    none(ParseResult))

proc fmap*(fn: proc(n: AstNode): AstNode {.closure.}; p: Parser): Parser =
  ## Map: transform the AstNode produced by p.
  newParser("Fmap", proc(s: TokenStream): Option[ParseResult] =
    let r = p.parse(s)
    if r.isSome: some((ast: fn(r.get.ast), stream: s))
    else: none(ParseResult))

proc repZeroOrMore*(p: Parser): Parser = p[0 .. -1]
proc repOneOrMore*(p: Parser): Parser  = p[1 .. -1]

# ─────────────────────────────────────────────────────────────────────────────
# Forward references  (FIX: single Parser type, no ForwardParser)
# ─────────────────────────────────────────────────────────────────────────────
#
# forward() returns a plain Parser whose parseFn is a closure over a mutable
# cell.  `<-` calls the registered resolver to swap in the real parser.
#
# Usage:
#   let expr = forward("expr")
#   expr <- term + more_terms

proc forward*(name: string): Parser =
  ## Create a named lazy forward reference.  Must be resolved with `<-` before parsing.
  var cell: Parser = nil
  let p = newParser(name, proc(s: TokenStream): Option[ParseResult] =
    if cell == nil:
      raise newException(ValueError, "Forward ref '" & name & "' not resolved")
    # Call parseFn directly (bypass parse/memo) to avoid double-memoising.
    # The outer parse() already memoises this forward stub.
    cell.parseFn(s))
  fwdResolvers[p.id] = proc(resolved: Parser) {.closure.} =
    cell = resolved
  p

proc `<-`*(p: Parser; resolved: Parser) =
  ## Resolve a forward reference.
  if p.id in fwdResolvers: fwdResolvers[p.id](resolved)
  else: raise newException(ValueError, "Parser '" & p.name & "' is not a forward ref")

# ─────────────────────────────────────────────────────────────────────────────
# Token-matching helpers  (FIX: reset pos on failure)
# ─────────────────────────────────────────────────────────────────────────────

proc expectType*(typ: TokenType): Parser =
  newParser("ExpectType_" & $typ, proc(s: TokenStream): Option[ParseResult] =
    let saved = s.pos
    let t = s.advance()
    if t.isSome and t.get.typ == typ:
      return some((ast: newLeaf(t.get.str, "token"), stream: s))
    s.pos = saved   # FIX: restore on failure
    none(ParseResult))

proc expect*(typ: TokenType; val: string): Parser =
  newParser("Expect_" & val, proc(s: TokenStream): Option[ParseResult] =
    let saved = s.pos
    let t = s.advance()
    if t.isSome and t.get.typ == typ and t.get.str == val:
      return some((ast: newLeaf(val, "expect_" & val), stream: s))
    s.pos = saved   # FIX: restore on failure
    none(ParseResult))

proc literal*(val: string): Parser = expect(ttName, val)

proc expectRe*(pattern: string): Parser =
  let rx = re(pattern)
  newParser("ExpectRe", proc(s: TokenStream): Option[ParseResult] =
    let saved = s.pos
    let t = s.advance()
    if t.isSome and t.get.str.contains(rx):
      return some((ast: newLeaf(t.get.str, "token"), stream: s))
    s.pos = saved   # FIX: restore on failure
    none(ParseResult))

# ─────────────────────────────────────────────────────────────────────────────
# Lexer  (newTokenStream)
# ─────────────────────────────────────────────────────────────────────────────

proc newTokenStream*(source: string): TokenStream =
  var tokens: seq[Token] = @[]
  var pos  = 0
  var line = 1
  var col  = 1

  # Operator tables – longest match tried first (FIX: 3-char before 2-char)
  const ops3 = ["<<=", ">>=", "**=", "//=", "..."]
  const ops2 = ["==", "!=", "<=", ">=", "+=", "-=", "*=", "/=", "%=",
                "&=", "|=", "^=", "<<", ">>", "**", "//", "->", ":=", ".."]
  const opStarts = {'+','-','*','/','%','&','|','^','~','<','>','=','!',
                    '(',')','{','}','[',']',',',';',':','.','?','@','\\'}

  while pos < source.len:
    let c = source[pos]

    # Whitespace
    if c in {' ', '\t'}:
      inc pos; inc col; continue

    # Newline
    if c == '\n':
      tokens.add Token(typ: ttNewline, str: "\n", line: line, col: col)
      inc pos; inc line; col = 1; continue

    # Comment  (FIX: was `source[pos..^1]`, now captures only the comment)
    if c == '#':
      let startCol = col; let startPos = pos
      while pos < source.len and source[pos] != '\n': inc pos; inc col
      tokens.add Token(typ: ttComment, str: source[startPos ..< pos],
                       line: line, col: startCol)
      continue

    # String literal  '...' or "..."
    if c in {'"', '\''}:
      let startCol = col; let quote = c
      var strVal = ""; inc pos; inc col
      while pos < source.len and source[pos] != quote:
        if source[pos] == '\\' and pos + 1 < source.len: inc pos; inc col
        strVal.add source[pos]; inc pos; inc col
      if pos < source.len: inc pos; inc col
      tokens.add Token(typ: ttString, str: strVal, line: line, col: startCol)
      continue

    # Number
    if c.isDigit or (c == '.' and pos+1 < source.len and source[pos+1].isDigit):
      let startCol = col; var num = ""
      while pos < source.len and
            (source[pos].isAlphaNumeric or source[pos] in {'.', '_'} or
             (source[pos] in {'+','-'} and pos > 0 and source[pos-1] in {'e','E'})):
        num.add source[pos]; inc pos; inc col
      tokens.add Token(typ: ttNumber, str: num, line: line, col: startCol)
      continue

    # Identifier / keyword
    if c.isAlphaAscii or c == '_':
      let startCol = col; var name = ""
      while pos < source.len and (source[pos].isAlphaNumeric or source[pos] == '_'):
        name.add source[pos]; inc pos; inc col
      tokens.add Token(typ: ttName, str: name, line: line, col: startCol)
      continue

    # Operators  (FIX: try 3-char, then 2-char, then 1-char)
    if c in opStarts:
      let startCol = col; var op = ""
      if pos+2 < source.len and source[pos .. pos+2] in ops3:
        op = source[pos .. pos+2]; inc pos, 3; inc col, 3
      elif pos+1 < source.len and source[pos .. pos+1] in ops2:
        op = source[pos .. pos+1]; inc pos, 2; inc col, 2
      else:
        op = $c; inc pos; inc col
      tokens.add Token(typ: ttOp, str: op, line: line, col: startCol)
      continue

    # Error token
    tokens.add Token(typ: ttError, str: $c, line: line, col: col)
    inc pos; inc col

  tokens.add Token(typ: ttEnd, str: "", line: line, col: col)
  TokenStream(tokens: tokens, pos: 0, farthestPos: 0,
              memos: initTable[MemoKey, MemoVal]())

proc toTokenStream*(source: string): TokenStream = newTokenStream(source)

# ─────────────────────────────────────────────────────────────────────────────
# Stock token parsers
# ─────────────────────────────────────────────────────────────────────────────

let
  lparen*    = ignore(expect(ttOp, "("))
  rparen*    = ignore(expect(ttOp, ")"))
  lbrace*    = ignore(expect(ttOp, "{"))
  rbrace*    = ignore(expect(ttOp, "}"))
  lbracket*  = ignore(expect(ttOp, "["))
  rbracket*  = ignore(expect(ttOp, "]"))
  comma*     = ignore(expect(ttOp, ","))
  semicolon* = ignore(expect(ttOp, ";"))
  vbar*      = ignore(expect(ttOp, "|"))
  colon*     = ignore(expect(ttOp, ":"))
  eq*        = ignore(expect(ttOp, "="))
  plus*      = ignore(expect(ttOp, "+"))
  minus*     = ignore(expect(ttOp, "-"))
  star*      = ignore(expect(ttOp, "*"))
  slash*     = ignore(expect(ttOp, "/"))
  ident*     = expectType(ttName)
  number*    = expectRe(r"^[0-9]+(\.[0-9]+)?([eE][+-]?[0-9]+)?$")
  stringLit* = expectType(ttString)
  dot*        = ignore(expect(ttOp, "."))
  questionMark* = ignore(expect(ttOp, "?"))
  sstar*       = expect(ttOp, "*")

# ─────────────────────────────────────────────────────────────────────────────
# TransformRegistry  (unchanged API; defTransform macro removed – it was broken)
# ─────────────────────────────────────────────────────────────────────────────

type
  TransformFunc*    = proc(node: AstNode): string {.closure.}
  TransformRegistry = Table[string, TransformFunc]

var transformRegistry*: TransformRegistry = initTable[string, TransformFunc]()

proc registerTransform*(key: string; fn: TransformFunc) =
  transformRegistry[key] = fn

proc transform*(node: AstNode; key: string = ""): string =
  let lookupKey = if key != "": key elif node.name != "": node.name else: ""
  if lookupKey != "" and lookupKey in transformRegistry: transformRegistry[lookupKey](node) else: $node

# ─────────────────────────────────────────────────────────────────────────────
# when isMainModule
# ─────────────────────────────────────────────────────────────────────────────

when isMainModule:
  echo "=== Parser Combinator Tests ===\n"

  # 1. Sequence
  block:
    echo "1. Sequence (A + B + C + D):"
    let keyvalue = ident + eq + number + semicolon
    let s = "x=789;".toTokenStream
    let r = keyvalue.parseAll(s)
    echo "   ", if r.isSome: "OK: " & $r.get.ast else: "FAIL"

  # 2. Repetition
  block:
    echo "\n2. Repetition (A[1..]):"
    let keyvalue = ident + eq + number + semicolon
    let keyvalues = keyvalue.repOneOrMore
    let s = "x=2; y=3.4;".toTokenStream
    let r = keyvalues.parseAll(s)
    echo "   ", if r.isSome: "OK: " & $r.get.ast else: "FAIL"
    # Verify stream position is NOT reset to zero (the original bug)
    echo "   stream.pos after parse: ", s.pos, " (should be > 0)"

  # 3. Choice
  block:
    echo "\n3. Choice (A | B):"
    let identOrNum = ident | number
    for src in ["hello", "123"]:
      let s = src.toTokenStream
      let r = identOrNum.parseAll(s)
      echo "   ", if r.isSome: "OK '" & src & "': " & $r.get.ast else: "FAIL"

  # 4. Negative lookahead
  block:
    echo "\n4. Negative lookahead (~A):"
    let notComma = ~comma + ident
    var s = "abc".toTokenStream
    var r = notComma.parseAll(s)
    echo "   non-comma: ", if r.isSome: "OK: " & $r.get.ast else: "FAIL"
    s = ", x".toTokenStream
    r = (~comma).parseAll(s)
    echo "   comma:     ", if r.isNone: "OK: correctly rejected" else: "FAIL"

  # 5. Peek (positive lookahead)
  block:
    echo "\n5. peek (positive lookahead):"
    let peekThenConsume = peek(ident) + ident
    let s = "hello".toTokenStream
    let r = peekThenConsume.parseAll(s)
    echo "   ", if r.isSome: "OK: " & $r.get.ast else: "FAIL"

  # 6. opt
  block:
    echo "\n6. opt (zero-or-one):"
    let optNum = ident + opt(number)
    var s = "x 42".toTokenStream
    var r = optNum.parseAll(s)
    echo "   with number:    ", if r.isSome: "OK: " & $r.get.ast else: "FAIL"
    s = "x".toTokenStream
    r = optNum.parseAll(s)
    echo "   without number: ", if r.isSome: "OK: " & $r.get.ast else: "FAIL"

  # 7. sep
  block:
    echo "\n7. sep (item, delim):"
    let identList = sep(ident, comma)
    var s = "a, b, c".toTokenStream
    var r = identList.parseAll(s)
    echo "   3 items: ", if r.isSome: "OK: " & $r.get.ast else: "FAIL"
    s = "a".toTokenStream
    r = identList.parseAll(s)
    echo "   1 item:  ", if r.isSome: "OK: " & $r.get.ast else: "FAIL"

  # 8. Forward reference (recursive grammar: s-expr)
  block:
    echo "\n8. Forward reference (recursive s-expr):"
    let atom  = forward("atom")
    let sExpr = lparen + atom.repZeroOrMore + rparen
    atom <- ident | number | sExpr
    let s = "(a b (c 3) (d 4 5))".toTokenStream
    let r = sExpr.parseAll(s)
    echo "   ", if r.isSome: "OK: " & $r.get.ast else: "FAIL"

  # 9. cut
  block:
    echo "\n9. cut (committed branch):"
    let ifExpr = literal("if") + cut(ident)
    var s = "if cond".toTokenStream
    var r = ifExpr.parseAll(s)
    echo "   good input: ", if r.isSome: "OK: " & $r.get.ast else: "FAIL"
    s = "if 123".toTokenStream
    try:
      r = ifExpr.parseAll(s)
      echo "   bad input: FAIL (should have raised ParseError)"
    except ParseError as e:
      echo "   bad input: OK, raised ParseError: " & e.msg

  # 10. treeRepr
  block:
    echo "\n10. treeRepr:"
    let keyvalue = ident + eq + number + semicolon
    let s = "x=789;".toTokenStream
    let r = keyvalue.parseAll(s)
    if r.isSome: echo treeRepr(r.get.ast)
    else: echo "   FAIL"

  # 11. Transform registry
  block:
    echo "\n11. Transform registry:"
    let s = "hello".toTokenStream
    let r = ident.parseAll(s)
    registerTransform("upper", proc(n: AstNode): string =
      case n.kind
      of nkLeaf: n.value.toUpperAscii
      of nkList: n.children.mapIt(transform(it, "upper")).join(", ")
      of nkEmpty: "")
    if r.isSome: echo "   ", transform(r.get.ast, "upper")
    else: echo "   FAIL"

  # 12. Memoisation: a parser at the same position is only called once
  block:
    echo "\n12. Memoisation:"
    var hitCount = 0
    let countingIdent = newParser("counting", proc(s: TokenStream): Option[ParseResult] =
      inc hitCount
      ident.parse(s))
    # ambig tries countingIdent+eq then countingIdent+colon
    let ambig = (countingIdent + eq) | (countingIdent + colon)
    let s = "x:1".toTokenStream
    hitCount = 0
    discard ambig.parseAll(s)
    echo "   countingIdent called ", hitCount,
         " time(s) at pos 0 (expected 1 with packrat)"

  # 13. 3-char operator lexing
  block:
    echo "\n13. 3-char operators:"
    for src in ["<<=", ">>=", "**=", "//="]:
      let s = src.toTokenStream
      let r = expect(ttOp, src).parseAll(s)
      echo "   ", src, ": ", if r.isSome: "OK" else: "FAIL"

  # 14. Comment capture
  block:
    echo "\n14. Comment capture:"
    let s = newTokenStream("# just a comment\nhello")
    let r = ident.parseAll(s)
    echo "   ident after comment: ", if r.isSome: "OK: " & $r.get.ast else: "FAIL"
    let commentTok = s.tokens[0]
    echo "   comment text: ", commentTok.str.escape,
         " (should be '# just a comment', not rest-of-file)"


  # 6. Empty s-expr (forward reference with <-)
  block:
    echo "\n6. Empty s-expr ():"
    let atom6 = forward("atom6")
    let sExpr6 = forward("sExpr6")
    sExpr6 <- lparen + atom6.repZeroOrMore + rparen
    atom6 <- ident | number | sExpr6
    let s = "()".toTokenStream
    let r = sExpr6.parse(s)
    echo "   ", if r.isSome: "OK: " & $r.get.ast else: "FAIL"

  # 7. Type declarations (forward references from Python version)
  block:
    echo "\n7. Type declarations:"
    let noneType = literal("None")
    let intType = literal("int")
    let strType = literal("str")
    let floatType = literal("float")
    let boolType = literal("bool")
    let typeAlias = ident

    let basicType = forward("basicType")
    let primitiveType = forward("primitiveType")
    let pointerType = forward("pointerType")
    let optionalType = forward("optionalType")
    let maybePointerType = forward("maybePointerType")
    let unionType = forward("unionType")
    let typeDecl = forward("typeDecl")

    primitiveType <- noneType | floatType | boolType | strType | intType
    pointerType <- star + basicType
    maybePointerType <- pointerType | basicType
    optionalType <- maybePointerType + questionMark
    unionType <- maybePointerType + (vbar + maybePointerType).repOneOrMore
    basicType <- primitiveType | pointerType | typeAlias
    typeDecl <- unionType | optionalType

    var s = "*int".toTokenStream
    var r = pointerType.parse(s)
    echo "   pointer *int: ", if r.isSome: "OK: " & $r.get.ast else: "FAIL"

    s = "str?".toTokenStream
    r = optionalType.parse(s)
    echo "   optional str?: ", if r.isSome: "OK: " & $r.get.ast else: "FAIL"

    s = "str|float|mytype".toTokenStream
    r = unionType.parse(s)
    echo "   union str|float|mytype: ", if r.isSome: "OK: " & $r.get.ast else: "FAIL"

    s = "*str?".toTokenStream
    r = typeDecl.parse(s)
    echo "   optional pointer *str?: ", if r.isSome: "OK: " & $r.get.ast else: "FAIL"

  echo "\n=== Tokenizer Tests ==="

  block:
    echo "\nT1. 3-char operators:"
    for src in ["<<=", ">>=", "**=", "//="]:
      let s = src.toTokenStream
      let r = expect(ttOp, src).parse(s)
      echo "   ", src, ": ", if r.isSome: "OK" else: "FAIL"

  block:
    echo "\nT2. Comment capture:"
    let s = newTokenStream("# just a comment\nhello")
    let r = ident.parse(s)
    echo "   ident after comment: ", if r.isSome: "OK: " & $r.get.ast else: "FAIL"

  echo "\n=== All tests completed ==="
