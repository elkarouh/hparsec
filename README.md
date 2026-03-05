# hparsec – Parser Combinator Library for Python

A lightweight **parser combinator** framework for building recursive descent parsers in Python. Inspired by [dabeaz/three-problems](https://github.com/dabeaz/blog/blob/main/2023/three-problems.md).

## Features

- **Combinator syntax**: Build parsers using intuitive Python operators
- **Recursive descent**: Supports left-factored grammars naturally
- **Python 3 parsing**: Includes a complete Python 3.14 parser implementation
- **AST generation**: Attach semantic actions via the `@method` decorator
- **Tokenizer integration**: Built-in support for Python's `tokenize` module

## Quick Example

```python
from hek_parsec import *

# Define a key-value parser: identifier = number ;
keyvalue = IDENTIFIER + EQUAL + NUMBER + SEMICOLON

# Add a semantic action
@method(keyvalue)
def to_py(self):
    return f"{self.nodes[0].to_py()}:{self.nodes[1].to_py()}"

# Parse input
ast, rest = keyvalue.parse(Input("x=789;"))
print(ast.to_py())  # Output: x:789
```

## Combinator Operators

| Operator | Meaning |
|----------|---------|
| `A + B` | Sequence – match A then B |
| `A \| B` | Choice – match A or B |
| `A[1:]` | One or more repetitions |
| `A[:]` | Zero or more repetitions |
| `A[n:m]` | Between n and m repetitions |
| `A * n` | Exactly n repetitions |

## Project Structure

- `hek_parsec.py` – Core parser combinator framework
- `hek_tokenize.py` – Tokenizer utilities
- `hek_py3_parser.py` – Python 3 compound statement parser
- `hek_py3_expr.py` – Python expression parser
- `hek_py3_stmt.py` – Python simple statement parser
- `hek_py_declarations.py` – Type annotation parsing
- `hek_py2py.py` – Python-to-Python transpilation utilities

## Usage

```python
from hek_py3_parser import parse_compound

ast = parse_compound("if x:\n    pass\n")
print(ast.to_py())
```

## Requirements

- Python 3.10+
- No external dependencies (uses stdlib `tokenize`)

## License

MIT
