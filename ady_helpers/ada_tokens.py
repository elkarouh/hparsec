"""AdaScript tokens for hparsec: Input(), the legacy token names, and their self-tests.

hparsec itself does not import this module. Code that parses AdaScript imports it:

    from ada_tokens import Input, NUMBER, PLUS
"""

import tokenize as tkn
from typing import Callable

from ady_tokenizer import Tokenizer
from hparsec import *  # noqa: F401,F403
from hparsec import SymbolTable


###############################################################################
# Lazy-loaded legacy tokens and adapters for tokenize / ady_tokenizer
_LEGACY_TOKEN_NAMES = {
    "Tokenizer",
    "Input",
    "expect_nl_or_richnl",
    # Delimiters
    "LPAREN", "RPAREN", "LBRACE", "RBRACE", "LBRACKET", "RBRACKET",
    "COMMA", "SEMICOLON", "VBAR", "COLON", "EQUAL",
    # Arithmetic operators
    "PLUS", "MINUS", "MUL", "STAR", "SSTAR", "DIV", "SLASH",
    "PERCENT", "DOUBLESTAR", "DOUBLESLASH",
    # Bitwise operators
    "AMPER", "TILDE", "CIRCUMFLEX", "LEFTSHIFT", "RIGHTSHIFT",
    # Comparison operators
    "LESS", "GREATER", "EQEQUAL", "NOTEQUAL", "LESSEQUAL", "GREATEREQUAL",
    # Assignment operators
    "PLUSEQUAL", "MINEQUAL", "STAREQUAL", "SLASHEQUAL", "PERCENTEQUAL",
    "AMPEREQUAL", "VBAREQUAL", "CIRCUMFLEXEQUAL", "LEFTSHIFTEQUAL",
    "RIGHTSHIFTEQUAL", "DOUBLESTAREQUAL", "DOUBLESLASHEQUAL",
    # Other operators
    "DOT", "RARROW", "ELLIPSIS", "COLONEQUAL",
    "DOUBLEDOT", "RANGE_OP", "RANGE_EXCL_OP",
    "TICK", "DOLLAR", "BASH_TEST", "BASH_CMP",
    "REGEX_LIT", "CAPTURE", "NAMED_CAPTURE", "SUBST",
    # Semantic tokens
    "IDENTIFIER", "NUMBER", "STRING", "INTEGER", "FLOAT", "DECIMAL", "QUESTION_MARK",
}


def _init_legacy_tokens():
    """Lazily initialize legacy token parsers and Input() that depend on tokenize / ady_tokenizer."""
    if "Input" in globals():
        return
    import tokenize as tkn

    def Input(string: str):
        """Create a token stream using ady_tokenizer (loaded on demand)."""
        from ady_tokenizer import Tokenizer

        gen = Tokenizer(string)
        next(gen)  # skip the encoding token
        return gen

    def expect_nl_or_richnl():
        """Match NL token or RichNL object and return it."""
        return filt(lambda tok: getattr(tok, "type", None) == tkn.NL, shift, name="NL")

    def _op(symbol: str):
        return ignore(expect(tkn.OP, symbol))

    def _visible_op(symbol: str):
        return expect(tkn.OP, symbol)

    # Synthetic token type numbers reserved by ady_tokenizer
    _TICK_TOKEN          = 90
    _DOLLAR_TOKEN        = 91
    _BASH_TEST_TOKEN     = 92
    _BASH_CMP_TOKEN      = 93
    _RANGE_TOKEN         = 94
    _RANGE_EXCL_TOKEN    = 95
    _REGEX_TOKEN         = 98
    _CAPTURE_TOKEN       = 99
    _NAMED_CAPTURE_TOKEN = 100
    _SUBST_TOKEN         = 101

    range_op = fmap(lambda tok: tok.string, filt(lambda tok: getattr(tok, "type", None) == _RANGE_TOKEN, shift, name=".."))
    sstar = _visible_op("*")
    identifier = filt(str.isidentifier, expect_type(tkn.NAME))
    number = expect_re(tkn.Number)
    string = expect_re(tkn.String)
    integer = filt(str.isdecimal, expect_type(tkn.NUMBER))
    float_tok = expect_re(tkn.Floatnumber)

    tokens = {
        "Input": Input,
        "expect_nl_or_richnl": expect_nl_or_richnl,
        # Delimiters
        "LPAREN": _op("("),
        "RPAREN": _op(")"),
        "LBRACE": _op("{"),
        "RBRACE": _op("}"),
        "LBRACKET": _op("["),
        "RBRACKET": _op("]"),
        "COMMA": _op(","),
        "SEMICOLON": _op(";"),
        "VBAR": _op("|"),
        "COLON": _op(":"),
        "EQUAL": _op("="),
        # Arithmetic operators
        "PLUS": _op("+"),
        "MINUS": _op("-"),
        "MUL": _op("*"),
        "STAR": _op("*"),
        "SSTAR": sstar,
        "DIV": _op("/"),
        "SLASH": _op("/"),
        "PERCENT": _op("%"),
        "DOUBLESTAR": _op("**"),
        "DOUBLESLASH": _op("//"),
        # Bitwise operators
        "AMPER": _op("&"),
        "TILDE": _op("~"),
        "CIRCUMFLEX": _op("^"),
        "LEFTSHIFT": _op("<<"),
        "RIGHTSHIFT": _op(">>"),
        # Comparison operators
        "LESS": _op("<"),
        "GREATER": _op(">"),
        "EQEQUAL": _op("=="),
        "NOTEQUAL": _op("!="),
        "LESSEQUAL": _op("<="),
        "GREATEREQUAL": _op(">="),
        # Assignment operators
        "PLUSEQUAL": _op("+="),
        "MINEQUAL": _op("-="),
        "STAREQUAL": _op("*="),
        "SLASHEQUAL": _op("/="),
        "PERCENTEQUAL": _op("%="),
        "AMPEREQUAL": _op("&="),
        "VBAREQUAL": _op("|="),
        "CIRCUMFLEXEQUAL": _op("^="),
        "LEFTSHIFTEQUAL": _op("<<="),
        "RIGHTSHIFTEQUAL": _op(">>="),
        "DOUBLESTAREQUAL": _op("**="),
        "DOUBLESLASHEQUAL": _op("//="),
        # Other operators
        "DOT": _op("."),
        "RARROW": _op("->"),
        "ELLIPSIS": _op("..."),
        "COLONEQUAL": _op(":="),
        "DOUBLEDOT": ignore(range_op),
        "RANGE_OP": range_op,
        "RANGE_EXCL_OP": fmap(lambda tok: tok.string, filt(lambda tok: getattr(tok, "type", None) == _RANGE_EXCL_TOKEN, shift, name="..<")),
        "TICK": ignore(filt(lambda tok: getattr(tok, "type", None) == _TICK_TOKEN, shift, name="'")),
        "DOLLAR": ignore(filt(lambda tok: getattr(tok, "type", None) == _DOLLAR_TOKEN, shift, name="$")),
        "BASH_TEST": filt(lambda tok: getattr(tok, "type", None) == _BASH_TEST_TOKEN, shift, name="bash_test"),
        "BASH_CMP": fmap(lambda tok: tok.string, filt(lambda tok: getattr(tok, "type", None) == _BASH_CMP_TOKEN, shift, name="bash_cmp")),
        "REGEX_LIT": fmap(lambda tok: tok.string, filt(lambda tok: getattr(tok, "type", None) == _REGEX_TOKEN, shift, name="regex_lit")),
        "CAPTURE": fmap(lambda tok: tok.string, filt(lambda tok: getattr(tok, "type", None) == _CAPTURE_TOKEN, shift, name="capture")),
        "NAMED_CAPTURE": fmap(lambda tok: tok.string, filt(lambda tok: getattr(tok, "type", None) == _NAMED_CAPTURE_TOKEN, shift, name="named_capture")),
        "SUBST": fmap(lambda tok: tok.string, filt(lambda tok: getattr(tok, "type", None) == _SUBST_TOKEN, shift, name="subst")),
        # Semantic tokens
        "IDENTIFIER": identifier,
        "NUMBER": number,
        "STRING": string,
        "INTEGER": integer,
        "FLOAT": float_tok,
        "DECIMAL": expect_re(tkn.Decnumber),
        "QUESTION_MARK": ignore(expect(tkn.ERRORTOKEN, "?")),
    }

    # AST methods
    for parser_cls in (identifier, number, integer, string, float_tok, sstar):
        @method(parser_cls)
        def to_py(self):
            return self.node

    globals().update(tokens)


def __getattr__(name):
    """Load legacy tokens, Input(), and Tokenizer on demand."""
    if name == "Tokenizer":
        from ady_tokenizer import Tokenizer
        return Tokenizer
    if name in _LEGACY_TOKEN_NAMES:
        _init_legacy_tokens()
        return globals()[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")



_init_legacy_tokens()


if __name__ == "__main__":
    # The tokenizer and legacy token definitions are needed only by this test harness.
    _init_legacy_tokens()
    from ady_tokenizer import Tokenizer

    # THE ADASCRIPT_GRAMMAR
    keyvalue = IDENTIFIER + EQUAL + NUMBER + SEMICOLON
    keyvalues = keyvalue[1:]

    @method(keyvalue)
    def to_py(self):
        return f"{self.nodes[0].to_py()}:{self.nodes[1].to_py()}"

    @method(keyvalues)
    def to_py(self):
        output = "{ "
        output += ", ".join(ast.to_py() for ast in self.nodes)
        return output + " }"

    ####################################################
    m = keyvalue.parse(Input("x=789;"))
    assert m, "keyvalue parse failed"
    ast, rest = m
    assert ast.__class__.__name__ == keyvalue.__name__
    print(f"keyvalue: {ast.to_py()}")

    m = keyvalues.parse(Input("x=2; y=3.4; z=.789;"))
    assert m, "keyvalues parse failed"
    ast, remaining = m
    print(f"keyvalues: {ast.to_py()}")

    ParserState.reset()
    ###################################################################################
    # recursive grammar for s-expressions
    atom = fw("atom")
    # lisp grammar
    s_expr = LPAREN + atom[:] + RPAREN
    atom = IDENTIFIER | NUMBER | STRING | s_expr

    @method(s_expr)
    def to_py(self):
        return f"({' '.join(member.to_py() for res in self.nodes for member in res.nodes)})"

    m = s_expr.parse(Input("()"))
    assert m, "empty s_expr parse failed"

    m = s_expr.parse(Input("(a b (c 3) (d '5' 6) 7 8)"))
    assert m, "s_expr parse failed"
    print(f"s_expr: {m[0].to_py()}")

    ParserState.reset()
    ##################################################################################
    G.DEBUG = False
    expr = fw("expr")
    term = fw("term")
    more_terms = fw("more_terms")
    factor = fw("factor")
    mult = fw("mult")
    div = fw("div")
    minus = fw("minus")
    plus = fw("plus")
    group = fw("group")

    expr = term + more_terms
    more_terms = mult | div | plus | minus | nothing
    mult = MUL + cut + term + more_terms
    div = DIV + term + more_terms
    plus = PLUS + term + more_terms
    minus = MINUS + term + more_terms
    term = NUMBER | IDENTIFIER | group
    group = LPAREN + expr + RPAREN

    @method(expr)
    def to_py(self):
        return " ".join(res.to_py() for res in self.nodes)

    @method(plus)
    def to_py(self):
        return "+ " + " ".join(res.to_py() for res in self.nodes)

    @method(minus)
    def to_py(self):
        return "- " + " ".join(res.to_py() for res in self.nodes)

    @method(mult)
    def to_py(self):
        return "* " + " ".join(res.to_py() for res in self.nodes)

    @method(div)
    def to_py(self):
        return "/ " + " ".join(res.to_py() for res in self.nodes)

    @method(group)
    def to_py(self):
        return f"({self.node.to_py()})"

    m = expr.parse(Input("(7+4)/5*4-5"))
    assert m, "arithmetic expr parse failed"
    print(f"expr: {m[0].to_py()}")

    ParserState.reset()
    ##############################################################################
    primitive_type = fw("primitive_type")
    map_type = fw("map_type")
    container_type = fw("container_type")
    list_type = fw("list_type")
    tuple_type = fw("tuple_type")
    multi_tuple_type = fw("multi_tuple_type")
    empty_tuple_type = fw("empty_tuple_type")
    singleton_tuple_type = fw("singleton_tuple_type")
    set_type = fw("set_type")
    iterable_type = fw("iterable_type")
    array_type = fw("array_type")
    sequence_type = fw("sequence_type")
    optional_type = fw("optional_type")
    maybe_optional_type = fw("maybe_optional_type")
    pointer_type = fw("pointer_type")
    maybe_pointer_type = fw("maybe_pointer_type")
    basic_type = fw("basic_type")
    union_type = fw("union_type")
    maybe_union_type = fw("maybe_union_type")

    none_type = literal("None")
    any_type = literal("ANY")
    boolean_type = literal("bool")

    @method(boolean_type)
    def to_py(self):
        return "BOOLEAN"

    integer_type = literal("int")

    @method(integer_type)
    def to_py(self):
        return "INTEGER"

    string_type = literal("str")

    @method(string_type)
    def to_py(self):
        return "STRING"

    bytes_type = literal("bytes")
    float_type = literal("float")

    @method(float_type)
    def to_py(self):
        return "FLOAT"

    type_alias = IDENTIFIER
    range_type = (INTEGER | type_alias) + DOUBLEDOT + (INTEGER | type_alias)
    type_decl = union_type | maybe_optional_type
    union_type = maybe_optional_type + (VBAR + maybe_optional_type)[1:]
    maybe_optional_type = optional_type | maybe_pointer_type
    optional_type = maybe_pointer_type + QUESTION_MARK
    maybe_pointer_type = pointer_type | basic_type
    pointer_type = STAR + basic_type
    basic_type = primitive_type | container_type | map_type | type_alias
    primitive_type = (
        none_type | float_type | boolean_type | string_type | integer_type | range_type
    )
    map_type = LBRACKET + basic_type + RBRACKET + basic_type
    container_type = (
        array_type | sequence_type | set_type | iterable_type | string_type | bytes_type
    )
    sequence_type = list_type | tuple_type
    list_type = LBRACKET + RBRACKET + basic_type
    tuple_type = empty_tuple_type | singleton_tuple_type | multi_tuple_type
    multi_tuple_type = LPAREN + basic_type + (COMMA + basic_type)[1:] + RPAREN
    singleton_tuple_type = LPAREN + basic_type + COMMA + RPAREN
    empty_tuple_type = LPAREN + COMMA + RPAREN
    set_type = LBRACE + RBRACE + basic_type
    array_type = LBRACKET + INTEGER + RBRACKET + basic_type
    iterable_type = LBRACKET + RBRACKET + RARROW + basic_type

    @method(range_type)
    def to_py(self):
        return f"range from {self.nodes[0].to_py()} to {self.nodes[1].to_py()}"

    @method(union_type)
    def to_py(self):
        return f"{self.nodes[0].to_py() + ' | ' + ' | '.join(n.node.to_py() for n in self.nodes[1].nodes)}"

    @method(optional_type)
    def to_py(self):
        return f"Optional[{self.node.to_py()}]"

    @method(pointer_type)
    def to_py(self):
        return "access to " + f"{self.node.to_py()}"

    @method(list_type)
    def to_py(self):
        return f"list[{self.node.to_py()}]"

    @method(set_type)
    def to_py(self):
        return f"set[{self.node.to_py()}]"

    @method(array_type)
    def to_py(self):
        return f"[array size {self.nodes[0].to_py()} of {self.nodes[1].to_py()}]"

    @method(map_type)
    def to_py(self):
        if type(self.nodes[0]).__name__ == "multi_tuple_type":
            return f"Callable[{self.nodes[0].to_py()},{self.nodes[1].to_py()}]".replace(
                "tuple", "", 1
            )
        elif type(self.nodes[0]).__name__ in (
            "singleton_tuple_type",
            "empty_tuple_type",
        ):
            return f"Callable[{self.nodes[0].to_py()},{self.nodes[1].to_py()}]".replace(
                ",]", "]"
            ).replace("tuple", "", 1)
        else:
            return f"dict[{self.nodes[0].to_py()},{self.nodes[1].to_py()}]"

    @method(multi_tuple_type)
    def to_py(self):
        output = f"tuple[{self.nodes[0].to_py()}, "
        output += f"{', '.join(n.node.to_py() for n in self.nodes[1].nodes)}]"
        return output

    @method(empty_tuple_type)
    def to_py(self):
        return f"tuple[]"

    @method(singleton_tuple_type)
    def to_py(self):
        return f"tuple[{self.node.to_py()},]"

    ##################################################### test type declarations ######################
    ast, rest = type_decl.parse(Input("[1 .. 10]str"))
    print(f"array range: {ast.to_py()}")

    ast, rest = range_type.parse(Input("a .. 77"))
    print(f"range: {ast.to_py()}")

    ast, rest = basic_type.parse(Input("[5]str"))
    print(f"array: {ast.to_py()}")

    ast, rest = basic_type.parse(Input("[]str"))
    print(f"list: {ast.to_py()}")

    ast, rest = basic_type.parse(Input("(int,str,float, []int)"))
    print(f"tuple: {ast.to_py()}")

    ast, rest = basic_type.parse(Input("[int][float]str"))
    print(f"map: {ast.to_py()}")

    m = pointer_type.parse(Input("*int"))
    assert ast, "pointer_type *int failed"
    m = pointer_type.parse(Input("*[int][float]str"))
    assert ast, "pointer_type *[int][float]str failed"
    ast, rest = maybe_pointer_type.parse(Input("*[int][float]str"))
    print(f"pointer: {ast.to_py()}")

    m = optional_type.parse(Input("str?"))
    assert ast, "optional_type str? failed"
    ast, rest = maybe_optional_type.parse(Input("*[int][float]str?"))
    print(f"optional pointer: {ast.to_py()}")

    m = union_type.parse(Input("str|float|mytype"))
    assert ast, "union_type failed"
    m = type_decl.parse(Input("str|*[]float?|mytype"))
    assert ast, "complex union type_decl failed"

    G.DEBUG = False
    ast, rest = type_decl.parse(Input("[(int,int)]bool"))
    print(f"callable(2): {ast.to_py()}")
    ast, rest = type_decl.parse(Input("[(int,)]bool"))
    print(f"callable(1): {ast.to_py()}")
    ast, rest = type_decl.parse(Input("[(,)]bool"))
    print(f"callable(0): {ast.to_py()}")

    # --- Negative lookahead test ---
    ParserState.reset()

    # ~COMMA succeeds (without consuming) when next token is NOT a comma
    not_comma = ~COMMA + shift

    m = not_comma.parse(Input("abc"))
    assert m, "negative lookahead: should succeed on non-comma"
    print(f"negative lookahead (success): parsed non-comma token")

    # ~COMMA should fail when next token IS a comma
    ParserState.reset()
    m_fail = (~COMMA).parse(Input(", x"))
    assert not m_fail, "negative lookahead: should have failed on comma"
    print("negative lookahead (fail case): correctly rejected comma")

    # --- SymbolTable tests ---
    print()
    print("--- SymbolTable tests ---")

    st = SymbolTable()
    assert st.depth() == 0, "empty stack depth"
    assert st.lookup("x") is None, "lookup on empty stack"
    assert st.pop_scope() is None, "pop empty stack"

    # Push module scope, add symbols
    st.push_scope("module")
    assert st.depth() == 1
    st.add("x", "int", "var")
    st.add("main", None, "func")
    assert st.lookup("x") == {"type": "int", "kind": "var"}
    assert st.lookup("main") == {"type": None, "kind": "func"}
    assert st.lookup("y") is None
    print("  push_scope / add / lookup: ok")

    # Push function scope, shadow x
    st.push_scope("main")
    assert st.depth() == 2
    st.add("x", "str", "param")
    st.add("y", "float", "var")
    assert st.lookup("x") == {"type": "str", "kind": "param"}, "inner x shadows outer"
    assert st.lookup("y") == {"type": "float", "kind": "var"}
    assert st.lookup("main") == {"type": None, "kind": "func"}, "outer func visible"
    print("  nested scope / shadowing: ok")

    # Pop function scope
    scope = st.pop_scope()
    assert scope["name"] == "main"
    assert "x" in scope["symbols"] and "y" in scope["symbols"]
    assert st.depth() == 1
    assert st.lookup("x") == {"type": "int", "kind": "var"}, "x restored after pop"
    assert st.lookup("y") is None, "y gone after pop"
    print("  pop_scope / restore: ok")

    # current_scope
    assert st.current_scope()["name"] == "module"
    st.pop_scope()
    assert st.current_scope() is None
    print("  current_scope: ok")

    # add with no scope is a no-op
    st.add("z", "int")
    assert st.lookup("z") is None
    print("  add with no scope: ok")

    # ParserState integration
    ParserState.reset()
    assert ParserState.symbol_table.depth() == 1
    ParserState.symbol_table.push_scope("test")
    ParserState.symbol_table.add("a", "bool")
    assert ParserState.symbol_table.lookup("a")["type"] == "bool"
    ParserState.reset()
    assert ParserState.symbol_table.depth() == 1
    assert ParserState.symbol_table.lookup("a") is None
    print("  ParserState integration: ok")

    # --- Left-recursive grammar tests ---
    print()
    print("--- Left-recursive grammar tests ---")

    # 1. Direct left recursion (arithmetic expressions with precedence & left-associativity)
    ParserState.reset()
    lr_expr = fw("lr_expr")
    lr_term = fw("lr_term")
    lr_factor = fw("lr_factor")

    lr_add = lr_expr + PLUS + lr_term
    lr_sub = lr_expr + MINUS + lr_term
    lr_mul = lr_term + MUL + lr_factor
    lr_div = lr_term + DIV + lr_factor

    lr_expr = lr_add | lr_sub | lr_term
    lr_term = lr_mul | lr_div | lr_factor
    lr_group = LPAREN + lr_expr + RPAREN
    lr_factor = NUMBER | lr_group

    @method(lr_add)
    def to_py(self):
        return f"({self.nodes[0].to_py()} + {self.nodes[1].to_py()})"

    @method(lr_sub)
    def to_py(self):
        return f"({self.nodes[0].to_py()} - {self.nodes[1].to_py()})"

    @method(lr_mul)
    def to_py(self):
        return f"({self.nodes[0].to_py()} * {self.nodes[1].to_py()})"

    @method(lr_div)
    def to_py(self):
        return f"({self.nodes[0].to_py()} / {self.nodes[1].to_py()})"

    @method(lr_group)
    def to_py(self):
        return f"[{self.node.to_py()}]"

    @method(lr_expr)
    def to_py(self):
        return self.node.to_py()

    @method(lr_term)
    def to_py(self):
        return self.node.to_py()

    @method(lr_factor)
    def to_py(self):
        return self.node.to_py()

    # Left-associative subtraction: 10 - 4 - 2 should parse as ((10 - 4) - 2)
    m = lr_expr.parse(Input("10 - 4 - 2"))
    assert m, "direct left-recursion: 10 - 4 - 2 failed"
    assert m[0].to_py() == "((10 - 4) - 2)", f"wrong tree: {m[0].to_py()}"
    print(f"  direct left recursion (left associativity): {m[0].to_py()} ok")

    # Full arithmetic with precedence & parentheses
    m = lr_expr.parse(Input("(1 + 2) * (3 - 4) / 2"))
    assert m, "direct left-recursion: arithmetic with parens failed"
    assert m[0].to_py() == "(([(1 + 2)] * [(3 - 4)]) / 2)"
    print(f"  direct left recursion (precedence & grouping): {m[0].to_py()} ok")

    # 2. Indirect left recursion: A -> B -> A
    ParserState.reset()
    ind_A = fw("ind_A")
    ind_B = fw("ind_B")

    ind_A = (ind_B + PLUS + NUMBER) | NUMBER
    ind_B = ind_A

    m = ind_A.parse(Input("1 + 2 + 3"))
    assert m, "indirect left-recursion failed"
    print("  indirect left recursion (A -> B -> A): ok")

    # 3. Grammar declarative class (zero forward declarations, inner-class AST methods)
    ParserState.reset()

    class AutoGrammar(Grammar):
        auto_expr = (auto_expr + PLUS + auto_term) | auto_term
        auto_term = (auto_term + MUL + NUMBER) | NUMBER

        class auto_expr:
            def to_py(self):
                return f"({self.nodes[0].to_py()} + {self.nodes[1].to_py()})"

        class auto_term:
            def to_py(self):
                return f"({self.nodes[0].to_py()} * {self.nodes[1].to_py()})"

    m = auto_expr.parse(Input("1 + 2 * 3"))
    assert m, "Grammar class parse failed"
    assert m[0].to_py() == "(1 + (2 * 3))"
    print("  Grammar class (zero forward declarations, inner-class AST methods): ok")

    # 4. A rule name gives a node's part of that rule; the name with _list gives all of them.
    ParserState.reset()

    class NamedGrammar(Grammar):
        named_sum = named_num + (PLUS + named_num)[:] + named_times[0:1]
        named_num = NUMBER
        named_times = MUL + NUMBER

    m = named_sum.parse(Input("1 + 2 + 3"))
    assert m, "named parts parse failed"
    assert [n.to_py() for n in m[0].named_num_list] == ["1", "2", "3"]
    assert m[0].named_num.to_py() == "1"
    assert m[0].named_times is None and m[0].named_times_list == []
    print("  named parts (node.rule, node.rule_list): ok")

    # 5. A named sequence on the left of + stays its own node.
    ParserState.reset()

    class HeadGrammar(Grammar):
        head_sum = NUMBER + PLUS + NUMBER
        head_line = head_sum + MUL + NUMBER

    m = head_line.parse(Input("1 + 2 * 3"))
    assert m and m[0].head_sum is not None, "a named sequence was merged into the next one"
    print("  named sequence on the left of +: ok")

    print("\nAll tests passed.")
