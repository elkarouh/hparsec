#!/usr/bin/env python3
"""Parser combinator framework for building recursive descent parsers.

Inspired by https://github.com/dabeaz/blog/blob/main/2023/three-problems.md

Parsers are composed using Python operators:
    A + B       sequence (match A then B)
    A | B       choice (match A or B)
    A[1:]       one or more repetitions
    A[:]        zero or more repetitions
    A[n:m]      between n and m repetitions
    A * n       exactly n repetitions

Each parser's parse() method returns (ast, token_stream) on success, or False
on failure. Use the @method decorator to add output methods (e.g. to_py) to
parser classes.

Quick example:
    keyvalue = IDENTIFIER + EQUAL + NUMBER + SEMICOLON
    keyvalues = keyvalue[1:]

    @method(keyvalue)
    def to_py(self):
        return f"{self.nodes[0].to_py()}:{self.nodes[1].to_py()}"

    ast, rest = keyvalue.parse(Input("x=789;"))
    print(ast.to_py())  # x:789

todo: replace tokenizer with own lexer
"""

import inspect
import re
import tokenize as tkn
from functools import wraps
from typing import Callable

from hek_tokenize import Tokenizer

##################################################################################################


def calling_module_namespace():
    """Return the namespace (globals dict) of the first calling module outside this one.

    Used by forward() and method() to resolve parser names in the caller's scope.
    """
    for stk in inspect.stack():
        mod = inspect.getmodule(stk[0])
        if mod is None:
            import __main__

            return vars(__main__)
        if mod.__name__ != __name__:  # we found the first calling module
            return vars(mod)
    return globals()


def method(KLASS: type) -> Callable:
    """Decorator to add a method to a class."""

    def wrapper(f):
        setattr(KLASS, f.__name__, f)

    # give a name to the assigned class !!!
    g = calling_module_namespace()
    for name in g:
        if g[name] is KLASS:
            if G.DEBUG:
                print(f"assigning {name} to {KLASS.__name__}")
            KLASS.__name__ = name
            break
    return wrapper


##################################################################################################
class SymbolTable:
    """A stack-based symbol table for tracking variable names and types across scopes.

    Each scope is a dict mapping names to {"type": type_str, "kind": kind_str}.
    kind is one of: "var", "param", "func", "class".
    """

    def __init__(self):
        self.stack = []  # list of {"name": scope_name, "symbols": {name: {type, kind}}}

    def push_scope(self, name="<unknown>"):
        """Push a new scope onto the stack."""
        self.stack.append({"name": name, "symbols": {}})

    def pop_scope(self):
        """Pop and return the current scope."""
        if self.stack:
            return self.stack.pop()
        return None

    def add(self, name, type_info=None, kind="var"):
        """Add a symbol to the current scope."""
        if self.stack:
            self.stack[-1]["symbols"][name] = {"type": type_info, "kind": kind}

    def lookup(self, name):
        """Look up a symbol from innermost scope outward. Returns dict or None."""
        for scope in reversed(self.stack):
            if name in scope["symbols"]:
                return scope["symbols"][name]
        return None

    def current_scope(self):
        """Return the current (innermost) scope dict, or None."""
        return self.stack[-1] if self.stack else None

    def depth(self):
        """Return the number of scopes on the stack."""
        return len(self.stack)


##################################################################################################
class ParserState:
    """Global parser configuration state.

    Attributes:
        DEBUG: When True, print parser construction and matching details.
        memos: Memoization cache (currently unused, reserved for packrat parsing).
    """

    DEBUG = False
    memos: dict = {}
    symbol_table = SymbolTable()
    nim_imports: set = set()
    nim_pragmas: set = set()       # top-level {.experimental: ...} pragmas
    tick_types: dict = {}  # {TypeName: {First: val, Last: val, members: [...]}}
    class_field_types: dict = {}   # {ClassName: {field_name: nim_type}}
    proc_param_types: dict = {}    # {proc_name: [nim_type, ...]} positional param types
    tuple_field_order: dict = {}   # {TupleName: [field, ...]} for positional tuple constructors
    object_field_order: dict = {}  # {ObjectName: [field, ...]} for positional object constructors

    @classmethod
    def reset(cls):
        """Clear memoization state between parses."""
        cls.memos.clear()
        cls.symbol_table = SymbolTable()
        cls.nim_imports = set()
        cls.nim_pragmas = set()
        cls.tick_types = {}
        cls.class_field_types = {}
        cls.proc_param_types = {}
        cls.tuple_field_order = {}
        cls.object_field_order = {}


G = ParserState  # backward compat alias


def apply_parsing_context(parse_function):
    """Decorator that wraps a parse method with packrat memoization and backtracking.

    Caches parse results keyed by (parser_id, position, *args) so each parser
    is called at most once per position, guaranteeing linear-time parsing.
    On failure, resets the position so other alternatives can be tried.
    """

    @wraps(parse_function)
    def wrapper(cls, token_stream, *args):
        key = (
            id(cls),
            token_stream.pos,
        ) + args  # args includes start_index for Choice_Parser

        if key in token_stream.memos:
            result, end_pos = token_stream.memos[key]
            if result:
                token_stream.pos = end_pos
            return result

        pos_ante = token_stream.mark()
        if m := parse_function(cls, token_stream, *args):
            token_stream.memos[key] = (m, token_stream.pos)
            return m
        token_stream.reset(pos_ante)
        token_stream.memos[key] = (False, pos_ante)
        return False

    return classmethod(wrapper)


###################################################################################################
class Cut(Exception):
    """Raised by fail/cut to abort parsing with an error message."""

    def __init__(self, token_stream: Tokenizer):
        super().__init__(token_stream.format_error())


class ParserMeta(type):
    """Metaclass enabling operator syntax for composing parsers.

    Operators:
        A + B   -> sequence(A, B)
        A | B   -> choice(A, B)
        A[n:m]  -> several_times_parser(A, n, m)
        A * n   -> several_times_parser(A, n, n)
        ~A      -> negative_lookahead(A)
    """

    def __add__(cls, other_klass):
        other_klass = literal(other_klass) if type(other_klass) is str else other_klass
        klass = sequence(cls, other_klass)
        if cls.__name__ == "Sequence_Parser":
            klass.parsers = cls.parsers + [other_klass]
        else:
            klass.parsers = [cls, other_klass]
        return klass

    def __radd__(cls, other_klass):
        other_klass = literal(other_klass) if type(other_klass) is str else other_klass
        klass = sequence(other_klass, cls)
        if other_klass.__name__ == "Sequence_Parser":
            klass.parsers = other_klass.parsers + [cls]
        else:
            klass.parsers = [other_klass, cls]
        return klass

    def __or__(cls, other_klass):
        other_klass = literal(other_klass) if type(other_klass) is str else other_klass
        klass = choice(cls, other_klass)
        if cls.__name__ == "Choice_Parser":
            klass.parsers = cls.parsers + [other_klass]
        else:
            klass.parsers = [cls, other_klass]
        return klass

    def __ror__(cls, other_klass):
        other_klass = literal(other_klass) if type(other_klass) is str else other_klass
        klass = choice(other_klass, cls)
        if other_klass.__name__ == "Choice_Parser":
            klass.parsers = other_klass.parsers + [cls]
        else:
            klass.parsers = [other_klass, cls]
        return klass

    def __getitem__(cls, subscript):
        if G.DEBUG:
            print(f"{subscript=}")
        if isinstance(subscript, slice):
            return several_times_parser(cls, subscript.start, subscript.stop)
        elif subscript == 0:
            return several_times_parser(cls, None, None)
        else:
            raise Exception(f"Not allowed: {subscript}")

    def __mul__(cls, other):
        return several_times_parser(cls, other, other)

    def __invert__(cls):
        return negative_lookahead(cls)


class Parser(metaclass=ParserMeta):
    """Base class for all parsers.

    Attributes:
        node:  The first AST node (shortcut for nodes[0]).
        nodes: List of all AST nodes produced by this parser.
    """

    def __init__(self, nodes) -> None:
        if type(nodes) is list:
            if nodes:
                self.node = nodes[0]
                self.nodes = nodes
            else:
                self.nodes = []
        else:
            self.node = nodes
            self.nodes = [nodes]
        if G.DEBUG:
            print(self.__class__.__name__, "Constructor->", self.nodes)

    def to_nim(self, prec=None):
        """Default to_nim() fallback: delegates to to_py() for expression nodes."""
        if not hasattr(self, 'to_py'):
            return ''
        return self.to_py(prec)


def forward(parser_name: str) -> type[Parser]:
    """Create a lazy forward reference for recursive grammars."""
    # Capture the module namespace at definition time, not parse time
    g = calling_module_namespace()

    class Lazy_Parser(Parser):
        @apply_parsing_context
        def parse(cls, token_stream):
            parser = g[parser_name]
            return parser.parse(token_stream)

    Lazy_Parser.name = parser_name
    Lazy_Parser.__name__ = parser_name
    return Lazy_Parser


fw = forward  # alias


class shift(Parser):
    """Consume and return the next token from the stream."""

    @apply_parsing_context
    def parse(cls, token_stream):
        if token := token_stream.get_new_token():
            return cls(token), token_stream
        return False


class nothing(Parser):
    """Always succeeds without consuming input. Returns None."""

    @apply_parsing_context
    def parse(cls, token_stream):
        return None, token_stream


class fail(Parser):
    """Always fails by raising Cut. Used with cut = nothing | fail."""

    @apply_parsing_context
    def parse(cls, token_stream):
        raise Cut(token_stream)


def negative_lookahead(p):
    """Negative lookahead: succeeds (without consuming input) only if parser p fails.

    Use via the ~ operator: ~parser
    Returns None as the AST node on success (no input consumed).
    """

    class NegativeLookahead(Parser):
        @apply_parsing_context
        def parse(cls, token_stream):
            pos = token_stream.mark()
            try:
                m = p.parse(token_stream)
            except Cut:
                m = False
            token_stream.reset(pos)
            if m:
                return False
            return None, token_stream

    return NegativeLookahead


def filt(predicate, p, name=None):
    """Filter parser: succeeds only if inner parser p matches AND predicate(node) is true.

    If name is provided, records it as an expected token on failure (for error reporting).
    """
    class Filter(Parser):
        @apply_parsing_context
        def parse(cls, token_stream):
            m = p.parse(token_stream)
            if m and predicate(m[0].node):
                # Create a new AST node instead of mutating the inner parser's result
                return cls(m[0].nodes), m[1]
            else:
                if name:
                    token_stream.set_failed_token(name)
                return False

    return Filter


def fmap(func, p):
    """Map parser: applies func to the parsed node, transforming the AST result."""

    class Fmap(Parser):
        @apply_parsing_context
        def parse(cls, token_stream):
            m = p.parse(token_stream)
            if not m:
                return False
            ast, token_stream = m
            # Create a new AST node with the mapped value instead of mutating
            new_ast = cls([func(ast.node)])
            return new_ast, token_stream

    return Fmap


def choice(p1, p2):
    """Try parsers in order, returning the first successful match."""

    class Choice_Parser(Parser):
        @apply_parsing_context
        def parse(
            cls, token_stream, start_index=0
        ):  # the start_index is necessary for backtracking
            for p in cls.parsers[start_index:]:
                if m := p.parse(token_stream):
                    return m
            return False

    return Choice_Parser


def sequence(p1, p2):
    """Match parsers in order, collecting all results. Supports backtracking."""

    class Sequence_Parser(Parser):
        @classmethod
        def post_process(cls, combined_asts):
            # Filter out None values returned by the ignore parser
            asts = [ast for ast in combined_asts if ast is not None]
            if len(asts) == 1:
                asts = asts[0]
            return cls(asts)

        @classmethod
        def parse_sequence(cls, token_stream, parsers):
            """This function was made recursive to allow backtracking"""
            p = parsers[0]
            if p.__name__ == "Lazy_Parser":
                g = calling_module_namespace()
                p = g[p.name]
            if (
                p.__name__ == "Choice_Parser"
            ):  # a choice parser, we have to implement backtracking
                for i in range(
                    len(p.parsers)
                ):  # look at the alternatives in the choice parser
                    if not (m := p.parse(token_stream, i)):
                        continue  # backtrack
                    ast, token_stream = m
                    if not parsers[1:]:
                        return [ast], token_stream
                    if not (m := cls.parse_sequence(token_stream, parsers[1:])):
                        continue  # backtrack
                    asts, token_stream = m
                    return [ast] + asts, token_stream
                return False  # this will trigger backtrack in the caller
            else:
                if not (m := p.parse(token_stream)):
                    return False
                ast, token_stream = m
                if not parsers[1:]:
                    return [ast], token_stream
                if not (m := cls.parse_sequence(token_stream, parsers[1:])):
                    return False  # will trigger backtrack in the caller
                asts, token_stream = m
                return [ast] + asts, token_stream

        @apply_parsing_context
        def parse(cls, token_stream):
            if res := cls.parse_sequence(token_stream, cls.parsers):
                combined_asts, token_stream = res
                return cls.post_process(combined_asts), token_stream
            return False

    return Sequence_Parser


def several_times_parser(parser, min_times, max_times=None):
    """Repeat parser between min_times and max_times. None means unbounded."""

    class Several_Times(Parser):
        @apply_parsing_context
        def parse(cls, token_stream):
            nodes = []
            while m := parser.parse(token_stream):
                ast, token_stream = m
                nodes.append(ast)
                if max_times is not None and len(nodes) == max_times:
                    break
            if min_times is None:
                if len(nodes) == 0:
                    return None, token_stream
            else:
                if len(nodes) < min_times:
                    return False
            return cls(nodes), token_stream

    return Several_Times


def ignore(parser):
    """Ignore parser: matches but returns None, so it won't appear in sequence results."""

    class ignore_parser(Parser):
        @apply_parsing_context
        def parse(cls, token_stream):
            if m := parser.parse(token_stream):
                return None, m[1]
            return False

    return ignore_parser


cut = nothing | fail


#############################################################################
def Input(string: str) -> Tokenizer:
    """Create a token stream from a source string, ready for parsing."""
    gen = Tokenizer(string)
    next(gen)  # skip the encoding token
    return gen


def expect(ty, val):
    """Match a token with the given type and exact string value."""
    parser = fmap(
        lambda tok: tok.string,
        filt(lambda tok: tok.type == ty and tok.string == val, shift),
    )
    # parser.__name__=f'expect_{val}'
    return parser


def expect_type(ty):
    """Match any token of the given type."""
    parser = fmap(lambda tok: tok.string, filt(lambda tok: tok.type == ty, shift))
    # parser.__name__=f'expect_{ty}'
    return parser


def expect_type_node(ty):
    """Match any token of the given type and return the node itself (not string).
    
    Used for RichNL and other enriched token types that carry additional data.
    """
    parser = filt(lambda tok: tok.type == ty, shift, name=tkn.tok_name.get(ty, str(ty)))
    return parser


def expect_node(ty, val):
    """Match token by type and value, preserving the full TokenInfo as node."""
    return filt(lambda tok: tok.type == ty and tok.string == val, shift, name=repr(val))


def expect_nl_or_richnl():
    """Match NL token or RichNL object and return it.
    
    RichNL.type == tkn.NL, so this matches both.
    """
    parser = filt(lambda tok: tok.type == tkn.NL, shift, name='NL')
    return parser


def literal(mylit: str) -> type[Parser]:
    """Match a NAME token with the exact string value (e.g. a keyword)."""
    parser = fmap(
        lambda tok: tok.string,
        filt(lambda tok: tok.type == tkn.NAME and tok.string == mylit, shift, name=repr(mylit)),
    )
    parser.__name__ = f"Literal_{mylit}"
    return parser


def expect_re(regex):
    """Match a token whose string matches the given regex."""
    parser = fmap(
        lambda tok: tok.string, filt(lambda tok: re.match(regex, tok.string), shift, name='NUMBER' if 'eE' in regex else 'STRING' if regex[0] == '(' else f'/{regex}/')
    )
    return parser


###############################################################################
# Token definition helpers
def _op(symbol: str):
    """Create an ignored operator token parser."""
    return ignore(expect(tkn.OP, symbol))


def _visible_op(symbol: str):
    """Create a visible (non-ignored) operator token parser."""
    return expect(tkn.OP, symbol)


# Delimiters
LPAREN = _op("(")
RPAREN = _op(")")
LBRACE = _op("{")
RBRACE = _op("}")
LBRACKET = _op("[")
RBRACKET = _op("]")
COMMA = _op(",")
SEMICOLON = _op(";")
VBAR = _op("|")
COLON = _op(":")
EQUAL = _op("=")

# Arithmetic operators
PLUS = _op("+")
MINUS = _op("-")
MUL = STAR = _op("*")
SSTAR = _visible_op("*")  # no ignore !!!
DIV = SLASH = _op("/")
PERCENT = _op("%")
DOUBLESTAR = _op("**")
DOUBLESLASH = _op("//")

# Bitwise operators
AMPER = _op("&")
TILDE = _op("~")
CIRCUMFLEX = _op("^")
LEFTSHIFT = _op("<<")
RIGHTSHIFT = _op(">>")

# Comparison operators
LESS = _op("<")
GREATER = _op(">")
EQEQUAL = _op("==")
NOTEQUAL = _op("!=")
LESSEQUAL = _op("<=")
GREATEREQUAL = _op(">=")

# Assignment operators
PLUSEQUAL = _op("+=")
MINEQUAL = _op("-=")
STAREQUAL = _op("*=")
SLASHEQUAL = _op("/=")
PERCENTEQUAL = _op("%=")
AMPEREQUAL = _op("&=")
VBAREQUAL = _op("|=")
CIRCUMFLEXEQUAL = _op("^=")
LEFTSHIFTEQUAL = _op("<<=")
RIGHTSHIFTEQUAL = _op(">>=")
DOUBLESTAREQUAL = _op("**=")
DOUBLESLASHEQUAL = _op("//=")

# Other operators
DOT = _op(".")
RARROW = _op("->")
ELLIPSIS = _op("...")
COLONEQUAL = _op(":=")
DOUBLEDOT = ignore(DOT + DOT)
IDENTIFIER = filt(str.isidentifier, expect_type(tkn.NAME))
# IDENTIFIER = expect_re(r"\w")
NUMBER = expect_re(tkn.Number)
STRING = expect_re(tkn.String)
INTEGER = filt(str.isdecimal, expect_type(tkn.NUMBER))
FLOAT = expect_re(tkn.Floatnumber)
DECIMAL = expect_re(tkn.Decnumber)
QUESTION_MARK = ignore(expect(tkn.ERRORTOKEN, "?"))


# THE AST methods
@method(IDENTIFIER)
def to_py(self):
    return self.node


@method(NUMBER)
def to_py(self):
    return self.node


@method(INTEGER)
def to_py(self):
    return self.node


@method(STRING)
def to_py(self):
    return self.node


@method(FLOAT)
def to_py(self):
    return self.node


@method(SSTAR)
def to_py(self):
    return self.node


###############################################################################
# Public API
__all__ = [
    # Core classes
    "Parser",
    "ParserState",
    "G",
    "Tokenizer",
    "Cut",
    "ParserMeta",
    # Parsing context
    "apply_parsing_context",
    # Parser constructors
    "forward",
    "fw",
    "shift",
    "nothing",
    "fail",
    "cut",
    "filt",
    "fmap",
    "choice",
    "sequence",
    "several_times_parser",
    "ignore",
    "negative_lookahead",
    # Input and matching
    "Input",
    "expect",
    "expect_type",
    "expect_type_node",
    "expect_nl_or_richnl",
    "expect_re",
    "literal",
    # Utilities
    "method",
    "calling_module_namespace",
    # Delimiter tokens
    "LPAREN",
    "RPAREN",
    "LBRACE",
    "RBRACE",
    "LBRACKET",
    "RBRACKET",
    "COMMA",
    "SEMICOLON",
    "VBAR",
    "COLON",
    "EQUAL",
    # Arithmetic operator tokens
    "PLUS",
    "MINUS",
    "MUL",
    "STAR",
    "SSTAR",
    "DIV",
    "SLASH",
    "PERCENT",
    "DOUBLESTAR",
    "DOUBLESLASH",
    # Bitwise operator tokens
    "AMPER",
    "TILDE",
    "CIRCUMFLEX",
    "LEFTSHIFT",
    "RIGHTSHIFT",
    # Comparison operator tokens
    "LESS",
    "GREATER",
    "EQEQUAL",
    "NOTEQUAL",
    "LESSEQUAL",
    "GREATEREQUAL",
    # Assignment operator tokens
    "PLUSEQUAL",
    "MINEQUAL",
    "STAREQUAL",
    "SLASHEQUAL",
    "PERCENTEQUAL",
    "AMPEREQUAL",
    "VBAREQUAL",
    "CIRCUMFLEXEQUAL",
    "LEFTSHIFTEQUAL",
    "RIGHTSHIFTEQUAL",
    "DOUBLESTAREQUAL",
    "DOUBLESLASHEQUAL",
    # Other operator tokens
    "DOT",
    "RARROW",
    "ELLIPSIS",
    "COLONEQUAL",
    "DOUBLEDOT",
    # Semantic tokens
    "IDENTIFIER",
    "NUMBER",
    "STRING",
    "INTEGER",
    "FLOAT",
    "DECIMAL",
    "QUESTION_MARK",
]

#############################################################
########################################################################################################################
########################################################################################################################
##########################################
if __name__ == "__main__":
    # THE HPYTHON_GRAMMAR
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
    assert ParserState.symbol_table.depth() == 0
    ParserState.symbol_table.push_scope("test")
    ParserState.symbol_table.add("a", "bool")
    assert ParserState.symbol_table.lookup("a")["type"] == "bool"
    ParserState.reset()
    assert ParserState.symbol_table.depth() == 0
    assert ParserState.symbol_table.lookup("a") is None
    print("  ParserState integration: ok")

    print("\nAll tests passed.")
