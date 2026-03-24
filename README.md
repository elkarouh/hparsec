# HPython

HPython is a statically-typed superset of Python 3 inspired by Ada and Nim.
It transpiles to both **Python 3** and **Nim**, letting you write concise,
type-safe code in a familiar syntax and target either ecosystem without
changing the source.

Every valid Python 3 file is also valid HPython. The extra features are purely
additive: left-to-right type annotations, Ada-style enums and variant records,
tick attributes, range expressions, `case/when` pattern matching, and
first-class shell command integration.

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
- [Python Interoperability](#python-interoperability)
- [Print Statement](#print-statement)
- [Shell Statements](#shell-statements)
- [Bash Variables](#bash-variables)
- [Benchmark Programs](#benchmark-programs)
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

### Transpile to Python 3

```bash
python3 TO_PYTHON/py2py.py source.hpy         # print to stdout
python3 TO_PYTHON/py2py.py -c source.hpy      # transpile and run
echo "var x: int = 42" | python3 TO_PYTHON/py2py.py  # from stdin
```

### Transpile to Nim

```bash
python3 TO_NIM/py2nim.py source.hpy           # transpile and compile+run (default)
python3 TO_NIM/py2nim.py -t source.hpy        # transpile only, write source.nim
python3 TO_NIM/py2nim.py c source.hpy         # compile (nim c)
python3 TO_NIM/py2nim.py c -r source.hpy      # compile and run (nim c -r)
python3 TO_NIM/py2nim.py --test               # run built-in self-tests
```

**Incremental builds** — `py2nim` performs a three-tier up-to-date check:
skip transpilation if `.nim` is newer than both `.hpy` and the transpiler
source files; skip compilation if the binary is newer than `.nim`; execute
the existing binary directly if everything is current. Changing any
transpiler `.py` file automatically triggers retranspilation of all cached
`.hpy` files on their next run.

**Clean source directories** — all generated artifacts (`.nim` file,
compiled binary, nimcache) are stored in `~/.cache/hparsec/cache-<HASH>/`,
keyed by the absolute path of the `.hpy` file. Source directories stay
uncluttered and the cache survives reboots (inspired by
[nimbang](https://github.com/jabbalaci/nimbang)).

**Shebang support** — add `#!/usr/bin/env py2nim` as the first line of an
`.hpy` file and make it executable. The file compiles and runs directly
without arguments to the transpiler.

**Per-file compiler options** — add a `#py2nim-args` directive as the
second line to set per-file nim options (inspired by nimbang's
`#nimbang-args`). The first token may be a nim subcommand; remaining tokens
are forwarded to the nim compiler. Command-line flags always override the
directive.

```python
#!/usr/bin/env py2nim
#py2nim-args c -d:release
```

**Forwarding flags to Nim** — any flag not recognised by `py2nim` (e.g.
`-d:release`, `--opt:speed`) is passed straight to `nim`.

```bash
python3 TO_NIM/py2nim.py c -d:release source.hpy   # optimised build
```

---

## Type Annotations

HPython uses a concise **left-to-right** annotation syntax rather than
Python's `typing` module. Container kinds are expressed as prefixes:
`[]int` reads naturally as "list of int".

| HPython        | Python                    | Nim                            |
|----------------|---------------------------|--------------------------------|
| `[]T`          | `list[T]`                 | `seq[T]`                       |
| `[N]T`         | `tuple[T, ...]`           | `array[N, T]`                  |
| `[*]T`         | `Sequence[T]`             | `openArray[T]`                 |
| `[E]T`         | `dict[E, T]`              | `array[E, T]` (enum-indexed)   |
| `{K}V`         | `dict[K, V]`              | `Table[K, V]`                  |
| `{}T`          | `set[T]`                  | `HashSet[T]` or `set[T]`       |
| `?T`           | `T \| None`               | `Option[T]`                    |
| `(T, U)`       | `tuple[T, U]`             | `(T, U)`                       |
| `[(T, U)]R`    | `Callable[[T, U], R]`     | `proc(a0: T, a1: U): R`        |

Types compose freely:

```python
var words:    []str        = ["hello", "world"]
var counts:   {str}int     = {"hello": 1}
var maybe:    ?int         = None
var grid:     [][]float    = [[1.0, 2.0], [3.0, 4.0]]
var callback: [(int,)]bool = my_predicate
```

### Empty collection literals

HPython uses distinct syntax for empty dicts and empty sets, resolving
Python's ambiguity where `{}` means an empty dict:

| Literal | Meaning      | Python output | Nim output                  |
|---------|--------------|---------------|-----------------------------|
| `{:}`   | empty dict   | `{}`          | `initTable[K, V]()`         |
| `{}`    | empty set    | `set()`       | `initHashSet[T]()` or `{}`  |

```python
var counts:  {str}int = {:}    # empty dict
var visited: {}str    = {}     # empty HashSet
var flags:   {}bool   = {}     # empty ordinal set
```

**Nim output:**

```nim
import tables, sets
var counts:  Table[string, int] = initTable[string, int]()
var visited: HashSet[string]    = initHashSet[string]()
var flags:   set[bool]          = {}
```

For sets, the Nim backend uses the type annotation to pick between
`initHashSet` (heap-allocated, any T) and `{}` (Nim ordinal set for
`bool`, `char`, `byte`, small integers, and user-defined enums).

---

## Type Declarations

### Enums

```python
type Color   is enum RED, GREEN, BLUE
type Digit_T is enum D0, D1, D2, D3, D4, D5, D6, D7, D8, D9
```

Both `is` and `=` are accepted as the assignment keyword.

**Python output:** `class Color(Enum): RED = auto(); GREEN = auto(); BLUE = auto()`
**Nim output:** `type Color = enum RED, GREEN, BLUE`

### Subranges

```python
type SmallInt is 0 .. 255    # inclusive on both ends
type Index    is 0 ..< 10    # exclusive upper bound (0–9)
```

### Named Tuples

```python
type Point is tuple:
    x: float
    y: float
```

**Python output:** `class Point(NamedTuple): ...`
**Nim output:** `type Point = tuple`

### Records (Dataclasses)

```python
type Person is record:
    name: str
    age:  int
```

**Python output:** `@dataclass class Person: ...`
**Nim output:** `type Person = object`

### Discriminated Records (Variant Types)

Ada/Nim-style variant records where the set of fields depends on an enum
discriminant. The discriminant is declared in parentheses after the type
name:

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
var result: []int          # Nim: seq[int]; Python: list[int]
```

Tuple unpacking:

```python
let (x, y) = point
var (a, b) = (1, 2)
```

---

## Range Expressions

```python
for i in 0 .. 10:     # inclusive: 0, 1, …, 10
    pass

for i in 0 ..< 10:    # exclusive upper bound: 0, 1, …, 9
    pass

if x in 1 .. 100:     # range membership test
    pass
```

**Python output:** `range(lo, hi + 1)` for `..`, `range(lo, hi)` for `..<`.
**Nim output:** native `lo .. hi` and `lo ..< hi`.

Ranges work with enum tick attributes too:

```python
for s in Stage_T'First .. Stage_T'Last:
    ...
```

---

## Case / When Statements

Pattern matching with Ada/Nim-inspired syntax. All standard pattern kinds
are supported: literals, captures, wildcards, OR-patterns, ranges,
sequences, mappings, class patterns, and `as` bindings.

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

Guards:

```python
case point:
    when Point(x, y) if x == y:
        print("on the diagonal")
    when Point(x, y):
        print(f"off diagonal: {x}, {y}")
```

**Python output:** standard `match/case` statement.
**Nim output:** `case/of` statement.

---

## Tick Attributes

Ada-style `'` attributes provide first-class access to enum and subrange
metadata. The tokenizer preprocesses `Type'Attr` to `Type__tick__Attr`
before parsing, so Python's lexer is not confused by the apostrophe.

```python
type Stage_T is enum A, B, C

Stage_T'First    # first member  → A
Stage_T'Last     # last member   → C
current'Next     # successor     → type(current)(current.value + 1)
current'Prev     # predecessor   → type(current)(current.value - 1)
```

Particularly useful for iterating over an enum's full range:

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

**Python output:** `{Priority.LOW: 1, Priority.MED: 5, Priority.HIGH: 10}`
**Nim output:** `[LOW: 1, MED: 5, HIGH: 10]`

Nested enum arrays (for 2-D lookup tables):

```python
var trans_p: [Hidden_State_T][Symptom_T]float = [
    HEALTHY: [NORMAL: 0.5, COLD: 0.4, DIZZY: 0.1],
    FEVER:   [NORMAL: 0.1, COLD: 0.3, DIZZY: 0.6],
]
```

---

## Named Tuple Literals

Construct named tuples with `(field: value)` syntax. The transpiler matches
field names against registered `type … is tuple` declarations:

```python
type Point is tuple:
    x: float
    y: float

p = Point(x: 1.0, y: 2.5)
```

**Python output:** `p = Point(x=1.0, y=2.5)`
**Nim output:** `p = (x: 1.0, y: 2.5)`

Named tuple literals also work inside collections and as function arguments:

```python
fringe.push((stage: STAGE1, budget: float(CAPITAL)))
```

---

## Functions

Standard Python `def` syntax with HPython type annotations:

```python
def add(a: int, b: int) -> int:
    return a + b
```

### Implicit return

When a function has a return-type annotation and its last statement is a
bare expression (not an explicit `return`), HPython automatically promotes
it to a return value:

```python
def clamp(x: int, lo: int, hi: int) -> int:
    max(lo, min(x, hi))
```

**Python output:** wraps with `return`.
**Nim output:** left as-is (Nim treats the last expression as the implicit
return value).

Two rules govern when implicit return fires:

- The function must have a return-type annotation (`-> T`).
- `-> None` is excluded — a void function's last expression stays as a
  statement.

### Default parameter values

```python
def find_path(graph: Graph_T, start: Node_T, end: Node_T,
              path: []Node_T = []) -> []Node_T:
    ...
```

### Generator functions

`yield` is fully supported, enabling generator functions that transpile
correctly to both Python and Nim:

```python
def shortest_path(self, start_state: S, end_state: S):
    ...
    while fringe:
        ...
        if current_state == end_state:
            yield self.real_cost(cost), path
```

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
class Optimizer[S, D, C]:
    var offset: float

    def __init__(self, offset: float = 0.0):
        self.offset = offset

    def evaluate(self, state: S) -> float:
        return 0.0
```

Nim output uses `[S, D, C]` generic parameters on the object type and all
generated procs.

### Class-level variable declarations

HPython uses `var`, `let`, or `const` inside a class body to declare fields,
keeping declarations visually distinct from assignments:

```python
class TrieNode:
    var children: [Digit_T]TrieNode
    var words: []str
```

---

## Nim-Only Imports

`nimport` marks imports that appear only in Nim output and are stripped
from Python output. Use it for Nim standard-library modules that have no
Python equivalent:

```python
nimport strutils, sequtils, algorithm, stdlib
```

---

## Python Interoperability

HPython knows whether each Python `import` has a direct Nim equivalent or
needs the [nimpy](https://github.com/yglukhov/nimpy) bridge. You write
ordinary Python imports; the transpiler decides how to map them.

### Natively mapped stdlib modules

These modules translate directly to their Nim counterparts with no runtime
overhead:

| Python import    | Nim module         | Notes                            |
|------------------|--------------------|----------------------------------|
| `import os`      | `import os`        | `os.path.*` → Nim path procs     |
| `import math`    | `import math`      | All standard functions mapped    |
| `import time`    | `import times`     |                                  |
| `import re`      | `import re`        |                                  |
| `import random`  | `import random`    |                                  |
| `import json`    | `import std/json`  |                                  |
| `import itertools`| `import sequtils` |                                  |
| `import asyncio` | `import asyncdispatch` |                              |

### Function call translation

```python
import math, time, re, random

x      = math.sqrt(4.0)
t      = time.time()
result = re.sub(r'\s+', ' ', text)
n      = random.randint(1, 100)
```

**Nim output:**

```nim
import math, re, random, times

var x      = sqrt(4.0)
var t      = epochTime()
var result = replace(text, re("\\s+"), " ")
var n      = rand(1..100)
```

### `os` and `sys` utilities

```python
import os, sys

if os.path.exists('/tmp/data'):
    p = os.path.join('/tmp', 'data', 'out.txt')
    os.makedirs('/tmp/data')

sys.exit(1)
```

**Nim output:**

```nim
import os

if fileExists("/tmp/data"):
    var p = joinPath("/tmp", "data", "out.txt")
    createDir("/tmp/data")

quit(1)
```

### Non-native Python libraries (nimpy bridge)

Libraries with no direct Nim equivalent are imported via nimpy automatically:

```python
import requests
import pandas as pd

r  = requests.get('https://example.com')
df = pd.read_csv('data.csv')
```

**Nim output:**

```nim
import nimpy

let requests = pyImport("requests")
let pd       = pyImport("pandas")

var r  = requests.get("https://example.com")
var df = pd.read_csv("data.csv")
```

### Automatic `.to(T)` coercion

When a variable has a primitive type annotation and its right-hand side
comes from a `PyObject` call chain, `.to(T)` is injected automatically:

```python
import requests

r     = requests.get('https://api.example.com/data')
count: int   = r.json()['total']
score: float = r.json()['score']
name:  str   = r.json()['name']
```

**Nim output:**

```nim
var count: int   = r.json()["total"].to(int)
var score: float = r.json()["score"].to(float)
var name:  string = r.json()["name"].to(string)
```

You can write `.to(T)` explicitly if you prefer — the transpiler will not
double-wrap it.

### Calling Python callables from Nim

When a variable holds a callable `PyObject` (e.g. a fitted model, compiled
regex, scipy interpolator), calling it emits `callObject()` automatically:

```python
import scipy.interpolate as interp

f   = interp.interp1d(x_points, y_points, 'linear')
val: float = f(1.5)
```

**Nim output:**

```nim
var f   = interp.interp1d(x_points, y_points, "linear")
var val: float = callObject(f, 1.5).to(float)
```

### `len()` helper

When nimpy is active and `len()` is called on a `PyObject`, a thin helper
proc is emitted automatically — only when needed:

```nim
proc len(o: PyObject): int = pyBuiltinsModule().len(o).to(int)
```

---

## Print Statement

HPython supports Python-2-style `print` without parentheses. The
transpiler rewrites it to `print(...)` in Python 3 and `echo(...)` in Nim:

```python
print "hello"
print f"result: {value}"
print "x =", x
```

The call form `print(...)` still works unchanged — the parser only
intercepts `print` when it is *not* immediately followed by `(`.

---

## Shell Statements

HPython has first-class syntax for running shell commands. The `shell` and
`shellLines` keywords integrate subprocess execution directly, with variable
interpolation, output capture, and options for working directory and timeout.

### Basic usage

```python
let result = shell: echo hello
print(result.output)   # stdout as a string
print(result.stderr)   # stderr as a string
print(result.code)     # exit code as int
```

### Variable interpolation

Use `{name}` anywhere in the command body to interpolate an HPython variable:

```python
let name = "world"
let result = shell: echo hello {name}
```

### Output as lines

`shellLines` captures stdout and splits it into `[]str`, one element per line:

```python
let lines = shellLines: ls -la
for line in lines:
    print(line)
```

### Options

```python
let result = shell(cwd = "/tmp"):           pwd
let result = shell(timeout = 5000):         slow-command
let result = shell(cwd = "/tmp", timeout = 3000): ls -la
```

### Discarding output

```python
shell: rm -rf /tmp/build
```

### Translation reference

| HPython              | Python 3                                            | Nim                                        |
|----------------------|-----------------------------------------------------|--------------------------------------------|
| `let r = shell: cmd` | `subprocess.run(…, capture_output=True, text=True)` | `execCmdEx("cmd")`                         |
| `let ls = shellLines: cmd` | `…stdout.splitlines()`                    | `execCmdEx("cmd")[0].splitLines()`         |
| `shell: cmd`         | `subprocess.run("cmd", shell=True)`                 | `discard execCmd("cmd")`                   |
| `shellLines: cmd`    | (implicit return of split lines)                    | `return execCmdEx("cmd")[0].splitLines()`  |
| `{var}` in body      | `f"""…{var}…"""`                                    | `fmt"""…{var}…"""` (imports `strformat`)   |

Required imports (`subprocess`, `types`, `osproc`, `strformat`) are inserted
automatically.

---

## Bash Variables

HPython supports bash-style special variables for scripts that handle
command-line arguments and environment variables:

### Argument variables

```python
print $0        # script name
print $1        # first argument
print $@        # all arguments (as a list)
print $#        # number of arguments
```

### Environment variables

All-caps identifiers with `$` read an environment variable:

```python
home   = $HOME
path   = $PATH
editor = $EDITOR
```

### In expressions

```python
if $# < 2:
    print f"Usage: {$0} <input> <output>"
    quit(1)

for arg in $@:
    print arg

outdir = $HOME + "/output"
```

### Translation reference

| HPython   | Python 3                    | Nim                    |
|-----------|-----------------------------|------------------------|
| `$0`      | `sys.argv[0]`               | `getAppFilename()`     |
| `$1` … `$9` | `sys.argv[1]` … `sys.argv[9]` | `paramStr(1)` … `paramStr(9)` |
| `$@`      | `sys.argv[1:]`              | `commandLineParams()`  |
| `$#`      | `len(sys.argv) - 1`         | `paramCount()`         |
| `$NAME`   | `os.environ.get('NAME', '')` | `getEnv("NAME")`      |

Required imports are inserted automatically.

### File-test operators

Bash-style file-test operators work as boolean expressions:

```python
if -e path:          # path exists
if -f path:          # path is a regular file
if -d path:          # path is a directory
if -L path:          # path is a symlink
if -r path:          # path is readable
if -w path:          # path is writable
if -x path:          # path is executable
if -s path:          # path exists and is non-empty

if file1 -nt file2:  # file1 is newer than file2
if file1 -ot file2:  # file1 is older than file2
```

They can be negated and combined with `and`/`or`:

```python
if not -e comment_path:
    comment_path = comment_path.replace("_t/", "_e/")
if -f comment_path:
    text = readFile(comment_path)
```

### Translation reference

| HPython      | Python 3                        | Nim                          |
|--------------|---------------------------------|------------------------------|
| `-e path`    | `os.path.exists(path)`          | `fileExists(path) or dirExists(path)` |
| `-f path`    | `os.path.isfile(path)`          | `fileExists(path)`           |
| `-d path`    | `os.path.isdir(path)`           | `dirExists(path)`            |
| `-L path`    | `os.path.islink(path)`          | `symlinkExists(path)`        |
| `-r path`    | `os.access(path, os.R_OK)`      | `fileExists(path)`           |
| `-w path`    | `os.access(path, os.W_OK)`      | `fileExists(path)`           |
| `-x path`    | `os.access(path, os.X_OK)`      | `fileExists(path)`           |
| `-s path`    | `os.path.getsize(path) > 0`     | `fileExists(path) and getFileSize(path) > 0` |
| `a -nt b`    | `os.path.getmtime(a) > os.path.getmtime(b)` | `getLastModificationTime(a) > getLastModificationTime(b)` |
| `a -ot b`    | `os.path.getmtime(a) < os.path.getmtime(b)` | `getLastModificationTime(a) < getLastModificationTime(b)` |

---

## Callable objects and pipe operator

### `__call__` and `__ror__`

Classes that define `__call__` become callable objects. In Nim this uses
the `{.experimental: "callOperator".}` pragma (inserted automatically).

`__ror__` (and other reflected operators like `__radd__`, `__rsub__`) flip
the argument order in Nim so `"text" | style` works naturally:

```python
class Style:
    var on: str
    var off: str
    def __init__(self, code: int):
        self.on = f"\x1b[{code}m"
        self.off = "\x1b[0m"
    def __call__(self, *args: str) -> str:
        return "".join([f"{self.on}{arg}" for arg in args]) + self.off
    def __ror__(self, other: str) -> str:
        return self(other)

let bold: Style = Style(1)
let red:  Style = Style(31)

print("hello" | bold | red)   # chains via __ror__
print(bold("hello", "world")) # direct __call__
```

The `|` operator is context-sensitive: when both operands involve custom
types (not plain integers), it emits Nim `|`; otherwise it emits `or`.

---

## Enum constructors

Calling an enum type with a string argument emits `parseEnum`:

```python
type State = enum ACTIVE, ON_HOLD, DONE

def parse_state(s: str) -> State:
    try:
        State(s.replace("-", "_"))
    except:
        ACTIVE
```

Transpiles to:

```nim
proc parse_state(s: string): State =
    try:
        parseEnum[State](s.replace("-", "_"))
    except:
        ACTIVE
```

---

## Benchmark Programs

The `BENCHMARK/` directory contains real programs that exercise the full
language and serve as end-to-end tests. Each has a `.hpy` source, a
transpiled `.nim` output, and in most cases a reference Python `.py` file.

### `primes.hpy` — Prime sieve

Counts primes up to 1,000,000 and measures wall time. Demonstrates the
`..` and `..<` range operators and `time.perf_counter()`.

```python
def is_prime(n: int) -> bool:
    for k in 2 .. int(n ** 0.5):
        if n % k == 0:
            return False
    return True

for k in 2 ..< N:
    if is_prime(k): count += 1
```

### `graph.hpy` — Graph path search

Three path-finding functions (find_path, find_all_paths, find_shortest_path)
on a dict-of-lists graph. Exercises recursive functions, `[]str` default
parameters, `not in`, and `append`.

```python
type Node_T  is str
type Graph_T is {Node_T}[]Node_T

def find_path(graph: Graph_T, start: Node_T, end: Node_T,
              path: []Node_T = []) -> []Node_T:
    ...
```

### `phonecode.hpy` — Phone code benchmark

Implements Prechelt's classic benchmark: find all word encodings of phone
numbers using a trie. Exercises enums, dict types, optional types, nested
classes, closures, and `$#`/`$1`/`$2` argument variables.

```python
type Digit_T is enum D0, D1, D2, D3, D4, D5, D6, D7, D8, D9

class TrieNode:
    var children: [Digit_T]TrieNode
    var words:    []str
    ...
```

### `h_shortest_path.hpy` — Generic optimiser framework

A 450-line framework demonstrating: generic classes `[S, D, C]`, nested
type declarations, `yield` (generator methods), discriminated tuples,
tick-attribute iteration, and 8 complete algorithm examples including
Dijkstra, A*, dynamic programming, knapsack, rod cutting, HMM Viterbi,
equipment replacement, and capital budgeting.

```python
class Optimizer[S, D, C]:
    def shortest_path(self, start_state: S, end_state: S, allsolutions: bool = True):
        fringe: PriorityQueue[Fringe_Element_T[S, D, C]] = PriorityQueue(...)
        while fringe:
            ...
            yield self.real_cost(cost), path
```

### `show_status.hpy` — Shell integration demo

A test-monitoring daemon that polls a shell command every minute, parses
its output, and prints timing summaries. Exercises `shellLines:`, `{}str`
sets, `time.sleep()`, and Python-2-style `print`.

```python
def getTestStatusLines() -> []str:
    shellLines: show_tests_status -raw

completedTests: {}str = {}
while True:
    time.sleep(60)
    for test in parseCompletedTests(getTestStatusLines()):
        completedTests.add(test)
```

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
│   ├── hek_py3_parser.py       to_py() for compound statements + type decls
│   ├── hek_py_declarations.py  to_py() for type annotations
│   └── py2py.py                Entry point: parse + emit Python 3
│
├── TO_NIM/                     Nim backend
│   ├── hek_nim_expr.py         to_nim() for all expression nodes
│   ├── hek_nim_stmt.py         to_nim() for simple statements
│   ├── hek_nim_parser.py       to_nim() for compound statements + type decls
│   ├── hek_nim_declarations.py to_nim() for type annotations
│   └── py2nim.py               Entry point: parse + emit Nim
│
└── BENCHMARK/                  End-to-end example programs
    ├── *.hpy                   HPython source
    ├── *.nim                   Transpiled Nim output
    └── stdlib.nim              Nim shim for Python builtins (PriorityQueue, etc.)
```

### How transpilation works

1. `hek_tokenize.Tokenizer` scans the source, preprocesses tick attributes
   (`Type'Attr` → `Type__tick__Attr`), and bundles inline comments into
   `RichNL` objects so they travel with the parse tree.
2. The grammar combinators in `HPYTHON_GRAMMAR/` define the language using
   `hek_parsec` operators. Parsers are plain classes composed with `+`, `|`,
   and `[:]`; forward references use `fw("name")`.
3. Each grammar rule class gets `to_py()` and `to_nim()` methods attached
   via the `@method` decorator (defined in the respective backend modules).
   Every method carries a docstring quoting the grammar rule it implements.
4. `py2py.py` / `py2nim.py` parse the full module and walk the AST, calling
   `to_py()` or `to_nim()` on each node.

### Parser combinator operators

| Expression  | Meaning                                      |
|-------------|----------------------------------------------|
| `A + B`     | Sequence: match A then B                    |
| `A \| B`    | Ordered choice: try A, fall back to B       |
| `A[1:]`     | One or more repetitions                     |
| `A[:]`      | Zero or more repetitions                    |
| `A[n:m]`    | Between n and m repetitions                 |
| `A * n`     | Exactly n repetitions                       |
| `~A`        | Negative lookahead: succeed only if A fails |
| `fw("X")`   | Lazy forward reference (recursive grammars) |

---

## Known Limitations

**Blank lines and inline comments** — `py2py.py` currently collapses blank
lines between statements and drops inline comments (`x = 1  # note`). The
infrastructure for fixing this (`RichNL` carrying comments through the parse
tree) is already in place; the remaining work is threading those tokens
through all compound-statement `to_py()` methods.

**Native `match/case` syntax** — HPython's `case/when` currently replaces
Python 3.10+ `match/case`. Restoring support for standard `match/case` as
an alternative syntax (so HPython remains a true superset) is on the
[TODO list](TODO.md).

**Nim stdlib coverage** — generated Nim code relies on a local `stdlib.nim`
shim for some Python builtins (`PriorityQueue`, `FifoQueue`, `ANY`). See
`BENCHMARK/stdlib.nim`.

**Global parser state** — `ParserState` is a class-level singleton. Call
`ParserState.reset()` between independent parse runs in the same process;
concurrent parses in separate threads are not safe.
