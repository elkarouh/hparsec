# BASIC interpreter

A small BASIC interpreter built on hparsec, as a proof of concept. It sits beside
`tools/zsh_linter/` and uses only the library, so it is a second example of a grammar
with evaluation attached to its nodes.

## What it supports

- `LET name = expression` assigns a global variable.
- `PRINT expr, expr, ...` prints the values separated by spaces. A bare `PRINT` prints an empty line.
- `DEF FN name(params) = expression` defines a single-line function.
- `FN name(args)` calls a function. A function body sees its parameters and the global variables.
- Numbers, `"strings"`, `+ - * /`, unary minus, parentheses, and `'` comments.
- Keywords are case-insensitive. Variable and function names are case-sensitive.

Not supported: line numbers, `GOTO`, `IF`, loops, arrays, and recursion through `FN`.

## Run it

```sh
python3 tools/basic_interpreter/basic_interpreter.py tools/basic_interpreter/examples/functions.bas
python3 tools/basic_interpreter/basic_interpreter.py     # runs the built-in self-tests
make basic                                                # both, from the repository root
```

From Python:

```python
from basic_interpreter import run
run('DEF FN SQ(X) = X * X\nPRINT FN SQ(4) + 1\n')   # ['17']
```

## How it is built

- `tokenize` splits the source into `NUMBER`, `STRING`, `IDENT`, `KEYWORD`, `OP` and
  `NEWLINE` tokens. Comments are dropped.
- `BasicGrammar` is written as EBNF. Each rule is a class whose docstring holds its rule.
  Statements have `run(env)`; expressions have `evaluate(env)`. Each method handles its
  own node and calls the methods of its parts, so nothing walks the tree generically.
- `Environment` keeps the variables, the functions and the output in hparsec's
  `SymbolTable`. A function call pushes a frame with its parameters, on top of the
  globals, and the frame is popped when the call returns.
- Errors are raised as `BasicError`. A syntax error names the token where the parse
  stopped, which is often the start of the statement rather than the exact spot.
