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

Quick example (the token names and Input() come from ady_helpers/ady_tokens.py):
    keyvalue = IDENTIFIER + EQUAL + NUMBER + SEMICOLON
    keyvalues = keyvalue[1:]

    @method(keyvalue)
    def to_py(self):
        return f"{self.nodes[0].to_py()}:{self.nodes[1].to_py()}"

    ast, rest = keyvalue.parse(Input("x=789;"))
    print(ast.to_py())  # x:789

IMPORTANT — sequence flattening
-------------------------------
`A + B` where A is already a Sequence_Parser produces a NEW Sequence_Parser
whose `.parsers` is `A.parsers + [B]` — i.e. A's children are hoisted into
the parent, and the intermediate `A` node does NOT appear in the resulting
AST. Likewise `A | B` flattens when A is a Choice_Parser.

Consequence: if you need an intermediate rule to remain visible in the AST,
wrap it with `as_node()` before composing it into a parent. The wrapper
retains the complete result as one child and therefore prevents sequence or
choice flattening from erasing that grammar boundary.

todo: replace tokenizer with own lexer
"""

import sys
import re
import inspect
from functools import wraps
from typing import Callable


##################################################################################################


def calling_module_namespace():
    """Return the namespace (globals dict) of the first calling module outside this one.

    Used by forward() and method() to resolve parser names in the caller's scope.
    """
    if hasattr(sys, "_getframe"):
        f = sys._getframe(1)
        while f:
            f_name = f.f_globals.get("__name__")
            if f_name != __name__:
                return f.f_globals
            f = f.f_back
        return globals()

    import inspect
    for stk in inspect.stack():
        mod = inspect.getmodule(stk[0])
        if mod is None:
            import __main__

            return vars(__main__)
        if mod.__name__ != __name__:  # we found the first calling module
            return vars(mod)
    return globals()


def _attach_method(target_parser, method_name: str, func: Callable):
    """Attach method_name=func to target_parser.

    FIX: only distribute to Sequence_Parser alternatives when the target
    really IS a Choice_Parser.  Distributing from a Sequence_Parser to its
    children was silently overwriting methods on inner parsers.
    """
    if getattr(target_parser, "__name__", None) == "Choice_Parser":
        targets = [
            p for p in target_parser.parsers
            if getattr(p, "__name__", None) == "Sequence_Parser"
        ]
        if not targets:
            targets = [target_parser]
    else:
        targets = [target_parser]

    for target in targets:
        setattr(target, method_name, func)


def method(KLASS: type) -> Callable:
    """Decorator to add a method to a class.

    When KLASS is a Choice_Parser (e.g. the result of ``A | B``), a
    Choice_Parser is never directly instantiated as an AST node — the
    matching sub-parser's instance always is.  So the decorator
    automatically distributes the method to every Sequence_Parser
    alternative inside KLASS.parsers.

    This lets you keep the grammar natural::

        additive = (additive + add_op + multiplicative) | multiplicative

        @method(additive)          # attaches to the Sequence_Parser binary case
        def evaluate(self):        # self.nodes == [lhs, op, rhs]
            ...

    instead of needing a named intermediate ``_additive_binary``.
    If no Sequence_Parser alternatives are found the method falls back
    to being set on KLASS itself.
    """

    def wrapper(f):
        _attach_method(KLASS, f.__name__, f)

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

    def resolve_type(self, name):
        """Return the type string for a symbol name, following type aliases.

        For a variable/param, returns its declared type.
        For a type alias (kind='type'), follows the chain transitively.
        Returns the name itself if not found.
        """
        seen = set()
        current = name
        while current and current not in seen:
            sym = self.lookup(current)
            if sym is None:
                break
            seen.add(current)
            if sym.get("kind") == "type":
                current = sym.get("type", current)
            else:
                return sym.get("type", current)
        return current


##################################################################################################
class ParserState:
    """Global parser configuration state.

    Attributes:
        DEBUG: When True, print parser construction and matching details.
        memos: Reserved for packrat parsing at the ParserState level.
            NOTE: per-parse memoization currently lives on TokenStream.memos.
        symbol_table: SymbolTable instance for the current parse.

    The state is process-global. Use ``ParserState.scoped()`` around nested
    translations to preserve the outer unit's state.
    """

    DEBUG = False
    memos: dict = {}
    symbol_table = SymbolTable()
    symbol_table.push_scope("<module>")
    proc_param_types: dict = {}

    @classmethod
    def reset(cls):
        """Clear core parser state between parses."""
        cls.memos.clear()
        cls.symbol_table = SymbolTable()
        cls.symbol_table.push_scope("<module>")

    @classmethod
    def _data_attrs(cls):
        """Names of the plain data attributes that make up the state."""
        return [
            k for k, v in vars(cls).items()
            if not k.startswith("__")
            and not callable(v)
            and not isinstance(v, (classmethod, staticmethod, property))
        ]

    @classmethod
    def snapshot(cls):
        """Capture the current state (core + backend fields).

        Containers are copied one level deep so in-place mutations inside a
        nested translation don't leak into the captured state.
        """
        import copy
        snap = {}
        for k in cls._data_attrs():
            v = vars(cls)[k]
            if isinstance(v, (dict, set, list)):
                v = copy.copy(v)
            snap[k] = v
        return snap

    @classmethod
    def restore(cls, snap):
        """Restore a snapshot(): drop fields added since, put back old values."""
        for k in cls._data_attrs():
            if k not in snap:
                delattr(cls, k)
        for k, v in snap.items():
            setattr(cls, k, v)

    @classmethod
    def scoped(cls):
        """Context manager: save the state on entry, restore it on exit.

        Makes nested translations re-entrant — the inner unit may reset()
        and mutate freely without corrupting the outer unit's state.
        """
        from contextlib import contextmanager

        @contextmanager
        def _scope():
            snap = cls.snapshot()
            try:
                yield cls
            finally:
                cls.restore(snap)

        return _scope()


G = ParserState  # backward compat alias


class LR:
    """Descriptor for an in-progress left-recursive rule invocation."""

    __slots__ = ("seed", "rule", "head", "next")

    def __init__(self, seed, rule, head=None, next=None):
        self.seed = seed
        self.rule = rule
        self.head = head
        self.next = next


class Head:
    """Head of a left-recursive cycle, tracking involved and evaluation sets."""

    __slots__ = ("rule", "involved_set", "eval_set")

    def __init__(self, rule):
        self.rule = rule
        self.involved_set = set()
        self.eval_set = set()


class MemoEntry:
    """Packrat memoization entry holding parse result and end position."""

    __slots__ = ("ans", "pos")

    def __init__(self, ans, pos):
        self.ans = ans
        self.pos = pos


class TokenStream:
    """Built-in token stream cursor for sequences of tokens or characters.

    Accepts any sequence (list, tuple, str) or custom iterable of tokens.
    Provides cursor navigation, position tracking, and packrat memo/LR storage.
    """

    def __init__(self, tokens):
        if isinstance(tokens, (list, tuple)):
            self.tokens = list(tokens)
        elif isinstance(tokens, str):
            self.tokens = list(tokens)
        elif hasattr(tokens, "__iter__"):
            self.tokens = list(tokens)
        else:
            self.tokens = [tokens]
        self.pos = 0
        self.farthest = 0  # highest token index any parser has examined
        self.memos = {}
        self.heads = {}
        self.lrstack = None
        self.failed_token = None

    def __iter__(self):
        return iter(self.tokens)

    def __len__(self):
        return len(self.tokens)

    def __getitem__(self, idx):
        return self.tokens[idx]

    def get_new_token(self):
        if self.pos > self.farthest:
            self.farthest = self.pos
        if self.pos >= len(self.tokens):
            return None
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def mark(self):
        return self.pos

    def reset(self, pos):
        self.pos = pos

    def set_failed_token(self, value):
        self.failed_token = value

    def format_error(self):
        if self.failed_token is not None:
            return f"Failed at token {self.failed_token!r} (position {self.pos})"
        if 0 <= self.pos < len(self.tokens):
            tok = self.tokens[self.pos]
            tok_str = getattr(tok, "string", str(tok))
            return f"Unexpected token {tok_str!r} at position {self.pos}"
        return f"Unexpected end of input at position {self.pos}"


def _setup_lr(rule, lr, token_stream):
    if lr.head is None:
        lr.head = Head(rule)
    s = token_stream.lrstack
    while s is not None and s.head != lr.head:
        s.head = lr.head
        lr.head.involved_set.add(s.rule)
        s = s.next


def _recall(cls, token_stream, rule, pos, parse_function, args):
    m = token_stream.memos.get((rule, pos))
    h = token_stream.heads.get(pos)
    if h is None:
        return m

    if m is None and rule != h.rule and rule not in h.involved_set:
        return MemoEntry(False, pos)

    if rule in h.eval_set:
        h.eval_set.remove(rule)
        token_stream.reset(pos)
        ans = parse_function(cls, token_stream, *args)
        end_pos = token_stream.pos if ans else pos
        m.ans = ans
        m.pos = end_pos
        return m

    return m


def _apply_memo_rule(rule, pos, m, token_stream):
    if isinstance(m.ans, LR):
        _setup_lr(rule, m.ans, token_stream)
        if m.ans.seed:
            token_stream.pos = m.pos
            return m.ans.seed
        token_stream.reset(pos)
        return False
    if m.ans:
        token_stream.pos = m.pos
        return m.ans
    token_stream.reset(pos)
    return False


def _lr_answer(cls, token_stream, rule, pos, m, h, parse_function, args):
    if h.rule != rule:
        m.ans = m.ans.seed if isinstance(m.ans, LR) else m.ans
        if not m.ans:
            token_stream.reset(pos)
        return m.ans

    m.ans = m.ans.seed if isinstance(m.ans, LR) else m.ans
    if not m.ans:
        token_stream.reset(pos)
        return False

    return _grow_lr(cls, token_stream, rule, pos, m, h, parse_function, args)


def _grow_lr(cls, token_stream, rule, pos, m, h, parse_function, args):
    token_stream.heads[pos] = h
    while True:
        token_stream.reset(pos)
        h.eval_set = set(h.involved_set)
        ans = parse_function(cls, token_stream, *args)
        end_pos = token_stream.pos if ans else pos

        if not ans or end_pos <= m.pos:
            break

        m.ans = ans
        m.pos = end_pos

    token_stream.heads.pop(pos, None)
    token_stream.pos = m.pos
    return m.ans


def apply_parsing_context(parse_function):
    """Decorator that wraps a parse method with packrat memoization and left-recursion support.

    Implements Warth et al.'s algorithm for direct and indirect left recursion
    in packrat parsers. Caches parse results keyed by (rule, position) and
    iteratively grows left-recursive rules until a fixed point is reached.
    """

    @wraps(parse_function)
    def wrapper(cls, token_stream, *args):
        if not hasattr(token_stream, "get_new_token"):
            token_stream = TokenStream(token_stream)
        elif not hasattr(token_stream, "heads"):
            token_stream.heads = {}
        if not hasattr(token_stream, "lrstack"):
            token_stream.lrstack = None

        norm_args = (0,) if (len(args) == 0 and parse_function.__code__.co_argcount > 2) else args
        rule = (id(cls), norm_args)
        pos = token_stream.pos

        m = _recall(cls, token_stream, rule, pos, parse_function, norm_args)
        if m is not None:
            return _apply_memo_rule(rule, pos, m, token_stream)

        lr = LR(seed=False, rule=rule, head=None, next=token_stream.lrstack)
        token_stream.lrstack = lr
        m = MemoEntry(ans=lr, pos=pos)
        token_stream.memos[(rule, pos)] = m

        try:
            ans = parse_function(cls, token_stream, *norm_args)
        finally:
            token_stream.lrstack = lr.next

        end_pos = token_stream.pos if ans else pos
        m.pos = end_pos

        if lr.head is not None:
            lr.seed = ans
            return _lr_answer(cls, token_stream, rule, pos, m, lr.head, parse_function, norm_args)
        else:
            m.ans = ans
            if not ans:
                token_stream.reset(pos)
            return ans

    return classmethod(wrapper)


###################################################################################################
class Cut(Exception):
    """Raised by fail/cut to abort parsing with an error message."""

    def __init__(self, token_stream):
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
    _default_class = None
    _rule_names = set()

    def __getattr__(self, name):
        """Delegate missing attributes to the registered default class.

        A rule name gives the node's part of that rule, or None: `node.if_condition`.
        The rule name with `_list` gives all of them: `node.elif_branch_list`.
        """
        dc = Parser._default_class
        if dc is not None:
            attr = getattr(dc, name, None)
            if attr is not None:
                if callable(attr):
                    return attr.__get__(self, type(self))
                return attr
        rule = name[:-len("_list")] if name.endswith("_list") else name
        if rule in Parser._rule_names:
            found = [p for p in parts(self) if type(p).__name__ == rule]
            return found if rule != name else next(iter(found), None)
        raise AttributeError(
            f"{type(self).__name__!r} object has no attribute {name!r}"
        )
        
    def __init__(self, nodes) -> None:
        if type(nodes) is list:
            if nodes:
                self.node = nodes[0]
                self.nodes = nodes
            else:
                self.node = None
                self.nodes = []
        else:
            self.node = nodes
            self.nodes = [nodes]
        if G.DEBUG:
            print(self.__class__.__name__, "Constructor->", self.nodes)

    def to_py(self):
        if hasattr(self, "node") and self.node is not self:
            if hasattr(self.node, "to_py"):
                return self.node.to_py()
            return str(self.node)
        return str(getattr(self, "node", ""))

    def evaluate(self):
        if hasattr(self, "node") and self.node is not self:
            if hasattr(self.node, "evaluate"):
                return self.node.evaluate()
            return self.node
        return getattr(self, "node", None)

def forward(parser_name: str) -> type[Parser]:
    """Create a lazy forward reference for recursive grammars."""
    # Capture the module namespace at definition time, not parse time
    g = calling_module_namespace()

    class Lazy_Parser(Parser):
        @classmethod
        def parse(cls, token_stream, *args):
            ns = getattr(cls, "namespace", g)
            parser = ns[parser_name]
            return parser.parse(token_stream, *args)

    Lazy_Parser.name = parser_name
    Lazy_Parser.namespace = g
    Lazy_Parser.__name__ = parser_name
    return Lazy_Parser


fw = forward  # alias


class GrammarNamespace(dict):
    """Namespace mapping for Grammar class body execution.

    Intercepts attribute lookups during class definition: if an attribute is not
    yet defined in the class body or in outer globals/builtins, it automatically
    generates a lazy forward reference (Parser) pointing to that attribute name.

    Also intercepts inner classes named after existing rules (e.g. ``class additive:``)
    to augment the rule with methods directly.
    """

    def __init__(self, outer_globals):
        super().__init__()
        self.outer_globals = outer_globals
        self.augmented_methods = []

    def __missing__(self, key):
        if key in self.outer_globals:
            return self.outer_globals[key]
        import builtins
        if hasattr(builtins, key):
            return getattr(builtins, key)
        lazy = forward(key)
        lazy.namespace = self.outer_globals
        self[key] = lazy
        return lazy

    def __setitem__(self, key, value):
        if isinstance(value, type) and (key in self or key in self.outer_globals) and not issubclass(value, Parser):
            prev = self[key] if key in self else self.outer_globals[key]
            for attr_name, attr_val in value.__dict__.items():
                if not attr_name.startswith("_") and inspect.isfunction(attr_val):
                    self.augmented_methods.append((prev, attr_name, attr_val))
            return
        # Name a rule's sequence as soon as it is defined: `a + b` merges an anonymous
        # sequence on its left into the new one, and a named rule must stay a node.
        if (isinstance(value, type) and issubclass(value, Parser) and key.isidentifier()
                and not key.startswith("_") and value.__name__ == "Sequence_Parser"):
            value.__name__ = value.__qualname__ = key
        super().__setitem__(key, value)


class GrammarMeta(type):
    """Metaclass that enables declarative grammars without explicit forward declarations.

    Also supports supplying AST methods directly inside the class without ``@method``:
    - As flat methods named ``<action>_<rule>`` (e.g. ``def evaluate_additive(self):``)
      or ``<rule>_<action>`` (e.g. ``def additive_evaluate(self):``).
    - As inner classes named after rules (e.g. ``class additive: def evaluate(self): ...``).
    """

    @classmethod
    def __prepare__(metacls, name, bases, **kwds):
        return GrammarNamespace(calling_module_namespace())

    def __new__(metacls, name, bases, namespace, **kwds):
        all_rules = {}
        if isinstance(namespace, GrammarNamespace):
            g = namespace.outer_globals
            all_rules.update({k: v for k, v in g.items() if hasattr(v, "parse")})
        all_rules.update({k: v for k, v in namespace.items() if hasattr(v, "parse")})

        # 1. Attach inner-class augmented methods
        if isinstance(namespace, GrammarNamespace):
            for target_parser, mname, mfunc in namespace.augmented_methods:
                _attach_method(target_parser, mname, mfunc)

        # 2. Process flat methods like evaluate_additive, to_py_additive, etc.
        sorted_rule_names = sorted(all_rules.keys(), key=len, reverse=True)
        methods_to_remove = set()

        for k, v in list(namespace.items()):
            if inspect.isfunction(v) and not k.startswith("_"):
                for rname in sorted_rule_names:
                    if k.endswith("_" + rname):
                        action = k[:-len(rname)-1]
                        rule = all_rules[rname]
                        _attach_method(rule, action, v)
                        methods_to_remove.add(k)
                        break
                    elif k.startswith(rname + "_"):
                        action = k[len(rname)+1:]
                        rule = all_rules[rname]
                        _attach_method(rule, action, v)
                        methods_to_remove.add(k)
                        break

        # Each rule is its own parser class; name it after the rule so a parse
        # node reports its rule through type(node).__name__.
        for rname, rule in all_rules.items():
            if isinstance(rule, type) and rname.isidentifier() and not rname.startswith("_"):
                rule.__name__ = rname
                rule.__qualname__ = rname
                Parser._rule_names.add(rname)

        cls = super().__new__(metacls, name, bases, dict(namespace))

        # Auto-register a `__default__` class defined in the grammar body as
        # the fallback class for all Parser instances. Rule authors never
        # reference it: `node.anything()` works whether the method is defined
        # on the rule or on `__default__`.
        if isinstance(namespace, GrammarNamespace):
            dc = namespace.get("__default__")
            if isinstance(dc, type) and not hasattr(dc, "parse"):
                Parser._default_class = dc
                
        # 3. Export rules to the caller's outer globals
        if isinstance(namespace, GrammarNamespace):
            g = namespace.outer_globals
            for k, v in namespace.items():
                if not k.startswith("_") and k not in methods_to_remove:
                    g[k] = v
        return cls


class Grammar(metaclass=GrammarMeta):
    """Base class for declarative grammars.

    Rules defined inside a subclass of Grammar do not require any `fw()` or `forward()`
    declarations — undefined rule references are resolved automatically.

    Methods can also be supplied directly inside the class:
      - ``def evaluate_<rule>(self): ...``
      - or inner classes ``class <rule>: def evaluate(self): ...``
    """
    pass


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


def as_node(parser):
    """Wrap the result of *parser* in a distinct AST node.

    Unlike a one-alternative choice, this creates an explicit AST boundary:
    the wrapped parser's complete result is retained as the wrapper's single
    child.  This works uniformly for choices, sequences, repetitions,
    terminals, and other parser expressions.

    The wrapper has its own parsing context, so it participates in the normal
    packrat memoization and left-recursion machinery.  The wrapped parser is
    still responsible for recognition; a failed match remains a failure and
    the parsing-context decorator restores the wrapper's starting position.
    """

    class As_Node(Parser):
        @apply_parsing_context
        def parse(cls, token_stream):
            result = parser.parse(token_stream)
            if not result:
                return False

            ast, token_stream = result
            return cls([ast]), token_stream

    return As_Node

def children(node):
    """Return the non-null direct AST children of *node*.

    Parser nodes normally expose ``nodes``; the singular ``node`` attribute
    is retained as a compatibility fallback for node-like objects.
    """
    if node is None:
        return []

    nodes = getattr(node, "nodes", None)
    if isinstance(nodes, list):
        return [child for child in nodes if child is not None]

    child = getattr(node, "node", None)
    return [child] if child is not None and child is not node else []


_ANONYMOUS_NODES = ("Sequence_Parser", "Several_Times", "As_Node")


def parts(node):
    """Yield the parts of a node: its children, looking through anonymous combinator nodes.

    as_node() marks a node boundary on purpose, so the node it wraps is a part even
    when that node is an anonymous sequence.
    """
    for child in children(node):
        kind = type(child).__name__ if isinstance(child, Parser) else None
        if kind == "As_Node":
            yield from children(child)
        elif kind in _ANONYMOUS_NODES:
            yield from parts(child)
        else:
            yield child


def token_of(node):
    """Return the first leaf token wrapped by *node*, or ``None``.

    An identity guard prevents malformed or cyclic node structures from
    causing an infinite loop.
    """
    current = node
    seen = set()

    while current is not None and id(current) not in seen:
        seen.add(id(current))

        if isinstance(current, str):
            return current

        if not isinstance(current, Parser):
            return current

        kids = children(current)
        if kids:
            current = kids[0]
        else:
            return None

    return None

def walk(node, visitor):
    """Call *visitor* on *node* and on every AST node below it, depth first.

    Each node is passed to *visitor* before its children, so a parent is seen
    before the nodes it contains. If the visitor returns ``False`` for a node,
    the children of that node are skipped. A node reached twice is visited once,
    which also keeps a cyclic structure from looping.
    """
    seen = set()

    def _walk(current):
        if current is None or id(current) in seen:
            return
        seen.add(id(current))
        if visitor(current) is False:
            return
        for child in children(current):
            _walk(child)

    _walk(node)


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
            if hasattr(p, "name"):
                # forward() already captured the caller's namespace. Reuse it
                # instead of walking the Python stack on every parse invocation.
                g = getattr(p, "namespace", None)
                if g is None:
                    g = calling_module_namespace()
                if p.name in g:
                    p = g[p.name]
            elif getattr(p, "__name__", None) == "Lazy_Parser":
                g = getattr(p, "namespace", None)
                if g is None:
                    g = calling_module_namespace()
                p = g[p.name]
            if (
                p.__name__ == "Choice_Parser"
            ):  # a choice parser, we have to implement backtracking
                for i in range(
                    len(p.parsers)
                ):  # look at the alternatives in the choice parser
                    saved_pos = token_stream.mark()
                    if not (m := p.parse(token_stream, i)):
                        token_stream.reset(saved_pos)
                        continue  # backtrack
                    ast, token_stream = m
                    if not parsers[1:]:
                        return [ast], token_stream
                    if not (m := cls.parse_sequence(token_stream, parsers[1:])):
                        token_stream.reset(saved_pos)
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
    """Repeat parser between min_times and max_times. None means unbounded.

    Zero-width-success guard: if the inner parser succeeds but does not advance
    the stream (e.g. `nothing[:]`), stop to avoid an infinite loop.

    NOTE: the position must be captured BEFORE calling parser.parse. Capturing
    it after the parse (as an earlier revision did) makes every iteration look
    zero-width and terminates the loop after a single match.
    """

    class Several_Times(Parser):
        @apply_parsing_context
        def parse(cls, token_stream):
            nodes = []
            while True:
                before = token_stream.pos
                m = parser.parse(token_stream)
                if not m:
                    break
                ast, token_stream = m
                nodes.append(ast)
                if max_times is not None and len(nodes) == max_times:
                    break
                if token_stream.pos == before:
                    # zero-width success — stop to avoid an infinite loop
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
def expect(ty, val):
    """Match a token with the given type and exact string value."""
    parser = fmap(
        lambda tok: getattr(tok, "string", tok),
        filt(lambda tok: getattr(tok, "type", None) == ty and getattr(tok, "string", tok) == val, shift),
    )
    # parser.__name__=f'expect_{val}'
    return parser


def expect_type(ty):
    """Match any token of the given type."""
    parser = fmap(lambda tok: getattr(tok, "string", tok), filt(lambda tok: getattr(tok, "type", None) == ty, shift))
    # parser.__name__=f'expect_{ty}'
    return parser


def expect_type_node(ty):
    """Match any token of the given type and return the node itself (not string).
    
    Used for RichNL and other enriched token types that carry additional data.
    """
    parser = filt(lambda tok: getattr(tok, "type", None) == ty, shift, name=str(ty))
    return parser


def expect_node(ty, val):
    """Match token by type and value, preserving the full TokenInfo as node."""
    return filt(lambda tok: getattr(tok, "type", None) == ty and getattr(tok, "string", tok) == val, shift, name=repr(val))


def literal(mylit: str) -> type[Parser]:
    """Match a token with the exact string value (e.g. a keyword)."""
    parser = fmap(
        lambda tok: getattr(tok, "string", tok),
        filt(lambda tok: getattr(tok, "string", tok) == mylit, shift, name=repr(mylit)),
    )
    parser.__name__ = f"Literal_{mylit}"
    Parser._rule_names.add(parser.__name__)
    return parser


def expect_re(regex):
    """Match a token whose string matches the given regex."""
    parser = fmap(
        lambda tok: getattr(tok, "string", tok),
        filt(lambda tok: bool(re.match(regex, getattr(tok, "string", str(tok)))), shift,
             name='NUMBER' if 'eE' in regex else 'STRING' if (len(regex) > 0 and regex[0] == '(') else f'/{regex}/')
    )
    return parser


class TerminalsNamespace(dict):
    """Namespace mapping for Terminals class body execution.

    Enforces the convention:
      - UPPERCASE attributes: automatically wrapped in ignore() (ignored terminals).
        Strings assigned to UPPERCASE are converted to ignore(literal(s)).
      - lowercase attributes: kept visible in the AST (strings converted to literal(s)).
    """

    def __setitem__(self, key, value):
        if key.isupper() and not key.startswith('_'):
            if isinstance(value, str):
                value = ignore(literal(value))
            elif hasattr(value, 'parse') and getattr(value, '__name__', '') != 'ignore_parser':
                value = ignore(value)
        elif not key.startswith('_') and isinstance(value, str):
            value = literal(value)
        super().__setitem__(key, value)


class TerminalsMeta(type):
    """Metaclass that enables declarative terminal definitions."""

    @classmethod
    def __prepare__(metacls, name, bases, **kwds):
        return TerminalsNamespace()

    def __new__(metacls, name, bases, namespace, **kwds):
        cls = super().__new__(metacls, name, bases, dict(namespace))
        # Export all non-private terminals to the caller's module globals
        g = calling_module_namespace()
        for k, v in namespace.items():
            if not k.startswith('_'):
                g[k] = v
        return cls


class Terminals(metaclass=TerminalsMeta):
    """Base class for declarative terminal definitions.

    Convention:
      - UPPERCASE names are automatically ignored (never appear in the AST).
        Strings are automatically converted to ignore(literal(s)).
      - lowercase names remain visible in the AST.
      - All defined terminals are automatically exported to module globals.
    """
    pass



###############################################################################
# Public API
__all__ = [
    # Core classes
    "Parser",
    "ParserState",
    "TokenStream",
    "G",
    "children",
    "token_of",
    "parts",
    "walk",
    "Cut",
    "ParserMeta",
    "Grammar",
    "GrammarMeta",
    "Terminals",
    "TerminalsMeta",
    # Parsing context & Left Recursion
    "apply_parsing_context",
    "LR",
    "Head",
    "MemoEntry",
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
    "as_node",
    "sequence",
    "several_times_parser",
    "ignore",
    "negative_lookahead",
    # Matching
    "expect",
    "expect_type",
    "expect_type_node",
    "expect_re",
    "literal",
    # Utilities
    "method",
    "calling_module_namespace",
]

#############################################################
########################################################################################################################
########################################################################################################################
##########################################
if __name__ == "__main__":
    # --- as_node() AST-boundary tests ---
    ParserState.reset()

    choice_node = as_node(shift | shift)
    choice_match = choice_node.parse(TokenStream(["choice"]))
    assert choice_match, "as_node(choice): parse failed"
    choice_ast, choice_stream = choice_match
    assert type(choice_ast) is choice_node, "as_node(choice): wrapper node missing"
    assert len(choice_ast.nodes) == 1, "as_node(choice): expected exactly one child"
    assert choice_ast.node is not choice_ast, "as_node(choice): child boundary missing"
    assert choice_stream.pos == 1

    # A failed first alternative must backtrack before the second is tried.
    rejecting_tail = filt(lambda _token: False, shift)
    backtracking_node = as_node((shift + rejecting_tail) | shift)
    backtracking_stream = TokenStream(["fallback"])
    backtracking_match = backtracking_node.parse(backtracking_stream)
    assert backtracking_match and backtracking_stream.pos == 1, (
        "as_node(choice): wrapped choice did not preserve backtracking"
    )

    sequence_node = as_node(shift + shift)
    sequence_match = sequence_node.parse(TokenStream(["left", "right"]))
    assert sequence_match, "as_node(sequence): parse failed"
    sequence_ast, _ = sequence_match
    assert type(sequence_ast) is sequence_node
    assert type(sequence_ast.node).__name__ == "Sequence_Parser"
    assert len(sequence_ast.node.nodes) == 2, "as_node(sequence): sequence structure lost"

    nested_node = as_node(as_node(shift))
    nested_match = nested_node.parse(TokenStream(["nested"]))
    assert nested_match, "as_node(nested): parse failed"
    nested_ast, _ = nested_match
    assert type(nested_ast) is nested_node
    assert type(nested_ast.node).__name__ == "As_Node"

    repeated_node = as_node(shift[:])
    repeated_match = repeated_node.parse(TokenStream(["one", "two"]))
    assert repeated_match, "as_node(repetition): parse failed"
    repeated_ast, repeated_stream = repeated_match
    assert type(repeated_ast) is repeated_node
    assert type(repeated_ast.node).__name__ == "Several_Times"
    assert len(repeated_ast.node.nodes) == 2 and repeated_stream.pos == 2

    failed_stream = TokenStream([])
    assert not as_node(shift).parse(failed_stream), "as_node(failure): expected failure"
    assert failed_stream.pos == 0, "as_node(failure): failure consumed input"

    class AsNodeMethodGrammar(Grammar):
        wrapped_rule = as_node(shift | shift)

        class wrapped_rule:
            def marker(self):
                return "method attached to wrapper"

    method_match = wrapped_rule.parse(TokenStream(["method"]))
    assert method_match, "as_node(grammar method): parse failed"
    assert method_match[0].marker() == "method attached to wrapper"

    memo_stream = TokenStream(["memo"])
    memo_parser = as_node(shift)
    memo_match = memo_parser.parse(memo_stream)
    assert memo_match, "as_node(memo): initial parse failed"
    memo_stream.reset(0)
    memo_match_again = memo_parser.parse(memo_stream)
    assert memo_match_again and memo_stream.pos == 1, "as_node(memo): memoized parse failed"
    assert any(key[0][0] == id(memo_parser) for key in memo_stream.memos), "as_node(memo): wrapper not memoized"

    # The wrapper itself can be a left-recursive grammar rule.
    ParserState.reset()
    as_node_lr_expr = fw("as_node_lr_expr")
    plus_token = filt(lambda token: token == "+", shift)
    as_node_lr_expr = as_node((as_node_lr_expr + plus_token + shift) | shift)
    lr_stream = TokenStream(["a", "+", "b", "+", "c"])
    lr_match = as_node_lr_expr.parse(lr_stream)
    assert lr_match and lr_stream.pos == 5, "as_node(left recursion): failed to grow parse"
    print("as_node(): AST boundaries, backtracking, grammar methods, memoization, and left recursion OK")

    print("\nAll tests passed.")
