# Lisp interpreter

A Lisp interpreter built on hparsec, equivalent to Peter Norvig's `lispy.py`. It sits
beside `tools/basic_interpreter/` and `tools/zsh_linter/`.

## What it supports

- Numbers, symbols and lists, with `;` comments.
- Special forms: `quote`, `if` (with or without an else branch), `define`, `set!`,
  `lambda`, and `begin`.
- Procedure calls, including closures: a lambda keeps the scopes that were open when
  it was created.
- The standard procedures of `lispy.py`: `+ - * /`, `> < >= <= =`, `abs`, `max`, `min`,
  `round`, `not`, `append`, `apply`, `car`, `cdr`, `cons`, `length`, `list`, `list?`,
  `map`, `null?`, `number?`, `procedure?`, `symbol?`, `eq?`, `equal?`.

Truthiness follows `lispy.py`: `if` takes Python truth values, so `0` and `[]` are false.
Booleans print as `#t` and `#f`.

Not supported: `'x` as shorthand for `(quote x)`, strings, `let`, `cond`, and
`(define (f x) ...)` shorthand. Recursion depth is limited to 80 nested calls.

## Run it

```sh
python3 tools/lisp_interpreter/lisp_interpreter.py                        # a REPL
python3 tools/lisp_interpreter/lisp_interpreter.py tools/lisp_interpreter/examples/closures.scm
python3 tools/lisp_interpreter/lisp_interpreter.py --test                 # self-tests
make lisp                                                                 # both, from the repository root
```

From Python:

```python
from lisp_interpreter import run
run("(begin (define fact (lambda (n) (if (<= n 1) 1 (* n (fact (- n 1)))))) (fact 10))")  # 3628800
```

## How it is built

- `tokenize` splits the source into `(`, `)`, numbers and symbols.
- `LispGrammar` is written as EBNF. Each rule is a class whose docstring holds its rule.
  `datum()` gives the Python value of a piece of source, and `evaluate(env)` gives the
  value of an expression.
- A list checks its first element for a special form, and otherwise evaluates its
  elements and applies the result. The special forms are methods of the list node.
- The environment is hparsec's `SymbolTable`. The stack of scopes is the environment
  chain. `define` adds to the innermost scope, `set!` updates the innermost scope that
  has the name, and a call pushes a frame with its arguments on top of the procedure's
  captured scopes.
