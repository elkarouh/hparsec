# hparsec — Python Parser Combinator Framework

A lightweight, operator-based parser combinator library for building recursive
descent parsers in Python. Inspired by
[David Beazley's three-problems post](https://github.com/dabeaz/blog/blob/main/2023/three-problems.md).

Parsers are composed using Python operators, producing typed AST nodes that
can be given output methods via the `@method` decorator.

---

## Repository layout

```
hparsec/
├── src/                      # the library (standard library only)
│   └── hparsec.py            # core combinators and parse machinery
├── ady_helpers/              # AdaScript support, kept apart from the library
│   ├── ady_tokens.py         # Input() and the AdaScript token names, with their self-tests
│   ├── ady_tokenizer.py      # Python-tokenize based Tokenizer used by Input()
│   └── hek_helpers.py        # helpers shared by translator backends
├── examples/
│   ├── expression_parser.py      # expression grammar written with repetition
│   └── expression_parser_lr.py   # same grammar written with left recursion
├── tools/
│   ├── basic_interpreter/        # a small BASIC interpreter built on hparsec (proof of concept)
│   ├── lisp_interpreter/         # a Lisp interpreter built on hparsec, equivalent to lispy.py
│   └── zsh_linter/               # zsh-lint: a zsh linter built on hparsec
│       ├── pyproject.toml        # installs the zsh-lint command
│       ├── zsh_tokenizer.py      # hand-written zsh scanner
│       ├── zsh_linter.py         # grammar + lint rules, with inline test cases
│       ├── count_rule.py         # counts one rule's findings across a codebase
│       ├── corpus_test.py        # runs the linter over a corpus of real scripts
│       └── corpus/               # oh-my-zsh and zsh-syntax-highlighting samples
├── benchmarks/
│   ├── benchmark_hparsec.py  # left recursion vs. repetition timing/memory
│   └── profile_hparsec.py    # cProfile of a left-recursive parse
├── tests/
│   └── test_scripts.py       # unittest wrapper around every self-test above
├── pyproject.toml
└── Makefile
```

| Module | Purpose |
|------|---------|
| `hparsec` | Core combinators: `Parser`, `ParserState`, `SymbolTable`, `Grammar`, `Terminals`, `forward`/`fw`, `method`, `filt`, `fmap`, `ignore`, `expect`, `literal`, … |
| `ady_tokens` (in `ady_helpers/`) | `Input()` and the AdaScript token names (`IDENTIFIER`, `NUMBER`, `SEMICOLON`, …); hparsec does not import this module |
| `ady_tokenizer` (in `ady_helpers/`) | `Tokenizer` — wraps Python's `tokenize` module; handles tick-attributes, range operators, bash-isms, f-string interpolation, `RichNL` comment bundling |
| `hek_helpers` (in `ady_helpers/`) | Shared helpers: indentation (`_ind`), `RichNL` extraction, block statement utilities |

The modules keep their flat `hek_*` names, so existing code that does
`from hparsec import ...` keeps working unchanged.

---

## Installation

hparsec has no third-party dependencies. Either install it (editable, so
changes in `src/` are picked up immediately):

```sh
pip install -e .
```

or just put `src/` and `ady_helpers/` on the path:

```sh
export PYTHONPATH=/path/to/hparsec/src:/path/to/hparsec/ady_helpers
```

Python 3.10 or newer is required.

---

## Running the tests

```sh
make test                          # all self-tests, examples, zsh linter and corpus
python -m unittest discover tests  # the same checks as a unittest suite
```

Individual targets: `make selftest` (library modules), `make examples`,
`make zsh`, `make corpus` (`make verbose` for per-file detail), plus
`make bench` and `make profile`. The Makefile sets `PYTHONPATH` to `src` and `ady_helpers` itself, so
no install is needed to run them.

---

## Operators

| Expression | Meaning |
|-----------|---------|
| `A + B` | Sequence — match A then B |
| `A \| B` | Choice — match A or B (first match wins) |
| `A[:]` | Zero or more repetitions |
| `A[1:]` | One or more repetitions |
| `A[n:m]` | Between n and m repetitions |
| `A * n` | Exactly n repetitions |

---

## Quick start

```python
from hparsec import ParserState, method, forward
from ady_tokens import Input, IDENTIFIER, EQUAL, NUMBER, SEMICOLON

# Grammar
keyvalue  = IDENTIFIER + EQUAL + NUMBER + SEMICOLON
keyvalues = keyvalue[1:]

# Output method
@method(keyvalue)
def to_py(self):
    name  = self.nodes[0].to_py()
    value = self.nodes[1].to_py()
    return f"{name} = {value}"

# Parse
ParserState.reset()
stream = Input("x=42; y=7;")
result = keyvalues.parse(stream)
for node in result[0].nodes:
    print(node.to_py())
# x = 42
# y = 7
```

---

## Key concepts

### Reading the tree
Every node has `nodes`, its children, and `node`, the first of them (`nodes[0]`).
An ignored token leaves no child, so `nodes` holds only what a method needs:

| Rule | What the node holds |
|------|---------------------|
| `A + B` | `nodes == [a, b]` |
| `IGNORED + A` | `nodes == [a]` |
| `A \| B` | no node of its own: the result is the node of the alternative that matched, so a choice needs no method |
| `A[1:]` | `nodes == [a, a, ...]` |
| `A[:]` | the same, and no node at all when nothing matched |
| `A + (SEP + A)[:]` | `nodes == [a]` or `[a, more]`; each item of `more.nodes` holds one `A` as `item.node` |

A method is written with `self.nodes[i]`, `self.node` and `for x in self.nodes`:

```python
names = IDENT + (SEP + IDENT)[:]

@method(names)
def to_py(self):
    return [self.node.to_py()] + [item.node.to_py() for more in self.nodes[1:] for item in more.nodes]
```

The self-tests at the end of `src/hparsec.py` show each case, and
`tools/basic_interpreter` and `tools/lisp_interpreter` are written this way.
`as_node()`, `parts()` and `node.<rule>` (below) are optional helpers for large
grammars. A grammar does not need them.

### `method(parser_class)`
Decorator that attaches an output method to a parser class after the grammar
has been defined. Used to add `to_py()`, `to_nim()`, or any backend-specific
rendering without modifying the grammar definition:

```python
@method(if_stmt)
def to_py(self, indent=0):
    ...
```

### `forward(name)` / `fw(name)`
Creates a lazy forward reference for mutually recursive grammar rules.
The name is resolved in the calling module's namespace at parse time:

```python
expr     = forward("expr")
paren    = LPAREN + expr + RPAREN
expr     = NUMBER | paren | ...
```

### Left recursion
`hparsec` natively supports direct and indirect left-recursive grammars using
packrat parsing with fixed-point seed growing (Warth et al.'s algorithm).
Rules can be written with natural left recursion and left-associativity without
triggering recursion limits or requiring manual grammar transformations:

```python
expr = forward("expr")
term = forward("term")

expr = (expr + PLUS + term) | (expr + MINUS + term) | term
term = NUMBER

# "10 - 4 - 2" parses left-associatively as ((10 - 4) - 2)
```

### `Grammar` and `Terminals` (declarative style)
Subclassing `Grammar` lets rules reference each other in any order without
`forward()` declarations, and lets AST methods live next to the rules as
inner classes (or as `<action>_<rule>` / `<rule>_<action>` functions).
`Terminals` turns string attributes into `literal()` parsers; UPPERCASE
names are wrapped in `ignore()` so they never appear in the AST. Both export
their rules to the defining module's globals. Any token list works as input,
so you can bring your own tokenizer (see `examples/expression_parser.py`):

```python
number = expect_type(NUMBER_TOKEN_TYPE)   # whatever your tokenizer emits

class ExpressionTerminals(Terminals):
    LPAREN = "("                      # ignored in the AST
    RPAREN = ")"
    add_op = literal("+") | literal("-")   # kept in the AST

class ExpressionGrammar(Grammar):
    expression = additive
    additive   = (additive + add_op + primary) | primary
    primary    = number | LPAREN + expression + RPAREN

    class additive:
        def evaluate(self):
            ...

ast, stream = expression.parse(tokenize("1 + (2 - 3)"))
```

A node reaches its parts by rule name: `self.if_condition` is its part of rule
`if_condition`, or `None` when the rule matched nothing, and `self.elif_branch_list`
is every such part in source order. Anonymous combinator nodes are looked through,
and a named rule always stays its own node, even on the left of `+`, so a handler
sees the parts its rule names, as an EBNF reading would:

```python
class if_stmt:
    def to_source(self):
        output = "if " + self.if_condition.to_source() + "; then\n"
        for statement in self.inner_statement_list:
            output += statement.to_source() + "\n"
        for branch in self.elif_branch_list:
            output += branch.to_source()
        if self.else_branch:
            output += self.else_branch.to_source()
        return output + "fi"
```

`parts(node)` is the function behind that access. It yields the node's children in source
order, looking through the anonymous combinator nodes, so `parts(node)` gives the same
objects as `node.<rule>` and `node.<rule>_list` do. A node built by `as_node()` marks a
boundary: the node it wraps is one part, even when that node is an anonymous sequence.
`children(node)` is the same list without the looking-through.

### `filt(predicate, parser)`
Wraps a parser so it only succeeds when the matched value satisfies a
predicate (the predicate receives the matched node's value, e.g. the token
string). Used for context-sensitive matching:

```python
keyword = filt(lambda value: value in KEYWORDS, IDENTIFIER)
```

### `fmap(func, parser)`
Transforms the matched result through a function before returning it:

```python
integer = fmap(int, NUMBER)
```

### `ignore(parser)`
Matches the parser but discards the result from the AST (useful for
punctuation that does not need to appear in the tree):

```python
COMMA = ignore(expect(tkn.OP, ","))
```

### `SymbolTable`
A scoped symbol table for tracking declared variables and types during
parsing. Supports `push()`/`pop()` for nested scopes and `resolve_type()`
to follow type aliases transitively.

### `ParserState`
Global parse-time state. Holds `DEBUG`, `memos`, and `symbol_table`.
Backend-specific state (imports, type maps, pragmas, etc.) should be
initialised by the backend after calling `ParserState.reset()` — not stored
here.

**The state is process-global and mutable.** All grammar rules and output
methods read and write it through the class, so only one translation unit
can be "live" at a time. Historically this made nested translations —
transpiling an imported dependency in the middle of transpiling the main
file — silently corrupt the outer unit's state: whatever `reset()` and field
writes the inner unit performed were still in effect when control returned
to the outer unit. Callers worked around it with careful call ordering and
module-level stash variables, which is fragile and easy to get wrong.

`snapshot()` / `restore()` / `scoped()` exist to make nested use safe:

```python
with ParserState.scoped():        # save every data field
    ParserState.reset()
    translate(dependency_source)  # inner unit mutates freely
# outer unit's state is restored here, even on exception
```

- `snapshot()` captures **all** data attributes on the class — core fields
  and any backend fields added since — copying dicts/sets/lists one level
  deep so in-place mutations inside the scope don't leak out.
- `restore(snap)` puts the captured values back and deletes fields that
  were added after the snapshot.
- `scoped()` is the context-manager form of the pair and is exception-safe.

Any code that triggers a translation while another translation is in
progress **must** wrap the inner one in `scoped()`.

Remaining limitations (accepted by design for a single-threaded CLI):
the state is still a global, so translations cannot run concurrently, and
two units cannot be interleaved except through `scoped()` nesting. Making
the state an explicit object passed through every rule and output method
would lift that, at the cost of touching every call site in the grammar
and both backends.

### `RichNL` (in `ady_helpers/ady_tokenizer`)
A newline token enriched with any preceding inline comments. Allows comments
to travel naturally with the parse tree so backends can reproduce them in
generated output.

---

## Tokenizer preprocessing

Before Python's `tokenize` module sees the source, `Tokenizer` applies
several source-level rewrites:

- **Tick attributes**: `Type'First` → `Type__tick__First`
- **Range operators**: `0..10` → `0 .. 10` (avoids float tokenisation)
- **Bash variables**: `$HOME` → `__bash_env_HOME__`, `$1` → `__bash_arg1__`
- **Bash file tests**: `-e file` → `__bash_test_e__ file`

These are reversed by the backend's output methods on the relevant AST nodes.

---

## Design notes

- **No dependencies** beyond the Python standard library.
- **Backend-agnostic**: the library knows nothing about Nim, Python output,
  or any target language. Backends attach output methods via `@method`.
- **Memoization**: `apply_parsing_context` wraps each `parse()` call with
  packrat-style caching keyed by `(parser_id, position)`, giving linear-time
  parsing for unambiguous grammars.
- **Error reporting**: the tokenizer tracks the farthest position reached
  and the set of expected tokens at that point, producing useful parse-error
  messages even on complex failures.

---

## Examples

- `examples/expression_parser.py` and `examples/expression_parser_lr.py`
  define the same small expression language (arithmetic, comparisons,
  `and`/`or`/`not`, function calls) with a custom regex tokenizer. The first
  uses repetition (`A + (op + A)[:]`), the second direct left recursion
  (`A = (A + op + B) | B`). Running either prints its parse and evaluation
  tests.
- `tools/lisp_interpreter/` is a Lisp interpreter equivalent to Peter Norvig's `lispy.py`,
  built on hparsec. Run `make lisp` for its self-tests and example.
- `tools/basic_interpreter/` is a small BASIC interpreter, a proof of concept with
  variables, `PRINT`, and single-line functions (`DEF FN`). Run it on a program with
  `python3 tools/basic_interpreter/basic_interpreter.py tools/basic_interpreter/examples/functions.bas`.
- `tools/zsh_linter/` is `zsh-lint`, a full zsh grammar with lint rules
  attached to AST nodes. Run `make install` from the repository root, which
  puts a `zsh-lint` command in `~/.local/bin`. Then lint scripts directly:

  ```sh
  zsh-lint ~/.zshrc deploy.zsh
  cat script.zsh | zsh-lint -
  ```

  Findings print as `file:line:col: RULE message`. The exit status is 0 when
  clean, 1 when there are findings, and 2 on a parse error. Without arguments
  it runs the inline self-tests. `corpus_test.py` lints every script in
  `corpus/`. `count_rule.py` counts how often one rule fires across a codebase,
  for example to count here-strings: `zsh_linter` has `ZSH008` for them, so
  `python tools/zsh_linter/count_rule.py ZSH008 ~/dotfiles` gives the total.

## Benchmarks

```sh
python benchmarks/benchmark_hparsec.py --sizes 100 1000 5000
python benchmarks/profile_hparsec.py --terms 3000
```

Both load the library from `src/` by default; pass `--source-dir` to compare
against another copy.
