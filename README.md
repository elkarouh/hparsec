# HPython

HPython is a statically-typed superset of Python 3 inspired by Ada and Nim.
It transpiles to both **Python 3** and **Nim**, letting you write concise,
type-safe code in a familiar Python syntax and target either ecosystem.

Every valid Python 3.14 file is also valid HPython. The extra features are
purely additive: left-to-right type annotations, Ada-style enums and variant
records, tick attributes, range expressions, `case/when` pattern matching,
and first-class shell command integration.

```
source.hpy
    │
    ├── python3 TO_PYTHON/py2py.py source.hpy  ──▶  Python 3
    └── python3 TO_NIM/py2nim.py   source.hpy  ──▶  Nim
```

---

## Table of Contents

- [Quick Example](#quick-example)
- [Installation](#installation)
- [Usage](#usage)
- [Type Annotations](#type-annotations)
- [Type Declarations](#type-declarations)
- [Variable Declarations](#variable-declarations)
- [Range Expressions](#range-expressions)
- [Case / When Statements](#casewhen-statements)
- [Tick Attributes](#tick-attributes)
- [Enum Array Literals](#enum-array-literals)
- [Named Tuple Literals](#named-tuple-literals)
- [Functions](#functions)
- [Classes and Inheritance](#classes-and-inheritance)
- [Nim-Only Imports](#nim-only-imports)
- [Print Statement](#print-statement)
- [Shell Statements](#shell-statements)
- [Architecture](#architecture)
- [Known Limitations](#known-limitations)

---

## Quick Example

```python
nimport sequtils

type Stage_T is enum STAGE1, STAGE2, STAGE3

type Choice_T is tuple:
    weight: int
    benefit: int

var items: [Stage_T]Choice_T = [
    STAGE1: (weight: 2, benefit: 65),
    STAGE2: (weight: 3, benefit: 80),
    STAGE3: (weight: 1, benefit: 30),
]

for s in Stage_T'First .. Stage_T'Last:
    let choice: Choice_T = items[s]
    print(f"Stage {s}: weight={choice.weight}, benefit={choice.benefit}")
```

**Python 3 output**

```python
from enum import Enum, auto
from typing import NamedTuple

class Stage_T(Enum):
    STAGE1 = auto()
    STAGE2 = auto()
    STAGE3 = auto()

class Choice_T(NamedTuple):
    weight: int
    benefit: int

items: dict[Stage_T, Choice_T] = {
    Stage_T.STAGE1: Choice_T(weight=2, benefit=65),
    Stage_T.STAGE2: Choice_T(weight=3, benefit=80),
    Stage_T.STAGE3: Choice_T(weight=1, benefit=30),
}

for s in range(Stage_T.STAGE1.value, Stage_T.STAGE3.value + 1):
    choice: Choice_T = items[s]
    print(f"Stage {s}: weight={choice.weight}, benefit={choice.benefit}")
```

**Nim output**

```nim
import sequtils

type Stage_T = enum STAGE1, STAGE2, STAGE3

type Choice_T = tuple
  weight: int
  benefit: int

var items: array[Stage_T, Choice_T] = [
  STAGE1: (weight: 2, benefit: 65),
  STAGE2: (weight: 3, benefit: 80),
  STAGE3: (weight: 1, benefit: 30),
]

for s in Stage_T.STAGE1 .. Stage_T.STAGE3:
  let choice: Choice_T = items[s]
  echo fmt"Stage {s}: weight={choice.weight}, benefit={choice.benefit}"
```

---

## Installation

No package install is required. Clone the repo and run the transpiler scripts
directly with Python 3.10+:

```bash
git clone https://github.com/elkarouh/hparsec
cd hparsec
```

Dependencies: none beyond the Python standard library.

---

## Usage

```bash
# Transpile to Python 3
python3 TO_PYTHON/py2py.py source.hpy

# Transpile to Nim
python3 TO_NIM/py2nim.py source.hpy

# Read from stdin
echo "var x: int = 42" | python3 TO_PYTHON/py2py.py
```

File extension `.hpy` is conventional but not enforced; any `.py` file is
also valid input.

---

## Type Annotations

HPython uses a concise **left-to-right** annotation syntax rather than
Python's `typing` module. Container kinds are expressed as prefixes, so
`[]int` reads naturally as "list of int".

| HPython        | Python                    | Nim                          |
|----------------|---------------------------|------------------------------|
| `[]T`          | `list[T]`                 | `seq[T]`                     |
| `[N]T`         | `tuple[T, ...]`           | `array[N, T]`                |
| `[*]T`         | `Sequence[T]`             | `openArray[T]`               |
| `[E]T`         | `dict[E, T]`              | `array[E, T]` (enum-indexed) |
| `{K}V`         | `dict[K, V]`              | `Table[K, V]`                |
| `{}T`          | `set[T]`                  | `HashSet[T]` or `set[T]`     |
| `?T`           | `T \| None`               | `Option[T]`                  |
| `(T, U)`       | `tuple[T, U]`             | `(T, U)`                     |
| `[(T, U)]R`    | `Callable[[T, U], R]`     | `proc(a0: T, a1: U): R`      |

Types compose freely:

```python
var words:    []str        = ["hello", "world"]
var counts:   {str}int     = {"hello": 1}
var maybe:    ?int         = None
var grid:     [][]float    = [[1.0, 2.0], [3.0, 4.0]]
var callback: [(int,)]bool = my_predicate
```

### Empty collection literals

HPython uses distinct syntax for empty dicts and empty sets, avoiding
Python's ambiguity where `{}` means an empty dict rather than an empty set:

| Literal | Meaning | Python output | Nim output |
|---------|---------|---------------|------------|
| `{:}` | empty dict | `{}` | `initTable[K, V]()` |
| `{}` | empty set | `set()` | `initHashSet[T]()` or `{}` (ordinal) |

```python
var counts:  {str}int = {:}    # empty dict
var visited: {}str    = {}     # empty HashSet
var flags:   {}bool   = {}     # empty ordinal set
```

**Python 3 output:**

```python
counts:  dict[str, int] = {}
visited: set[str]       = set()
flags:   set            = set()
```

**Nim output:**

```nim
import tables, sets
var counts:  Table[string, int] = initTable[string, int]()
var visited: HashSet[string]    = initHashSet[string]()
var flags:   set[bool]          = {}
```

The Nim backend uses the type annotation of the receiving variable to emit
the correct initialiser. For sets, it distinguishes ordinal element types
(`bool`, `char`, `byte`, `int8`, `int16`, `uint8`, `uint16`, and any
user-defined enum registered in the symbol table) from hash-set types:

| Declared type | Nim output |
|---------------|------------|
| `HashSet[T]` (`{}str`, `{}int`, …) | `initHashSet[T]()` (imports `sets`) |
| `set[T]` with ordinal T | `{}` (Nim built-in ordinal set) |
| no annotation | `initHashSet()` fallback |

---

## Type Declarations

### Enums

```python
type Color   is enum RED, GREEN, BLUE
type Digit_T is enum D0, D1, D2, D3, D4, D5, D6, D7, D8, D9
```

Both `is` and `=` are accepted as the assignment keyword.

### Subranges

```python
type SmallInt is 0 .. 255   # inclusive on both ends
type Index    is 0 ..< 10   # exclusive upper bound (0–9)
```

### Named Tuples

```python
type Point is tuple:
    x: float
    y: float
```

Python output: `class Point(NamedTuple): ...`
Nim output: `type Point = tuple`

### Records (Dataclasses)

```python
type Person is record:
    name: str
    age:  int
```

Python output: `@dataclass class Person: ...`
Nim output: `type Person = object`

### Discriminated Records (Variant Types)

Ada/Nim-style variant records where the set of fields depends on an enum
discriminant:

```python
type Shape_Kind is enum Circle, Rectangle

type Shape (Kind : Shape_Kind) is record:
    case Kind is
        when Circle:
            Radius : float
        when Rectangle:
            Width  : float
            Height : float
```

**Nim output** — native variant object:

```nim
type Shape = object
  case Kind: Shape_Kind
  of Circle:
    Radius: float
  of Rectangle:
    Width:  float
    Height: float
```

**Python output** — flattened dataclass with `None` defaults:

```python
@dataclass
class Shape:
    Kind:   Shape_Kind
    Radius: float = None
    Width:  float = None
    Height: float = None
```

---

## Variable Declarations

```python
var   x: int    = 10       # mutable
let   name: str = "hello"  # immutable (Nim: let; Python: annotated assignment)
const MAX: int  = 1000     # compile-time constant
```

Declarations without an initial value are valid:

```python
var result: []int
```

Tuple unpacking:

```python
let (x, y) = point
var (a, b) = (1, 2)
```

---

## Range Expressions

```python
for i in 0 .. 10:    # inclusive: 0, 1, …, 10
    pass

for i in 0 ..< 10:   # exclusive upper bound: 0, 1, …, 9
    pass

if x in 1 .. 100:    # range membership check
    pass
```

Python output: `range(lo, hi + 1)` for `..`, `range(lo, hi)` for `..<`.
Nim output: native `lo .. hi` and `lo ..< hi`.

---

## Case / When Statements

Pattern matching with Ada/Nim-inspired syntax. All standard Python
`match/case` pattern kinds are supported: literals, captures, wildcards,
OR-patterns, ranges, sequences, mappings, class patterns, and `as` bindings.

```python
case value:
    when 1:
        print("one")
    when 2 | 3:
        print("two or three")
    when 4 .. 10:
        print("four to ten")
    when others:
        print("something else")
```

Guards work with any boolean expression:

```python
case point:
    when Point(x, y) if x == y:
        print("on the diagonal")
    when Point(x, y):
        print(f"off diagonal: {x}, {y}")
```

Python output: standard `match/case`.
Nim output: `case/of` statement.

---

## Tick Attributes

Ada-style `'` attributes give first-class access to enum and subrange
metadata. The tokenizer preprocesses `Type'Attr` to `Type__tick__Attr`
before parsing so Python's lexer is not confused by the apostrophe.

```python
type Stage_T is enum A, B, C

Stage_T'First   # first member  → A
Stage_T'Last    # last member   → C
current'Next    # successor     → type(current)(current.value + 1)
current'Prev    # predecessor   → type(current)(current.value - 1)
```

These are particularly useful in `for` loops over enums:

```python
for s in Stage_T'First .. Stage_T'Last:
    ...
```

---

## Enum Array Literals

Arrays indexed by enum members use `[KEY: value, ...]` syntax, mapping
cleanly to Python dicts and Nim enum-indexed arrays:

```python
type Priority is enum LOW, MED, HIGH

var costs: [Priority]int = [LOW: 1, MED: 5, HIGH: 10]
```

Python output: `{Priority.LOW: 1, Priority.MED: 5, Priority.HIGH: 10}`
Nim output:    `[LOW: 1, MED: 5, HIGH: 10]`

---

## Named Tuple Literals

Construct named tuples with `(field: value)` syntax. The transpiler matches
field names against registered `type … is tuple` declarations and emits the
appropriate constructor:

```python
type Point is tuple:
    x: float
    y: float

p = Point(x: 1.0, y: 2.5)
```

Python output: `p = Point(x=1.0, y=2.5)`
Nim output:    `p = (x: 1.0, y: 2.5)`

---

## Functions

Standard Python `def` syntax is used for all functions, with HPython type
annotations on parameters and return values.

```python
def add(a: int, b: int) -> int:
    return a + b

def greet(name: str) -> str:
    return f"Hello, {name}"
```

### Implicit return

When a function has a return-type annotation and its last statement is a bare
expression (not an explicit `return`), HPython automatically promotes that
expression to a return value. This lets you write single-expression functions
in the style of Nim or Kotlin:

```python
def formatTime(dt: str) -> str:
    dt.format("HH:mm:ss")

def clamp(x: int, lo: int, hi: int) -> int:
    max(lo, min(x, hi))
```

**Python output** — the bare expression is wrapped with `return`:

```python
def formatTime(dt: str) -> str:
    return dt.format("HH:mm:ss")

def clamp(x: int, lo: int, hi: int) -> int:
    return max(lo, min(x, hi))
```

**Nim output** — the expression is left as-is, since Nim treats the last
expression in a proc as its implicit return value:

```nim
proc formatTime(dt: string): string =
    dt.format("HH:mm:ss")

proc clamp(x: int, lo: int, hi: int): int =
    max(lo, min(x, hi))
```

Two rules govern when implicit return fires:

- The function must have a return-type annotation (`-> T`). Functions without
  one are left unchanged.
- `-> None` is excluded — a void function's last expression stays as a
  statement, never becomes a return.

Explicit `return` always works too; implicit return is just a convenience for
functions whose body is a single expression or ends with one.

---

## Classes and Inheritance

Standard Python class syntax is fully supported, including inheritance,
`__init__`, properties, and generic type parameters. In Nim output, classes
with inheritance become `ref object of Base` with separate `proc` definitions.

```python
class Shape:
    def area(self) -> float:
        return 0.0

class Circle(Shape):
    var radius: float

    def __init__(self, r: float):
        self.radius = r

    def area(self) -> float:
        return 3.14159 * self.radius ** 2
```

### Generic Classes

```python
class Optimizer[S, D]:
    var offset: float

    def __init__(self, offset: float = 0.0):
        self.offset = offset

    def evaluate(self, state: S) -> float:
        return 0.0
```

Nim output uses `[S, D]` generic parameters on the object type and all
generated procs.

---

## Nim-Only Imports

`nimport` marks imports that appear only in Nim output and are stripped from
Python output. Use it for Nim standard-library modules that have no Python
equivalent:

```python
nimport strutils, sequtils, algorithm
```

Regular `import` statements are translated automatically: known stdlib modules
(`os`, `math`, `json`, `re`, `time`) are mapped to their Nim counterparts;
others are wrapped with `pyImport(...)` via the `nimpy` bridge.

---

## Print Statement

HPython supports Python-2-style `print` without parentheses. The transpiler
rewrites it to `print(...)` in Python 3 output and `echo(...)` in Nim output,
so you never need to think about the target.

```python
print "hello"
print f"result: {value}"
print "x =", x
```

**Python 3 output:**

```python
print("hello")
print(f"result: {value}")
print("x =", x)
```

**Nim output:**

```nim
echo("hello")
echo(fmt"result: {value}")  # strformat imported automatically
echo("x =", x)
```

The call form `print(...)` still works unchanged — the parser only intercepts
`print` when it is *not* immediately followed by `(`, so existing Python 3
code is never affected.

---

## Shell Statements

HPython has first-class syntax for running shell commands. The `shell` and
`shellLines` keywords integrate subprocess execution directly into the
language, with variable interpolation, output capture, and options for working
directory and timeout.

### Basic usage

```python
let result = shell: echo hello
print(result.output)   # stdout as a string
print(result.stderr)   # stderr as a string
print(result.code)     # exit code as int
```

### Variable interpolation

Use `{name}` anywhere in the command body to interpolate an HPython variable.
The transpiler detects the braces and emits an f-string automatically.

```python
let name = "world"
let result = shell: echo hello {name}
print(result.output)
```

### Getting output as lines

`shellLines` captures stdout and splits it into a list of strings, one per
line — no `.splitlines()` call needed at the call site.

```python
let lines = shellLines: ls -la
for line in lines:
    print(line)
```

### Options

Options are passed in parentheses between the keyword and the colon.

```python
# Working directory
let result = shell(cwd = "/tmp"): pwd

# Timeout in milliseconds
let result = shell(timeout = 5000): slow-command

# Both together
let result = shell(cwd = "/tmp", timeout = 3000): ls -la
```

### Discarding output

Omit the assignment target when you don't need the result.

```python
shell: rm -rf /tmp/build
```

### Inside functions

`shell` is a statement, so it works at any indentation level.

```python
def build(target: str) -> str:
    let result = shell: make {target}
    if result.code != 0:
        raise RuntimeError(result.stderr)
    return result.output
```

### Translation reference

| HPython | Python 3 | Nim |
|---------|----------|-----|
| `let r = shell: cmd` | `_r = subprocess.run("""cmd""", shell=True, capture_output=True, text=True)` then `SimpleNamespace(output=…, stderr=…, code=…)` | `let _r = execCmdEx("cmd")` then `(output: _r[0], code: _r[1])` |
| `let ls = shellLines: cmd` | `…run(…).stdout.splitlines()` | `execCmdEx("cmd")[0].splitLines()` |
| `shell: cmd` | `subprocess.run("""cmd""", shell=True)` | `discard execCmd("cmd")` |
| `shell(cwd="/x"): cmd` | `…run(…, cwd="/x")` | `execCmdEx("cd /x && cmd")` |
| `shell(timeout=5000): cmd` | `…run(…, timeout=5.0)` | `execCmdEx("cmd")  # timeout: 5000ms` |
| `{var}` in body | `f"""…{var}…"""` | `fmt"""…{var}…"""` (imports `strformat`) |

The required imports (`subprocess`, `types`, `osproc`, `strformat`) are
inserted automatically at the top of the output — you never write them by
hand.

---

## Architecture

```
hparsec/
├── hek_parsec.py               Parser combinator engine
│                               ParserMeta (+, |, [], *, ~), packrat memoization,
│                               SymbolTable, forward references, token helpers
│
├── hek_tokenize.py             Enhanced tokenizer
│                               RichNL (comments attached to newlines),
│                               tick-attribute preprocessing (Type'Attr),
│                               bracket-context NL stripping
│
├── hek_helpers.py              Shared indentation and RichNL utilities
│
├── HPYTHON_GRAMMAR/            Language-neutral grammar definitions
│   ├── py3expr.py              Expression grammar (precedence, all operators)
│   ├── py3stmt.py              Simple statements (assignment, import, raise, …)
│   ├── py3compound_stmt.py     Compound statements (if/while/for/def/class/shell/…)
│   └── py_declarations.py      HPython type annotations and type declarations
│
├── TO_PYTHON/                  Python 3 backend
│   ├── hek_py3_expr.py         to_py() for all expression nodes
│   ├── hek_py3_stmt.py         to_py() for simple statements
│   ├── hek_py3_parser.py       to_py() for compound statements
│   ├── hek_py_declarations.py  to_py() for type annotations
│   └── py2py.py                Entry point: parse + emit Python 3
│
├── TO_NIM/                     Nim backend
│   ├── hek_nim_expr.py         to_nim() for all expression nodes
│   ├── hek_nim_stmt.py         to_nim() for simple statements
│   ├── hek_nim_parser.py       to_nim() for compound statements
│   ├── hek_nim_declarations.py to_nim() for type annotations
│   └── py2nim.py               Entry point: parse + emit Nim
│
└── BENCHMARK/                  Benchmark programs (.hpy) with reference outputs
```

### How transpilation works

1. `hek_tokenize.Tokenizer` scans the source, preprocesses tick attributes
   (`Type'Attr` → `Type__tick__Attr`), and bundles inline comments into
   `RichNL` objects so they travel with the parse tree.
2. The grammar combinators in `HPYTHON_GRAMMAR/` define the language using
   `hek_parsec` operators. Parsers are plain classes composed with `+`, `|`,
   and `[:]`; forward references use `fw("name")`.
3. Each grammar rule class gets `to_py()` and `to_nim()` methods attached via
   the `@method` decorator (defined in the respective backend modules). Every
   such method carries a docstring quoting the grammar rule it implements.
4. `py2py.py` / `py2nim.py` parse the full module and walk the AST, calling
   `to_py()` or `to_nim()` on each node.

### Parser combinator operators

| Expression | Meaning                                     |
|------------|---------------------------------------------|
| `A + B`    | Sequence: match A then B                   |
| `A \| B`   | Ordered choice: try A, fall back to B      |
| `A[1:]`    | One or more repetitions                    |
| `A[:]`     | Zero or more repetitions                   |
| `A[n:m]`   | Between n and m repetitions                |
| `A * n`    | Exactly n repetitions                      |
| `~A`       | Negative lookahead: succeed only if A fails|
| `fw("X")`  | Lazy forward reference (recursive grammars)|

---

## Known Limitations

**Blank lines and inline comments** — `py2py.py` currently collapses blank
lines between statements and drops inline comments (`x = 1  # note`). The
infrastructure for fixing this (`RichNL` carrying comments through the parse
tree) is already in place; the remaining work is threading those tokens
through all compound-statement `to_py()` methods.

**Native `match/case` syntax** — HPython's `case/when` currently replaces
Python 3.10+ `match/case`. Restoring support for standard `match/case` as an
alternative syntax (so HPython remains a true superset) is on the TODO list.

**Nim stdlib coverage** — generated Nim code relies on a local `stdlib.nim`
shim for some Python builtins. See `BENCHMARK/stdlib.nim`.

**Global parser state** — `ParserState` is a class-level singleton. Call
`ParserState.reset()` between independent parse runs in the same process;
concurrent parses in separate threads are not safe.
