# Adascript Tutorial

Adascript is a statically-typed superset of Python 3 that transpiles to both
**Python 3** and **Nim**. Every valid Python 3 file is also valid Adascript —
the extra features are purely additive. You write one source file; both
ecosystems get idiomatic, efficient output.

```
source.ady  ──▶  python3 TO_PYTHON/py2py.py source.ady  ──▶  Python 3
            ──▶  python3 TO_NIM/py2nim.py   source.ady  ──▶  Nim
```

---

## Table of Contents

1. [Getting Started](#1-getting-started)
2. [Type Annotations](#2-type-annotations)
3. [Variable Declarations](#3-variable-declarations)
4. [Enums](#4-enums)
5. [Named Tuples](#5-named-tuples)
6. [Records and Variant Records](#6-records-and-variant-records)
7. [Collections](#7-collections)
8. [Subranges](#8-subranges)
9. [Tick Attributes](#9-tick-attributes)
10. [Range Expressions](#10-range-expressions)
11. [Control Flow](#11-control-flow)
12. [Functions](#12-functions)
13. [Classes and Inheritance](#13-classes-and-inheritance)
14. [Generic Classes](#14-generic-classes)
15. [Shell Integration](#15-shell-integration)
16. [Bash Variables and File Tests](#16-bash-variables-and-file-tests)
17. [Nim-Only Imports](#17-nim-only-imports)
18. [Real Examples](#18-real-examples)

---

## 1. Getting Started

### File structure

Adascript files use the `.ady` extension. The first two lines can carry a
shebang and per-file compiler options:

```python
#!/usr/bin/env py2nim
#ady2nim-args c --cc:clang -d:release
```

With the shebang line and `chmod +x`, you can execute the file directly:

```bash
./hello.ady        # compiles (cached) and runs
```

### The simplest program

```python
#!/usr/bin/env py2nim
print "Hello, world!"
```

Python 2-style `print` without parentheses is fully supported — the transpiler
rewrites it to `print(...)` in Python 3 and `echo(...)` in Nim. The call form
`print(...)` also works unchanged.

### Running programs

```bash
# Transpile to Python 3 and print to stdout
python3 TO_PYTHON/py2py.py source.ady

# Transpile to Python 3 and run
python3 TO_PYTHON/py2py.py -c source.ady

# Transpile to Nim and compile+run (default)
python3 TO_NIM/py2nim.py source.ady

# Transpile only — write the .nim file
python3 TO_NIM/py2nim.py --transpile-only source.ady

# Optimised build
python3 TO_NIM/py2nim.py c -d:release source.ady
```

All build artifacts go into `~/.cache/hparsec/cache-<HASH>/`, keeping your
source directory clean. Builds are incremental: re-runs skip transpilation or
compilation whenever the cached output is newer than both the source and the
transpiler itself.

---

## 2. Type Annotations

Adascript uses **left-to-right** annotation syntax. Container kinds are
prefixes, so `[]int` reads "list of int" and `{str}int` reads "dict mapping
str to int".

| Adascript      | Python                | Nim                            |
|----------------|----------------------|--------------------------------|
| `[]T`          | `list[T]`            | `seq[T]`                       |
| `[N]T`         | `tuple[T, ...]`      | `array[N, T]`                  |
| `[*]T`         | `Sequence[T]`        | `openArray[T]`                 |
| `[E]T`         | `dict[E, T]`         | `array[E, T]` (enum-indexed)  |
| `{K}V`         | `dict[K, V]`         | `Table[K, V]`                  |
| `{}T`          | `set[T]`             | `HashSet[T]` or `set[T]`      |
| `?T`           | `T \| None`          | `Option[T]`                    |
| `(T, U)`       | `tuple[T, U]`        | `(T, U)`                       |
| `[(T, U)]R`    | `Callable[[T,U], R]` | `proc(a0: T, a1: U): R`       |

Types compose freely — a graph represented as a dict-of-dicts-of-floats is
simply `{Node_T}{Node_T}float`:

```python
type Node_T is str
type Graph_T is {Node_T}[]Node_T

graph: Graph_T = {'A': ['B', 'C'], 'B': ['C', 'D']}
```

### Empty collection literals

Python's `{}` is ambiguous (empty dict or empty set). Adascript resolves this:

```python
var counts:  {str}int = {:}    # empty dict  → Python: {}   Nim: initTable[...]()
var visited: {}str    = {}     # empty set   → Python: set() Nim: initHashSet[...]()
```

---

## 3. Variable Declarations

The keywords `var`, `let`, and `const` make intent explicit and map cleanly to
Nim:

```python
var   counter: int   = 0        # mutable variable
let   name:    str   = "Alice"  # immutable binding
const MAX:     int   = 1_000    # compile-time constant
```

Declarations without an initial value are valid (Nim zero-initialises):

```python
var result: []int               # empty seq[int]
var table:  {str}int            # empty Table[string, int]
```

### Tuple unpacking

```python
let (x, y) = point              # explicit let destructuring
var (a, b) = (1, 2)             # explicit var destructuring
a, b = some_func()              # implicit let tuple unpack
```

---

## 4. Enums

Enums use Ada/Nim-style declaration with `type … is enum`:

```python
type Door_T   is enum Door1, Door2, Door3
type Priority is enum LOW, MED, HIGH
type Digit_T  is enum D0, D1, D2, D3, D4, D5, D6, D7, D8, D9
```

Both `is` and `=` are accepted as the assignment keyword.

**Python output:** `class Door_T(Enum): Door1 = auto()` …  
**Nim output:** `type Door_T = enum Door1, Door2, Door3`

Enums integrate tightly with arrays, case statements, and tick attributes —
see those sections below.

---

## 5. Named Tuples

Declare named tuples with `type … is tuple:` and a body of annotated fields:

```python
type Point is tuple:
    x: float
    y: float

type Neighbour_T is tuple:
    distance: float
    neighbor: Node_T
```

Construct them with `(field: value)` syntax:

```python
p = Point(x: 1.0, y: 2.5)
n = Neighbour_T(distance: 3.7, neighbor: 'B')
```

**Python output:** `Point(x=1.0, y=2.5)` (using `NamedTuple`)  
**Nim output:** `(x: 1.0, y: 2.5)` (structural tuple literal)

Destructure with `let`:

```python
let (dist, node) = queue.pop()
```

Named tuple literals work anywhere — inside collections, as function arguments,
and as fringe elements in priority queues:

```python
fringe.push((stage: STAGE1, budget: float(CAPITAL)))
```

---

## 6. Records and Variant Records

### Records (dataclasses)

```python
type Person is record:
    name: str
    age:  int
```

**Python output:** `@dataclass class Person: …`  
**Nim output:** `type Person = object`

### Discriminated (variant) records

When the set of fields depends on a tag, use Ada-style discriminated records.
The discriminant goes in parentheses after the type name:

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

**Nim output** — a native variant object:

```nim
type Shape = object
  case Kind: Shape_Kind
  of Circle:
    Radius: float
  of Rectangle:
    Width, Height: float
```

**Python output** — flattened dataclass with `None` defaults for the unused fields.

---

## 7. Collections

### Sequences `[]T`

```python
var words:  []str  = ["hello", "world"]
var matrix: [][]float = [[1.0, 2.0], [3.0, 4.0]]

words.append("!")
print(len(words))
```

### Hash tables `{K}V`

```python
var counts: {str}int = {:}
counts["apple"] += 1

for key, val in counts.items():
    print(f"{key}: {val}")
```

### Sets `{}T`

The type annotation drives the Nim backend: ordinal types (bool, char,
byte, small int, enum) use Nim's efficient bitset; other types use `HashSet`.

```python
var visited: {}str    = {}          # HashSet[string]
var flags:   {}bool   = {}          # set[bool] (bitset)
var seen:    {}Door_T = {}          # set[Door_T] (bitset)

visited.add("node_A")
if "node_A" in visited:
    print("already seen")
```

### Enum-indexed arrays `[E]T`

When all keys are enum members, use `[E]T` — this maps to a fixed-size array
in Nim (no heap allocation, O(1) lookup):

```python
type Priority is enum LOW, MED, HIGH

var costs: [Priority]int = [LOW: 1, MED: 5, HIGH: 10]
print(costs[HIGH])   # 10
```

Nested enum arrays work too (2-D lookup table):

```python
var transition: [Hidden_State_T][Hidden_State_T]float = [
    HEALTHY: [HEALTHY: 0.7, FEVER: 0.3],
    FEVER:   [HEALTHY: 0.4, FEVER: 0.6],
]
```

**Python output:** nested dict  
**Nim output:** `array[Hidden_State_T, array[Hidden_State_T, float]]`

### Optional values `?T`

```python
def find_exact_word(self, digits: []Digit_T) -> ?str:
    ...
    if len(node.words) > 0:
        return node.words[0]
    return None
```

---

## 8. Subranges

Subrange types constrain a base type to a value range. The `..` operator is
inclusive; `..<` excludes the upper bound:

```python
type SmallInt  is 0 .. 255     # values 0–255
type Index     is 0 ..< 10     # values 0–9
type Positive  is 1 .. 1000
```

**Python output:** `int` (a type alias)  
**Nim output:** a native Nim range type with compile-time bounds checking

---

## 9. Tick Attributes

Ada-style `'` attributes provide metadata about enums and ranges without
any runtime overhead. The tokeniser converts `Type'Attr` to `Type__tick__Attr`
before parsing, so Python's lexer is never confused by the apostrophe.

| Expression         | Meaning                            |
|--------------------|------------------------------------|
| `E'First`          | First member of enum `E`           |
| `E'Last`           | Last member of enum `E`            |
| `E'Range`          | Ordinal set of all members of `E`  |
| `expr'Next`        | Successor of `expr`                |
| `expr'Prev`        | Predecessor of `expr`              |
| `expr'Choice`      | Random element from expr or range  |

### Iterating over an enum's full range

```python
type Stage_T is enum STAGE1, STAGE2, STAGE3

for s in Stage_T'First .. Stage_T'Last:
    print(f"processing stage {s}")
```

### Set arithmetic with `'Range`

`E'Range` yields the full set of an enum's members — useful for computing
complements:

```python
# from monty_hall.ady — Monty Hall simulation
type Door_T is enum Door1, Door2, Door3

let available: {}Door_T = Door_T'Range - {candidateFirstChoice, carLocation}
let hostChoice: Door_T  = available'Choice   # random door from the set
```

### Random selection with `'Choice`

`'Choice` picks a uniformly random element from an enum, set, or range:

```python
let carLocation:         Door_T = Door_T'Choice       # random enum member
let candidateFirstChoice: Door_T = Door_T'Choice

# 'Choice also works on a range expression:
# from floyd.ady — Floyd's algorithm for distinct random sampling
t = (1..i)'Choice    # random int in 1..i
```

### Enum successor/predecessor

`'Next` and `'Prev` step through enum members:

```python
type Stage_T is enum STAGE1, STAGE2, STAGE3, END

current_stage: Stage_T = STAGE1
next_stage: Stage_T = current_stage'Next    # STAGE2
```

---

## 10. Range Expressions

The `..` (inclusive) and `..<` (exclusive) operators produce integer or enum
ranges. They are first-class values, usable in `for` loops, membership tests,
and with `'Choice`.

```python
for i in 0 .. 10:      # 0, 1, …, 10  (inclusive)
    pass

for i in 0 ..< 10:     # 0, 1, …, 9   (exclusive upper bound)
    pass

if x in 1 .. 100:      # range membership test
    print("in range")

# From primes.ady:
for k in 2 .. int(n ** 0.5):
    if n % k == 0:
        return False
```

**Python output:** `range(lo, hi+1)` for `..`; `range(lo, hi)` for `..<`  
**Nim output:** native `lo .. hi` / `lo ..< hi`

---

## 11. Control Flow

### if / elif / else

Standard Python — no changes.

```python
if x > 0:
    print("positive")
elif x == 0:
    print("zero")
else:
    print("negative")
```

### for loops

```python
for item in collection:
    pass

for i in 0 ..< 10:
    pass

for key, val in mapping.items():
    pass
```

### while loops

```python
while queue:
    item = queue.pop()
```

### case / when

Ada/Nim-inspired pattern matching. Replaces Python 3.10+ `match/case`
(also accepted by the parser).

**Literal and range patterns:**

```python
case code:
    when 200:
        print("OK")
    when 400 | 401 | 403:
        print("client error")
    when 500 .. 599:
        print("server error")
    when others:
        print("unknown")
```

**Enum patterns:**

```python
# from monty_hall.ady
for choice in Choice_T:
    case choice:
        when DontSwitch:
            if candidateFirstChoice == carLocation:
                stayWins += 1
        when Switch:
            let candidateSecondChoice: Door_T = switchOptions'Choice
            if candidateSecondChoice == carLocation:
                switchWins += 1
```

**Structural patterns with guards:**

```python
case point:
    when Point(x, y) if x == y:
        print("on the diagonal")
    when Point(x, y):
        print(f"off diagonal: {x}, {y}")
```

**Python output:** standard `match/case` statement  
**Nim output:** `case/of` statement

---

## 12. Functions

Standard Python `def` with Adascript type annotations:

```python
def add(a: int, b: int) -> int:
    return a + b

def greet(name: str = "world") -> str:
    return f"Hello, {name}!"
```

### Implicit return

When a function has a return-type annotation and its last statement is a bare
expression (not an explicit `return`), Adascript promotes it to a return:

```python
def clamp(x: int, lo: int, hi: int) -> int:
    max(lo, min(x, hi))

def is_even(n: int) -> bool:
    n % 2 == 0
```

`-> None` is excluded: void functions' last expression stays as a statement.

### Nested functions / closures

```python
# from phonecode.ady
def load_dictionary(self, filename: str, verbose: bool) -> None:
    def word_to_digits(word: str) -> []Digit_T:
        var digits: []Digit_T = []
        for c in word.lower():
            if c not in CHAR_TO_DIGIT:
                return []
            digits.append(CHAR_TO_DIGIT[c])
        return digits

    with open(filename, "r") as f:
        for line in f:
            let digits: []Digit_T = word_to_digits(line.strip())
            ...
```

### Generator functions

`yield` is fully supported and transpiles to Python generators and Nim
iterators:

```python
def shortest_path(self, start_state: S, end_state: S, allsolutions: bool = True):
    fringe: PriorityQueue[...] = PriorityQueue(...)
    while fringe:
        let (_, cost, path, current_state) = fringe.pop()
        if current_state == end_state:
            yield self.real_cost(cost), path
            if not allsolutions:
                break
        for new_decision, step_cost in self.get_next_decisions(current_state):
            fringe.push(...)
```

---

## 13. Classes and Inheritance

Standard Python class syntax with Adascript annotations. Use `var`, `let`,
or `const` inside the class body to declare fields (visually distinct from
method-local assignments).

```python
class TrieNode:
    var children: [Digit_T]TrieNode   # fixed-size array indexed by enum
    var words:    []str

    def __init__(self, filename: str = "", verbose: bool = False):
        self.children = {d: None for d in Digit_T}
        self.words = []
        if filename:
            self.load_dictionary(filename, True)

    def add_word(self, word: str, digits: []Digit_T) -> None:
        var node: TrieNode = self
        for digit in digits:
            if node.children[digit] is None:
                node.children[digit] = TrieNode()
            node = node.children[digit]
        node.words.append(word)
```

### Inline field defaults

Field declarations can carry default values. The transpiler injects them into
the generated constructor, so `__init__` only needs to set fields whose values
differ per instance:

```python
class AwkProcessor(AwkBase):
    var NR        : int = 0
    var NF        : int = 0
    var total_len : int = 0
    var counts    : [Severity_T]int = [INFO: 0, WARN: 0, ERROR: 0, OTHER: 0]

    def __init__(self, fs: str = " ", ofs: str = " "):
        self.FS  = fs   # only the caller-supplied fields need explicit init
        self.OFS = ofs
```

### Mutable self in non-virtual classes

For plain (non-`@virtual`) classes, the transpiler automatically detects
whether a method mutates `self` — via field assignment (`+=`, `=`), `.add()`,
indexed assignment, or any `self.method()` call — and emits
`self: var ClassName` in the generated Nim. No decorator or annotation needed:

```python
class Counter:
    var count: int = 0

    def increment(self):
        self.count += 1   # → proc increment(self: var Counter) in Nim
```

### Forwarding constructors

When a subclass has no `__init__`, the transpiler automatically generates a
forwarding constructor that mirrors the parent's parameters and delegates to
the parent's initialiser:

```python
@virtual
class AwkBase:
    var FS: str
    var OFS: str

    def __init__(self, fs: str = " ", ofs: str = " "):
        self.FS  = fs
        self.OFS = ofs

class AwkProcessor(AwkBase):
    var counts: [Severity_T]int = [INFO: 0, WARN: 0, ERROR: 0, OTHER: 0]
    # No __init__ needed — AwkProcessor(fs, ofs) is generated automatically,
    # calling initAwkBase(result, fs, ofs) and initialising counts.
```

### Inheritance and `super()`

```python
class EquipmentReplacement(Optimizer[State_T, Decision_T, Cost_T]):
    var maintenance_cost: {Age_T}Cost_T = {0: 60.0, 1: 80.0, 2: 120.0}

    def __init__(self, offset: float = 0.0):
        super().__init__(offset)

    def get_next_decisions(self, current_state: State_T) -> [](Decision_T, Cost_T):
        let (year, age) = current_state
        ...
```

### `@virtual` — enabling cross-module subclassing

The `@virtual` decorator makes Nim generate `ref object of RootObj` instead of
a plain `object`. It is **only required** when subclasses live in a different
file (module) from their base class — for dynamic dispatch across module
boundaries. Within a single file, plain classes handle mutable `self`
automatically (see above).

```python
@virtual
class Optimizer[S, D, C]:
    var offset: float
    var decision_path: []D
    var start_state: S

    def __init__(self, offset: float = 0.0):
        self.offset = offset
        self.decision_path = []
```

When used with `nimport` (see §17), the base class's `.nim` is compiled as a
library and subclasses in the importing file dispatch dynamically at runtime.

---

## 14. Generic Classes

Generic type parameters go in square brackets after the class name. The
transpiler infers the parameter list from context and threads it through all
generated Nim procs:

```python
class Optimizer[S, D, C]:
    """Generic shortest-path / DP optimiser.
    S = state type, D = decision type, C = cost type."""

    var offset: float

    def get_next_decisions(self, current_state: S) -> [](D, C):
        raise NotImplementedError("Override get_next_decisions()")

    def shortest_path(self, start_state: S, end_state: S):
        ...
        yield self.real_cost(cost), path
```

Subclass by instantiating the parameters:

```python
type State_T is str
type Cost_T  is float

class BookMap(Optimizer[State_T, State_T, Cost_T]):
    var G: {State_T}[](State_T, Cost_T) = { ... }

    def get_state(self, past_decisions: []State_T) -> State_T:
        return past_decisions[-1]

    def get_next_decisions(self, curr: State_T) -> [](State_T, Cost_T):
        return self.G.get(curr, [])
```

Methods that need to sit outside the class (to avoid Nim 2.x's
generic-method restriction) can be written as top-level functions and called
via UFCS (`op.longest_path(...)` still works):

```python
def longest_path(self: Optimizer[S, D, C], start_state: S, end_state: S,
                 max_path_length: int = 1000) -> (float, []D):
    """Find the highest-revenue simple path (defined outside the class so
    Nim emits 'proc' instead of 'method', avoiding Nim 2.x restrictions)."""
    ...
```

---

## 15. Shell Integration

Shell commands are first-class expressions in Adascript. The `shell` and
`shellLines` keywords integrate subprocess calls directly.

### Basic capture

```python
let result = shell: git status
print(result.output)   # stdout as a string
print(result.stderr)   # stderr as a string
print(result.code)     # exit code as int
```

### Lines capture

`shellLines` splits stdout into `[]str`, one element per line:

```python
def getTestStatusLines() -> []str:
    shellLines: show_tests_status -raw

for line in getTestStatusLines():
    print(line)
```

### Variable interpolation

Use `{name}` to embed an Adascript variable in the command body:

```python
let branch = "main"
let result = shell: git log --oneline {branch}
```

### Options

```python
let result = shell(cwd = "/tmp"):          pwd
let result = shell(timeout = 5000):        slow-command
let result = shell(cwd = src, timeout = 3000): make all
```

### Discarding output

```python
shell: rm -rf /tmp/build
shell: git add {filename}
```

### Translation summary

| Adascript                    | Python 3                                   | Nim                              |
|------------------------------|--------------------------------------------|----------------------------------|
| `let r = shell: cmd`         | `subprocess.run(…, capture_output=True)`   | `execCmdEx("cmd")`               |
| `let ls = shellLines: cmd`   | `…stdout.splitlines()`                     | `execCmdEx(…)[0].splitLines()`   |
| `shell: cmd`                 | `subprocess.run("cmd", shell=True)`        | `discard execCmd("cmd")`         |
| `{var}` in body              | f-string interpolation                     | `fmt"""…"""` with `strformat`    |

Required imports (`subprocess`, `osproc`, `strformat`) are inserted
automatically.

---

## 16. Bash Variables and File Tests

### Command-line arguments

```python
if $# < 2:
    print(f"Usage: {$0} <dict_file> <phone_file>")
    quit(1)

let dict_file:  str = $1
let phone_file: str = $2

for arg in $@:
    print(arg)
```

### Environment variables

All-caps identifiers preceded by `$` read environment variables:

```python
home   = $HOME
editor = $EDITOR
outdir = $HOME + "/output"
```

### File-test operators

```python
if not -f dict_file:
    print(f"Error: {dict_file} not found")
    quit(1)

if -d output_dir:
    shell: ls {output_dir}
elif not -e output_dir:
    shell: mkdir -p {output_dir}

if src -nt dest:     # src is newer than dest
    shell: cp {src} {dest}
```

| Operator    | Meaning                        |
|-------------|-------------------------------|
| `-e path`   | path exists                   |
| `-f path`   | path is a regular file        |
| `-d path`   | path is a directory           |
| `-L path`   | path is a symlink             |
| `-r path`   | path is readable              |
| `-w path`   | path is writable              |
| `-x path`   | path is executable            |
| `-s path`   | path exists and is non-empty  |
| `a -nt b`   | a is newer than b             |
| `a -ot b`   | a is older than b             |

---

## 17. Nim-Only Imports

`nimport` marks imports that appear **only** in Nim output and are stripped
from Python output. Use it for Nim standard-library modules and for
dependencies between Adascript files:

```python
nimport strutils, sequtils, algorithm
nimport stdlib                      # PriorityQueue, FifoQueue, ANY shims
nimport awk                         # AwkBase — bundled record-processor stdlib
nimport shortest_path             # another .ady file compiled as a library
```

When `nimport`-ing another `.ady` file, `py2nim` automatically transpiles
that dependency (if not already cached and up to date) and places both `.nim`
files in the same cache directory, wiring up `--path` for the Nim compiler.

### Bundled Adascript standard libraries

`.ady` files shipped in `TO_NIM/` are automatically installed into the build
cache at compile time, so they can be used via `nimport` from **any directory**
without a local copy next to your source file:

| `nimport`      | Provides                                              |
|----------------|-------------------------------------------------------|
| `nimport stdlib` | `PriorityQueue`, `FifoQueue`, `LifoQueue`, `ANY`    |
| `nimport awk`  | `AwkBase` — subclass and override `process_record()`, `begin()`, `finish()` |

Example — a custom awk processor in any directory:

```python
#!/usr/bin/env py2nim
nimport awk

class WordCounter(AwkBase):
    var word_count: int = 0

    def process_record(self):
        self.word_count += self.NF

    def finish(self):
        print f"total words: {self.word_count}"

var wc: WordCounter = WordCounter()
wc.run()
```

### Splitting a library from its tests

**shortest_path.ady** (the library, decorated with `@virtual`):

```python
#!/usr/bin/env py2nim
#ady2nim-args c --cc:clang --clang.exe:zigcc --clang.linkerexe:zigcc

nimport stdlib

@virtual
class Optimizer[S, D, C]:
    var offset: float
    ...
```

**test_shortest_path.ady** (the test file):

```python
#!/usr/bin/env py2nim
#ady2nim-args c --cc:clang --clang.exe:zigcc --clang.linkerexe:zigcc

nimport stdlib
nimport shortest_path      # triggers auto-transpilation of shortest_path.ady

class MyOptimizer(Optimizer[str, str, float]):
    ...
```

---

## 18. Real Examples

The `EXAMPLES/` directory contains complete programs. Here are annotated
highlights from each.

---

### primes.ady — Range operators and timing

```python
#!/usr/bin/env py2nim
import time

N = 1_000_000

def is_prime(n: int) -> bool:
    for k in 2 .. int(n ** 0.5):    # inclusive range
        if n % k == 0:
            return False
    return True

def count_primes(n: int) -> int:
    count = 0
    for k in 2 ..< n:               # exclusive upper bound
        if is_prime(k):
            count += 1
    return count

start = time.perf_counter()
print f"Number of primes: {count_primes(N)}"
print f"Time elapsed: {time.perf_counter() - start}s"
```

Features: `..` / `..<` range operators, `import time` (→ Nim `times`),
Python-2-style `print`, f-strings.

---

### graph.ady — Type aliases and recursive functions

```python
#!/usr/bin/env py2nim

type Node_T  is str
type Graph_T is {Node_T}[]Node_T    # dict mapping node to list of neighbours

graph: Graph_T = {
    'A': ['B', 'C'],
    'B': ['C', 'D'],
    'C': ['D'],
    'D': ['C'],
}

def find_path(graph: Graph_T, start: Node_T, end: Node_T,
              path: []Node_T = []) -> []Node_T:
    path = path + [start]
    if start == end:
        return path
    if start not in graph:
        return None
    for node in graph[start]:
        if node not in path:
            newpath: []Node_T = find_path(graph, node, end, path)
            if newpath:
                return newpath
    return None

assert find_path(graph, 'A', 'D') == ['A', 'B', 'C', 'D']
print(find_path(graph, 'A', 'D'))
```

Features: type aliases for readability, `{}` and `[]` collections,
`not in`, default parameters.

---

### monty_hall.ady — Enums, sets, tick attributes, case/when

```python
#!/usr/bin/env py2nim

type Door_T   is enum Door1, Door2, Door3
type Choice_T is enum Switch, DontSwitch

def monty_hall_simulation(trials = 100_000):
    var stayWins:   int = 0
    var switchWins: int = 0

    for _ in 1 .. trials:
        let carLocation:          Door_T  = Door_T'Choice
        let candidateFirstChoice: Door_T  = Door_T'Choice
        let availableDoors:       {}Door_T = Door_T'Range - {candidateFirstChoice, carLocation}
        let hostChoice:           Door_T  = availableDoors'Choice
        let switchOptions:        {}Door_T = Door_T'Range - {candidateFirstChoice, hostChoice}

        for choice in Choice_T:
            case choice:
                when DontSwitch:
                    if candidateFirstChoice == carLocation:
                        stayWins += 1
                when Switch:
                    let candidateSecondChoice: Door_T = switchOptions'Choice
                    if candidateSecondChoice == carLocation:
                        switchWins += 1

    print "Trials: ", trials
    print f"Stay:   {stayWins} wins ({stayWins * 100 / trials} %)"
    print f"Switch: {switchWins} wins ({switchWins * 100 / trials} %)"

monty_hall_simulation()
```

Features: enums, ordinal sets (`{}Door_T`), `'Choice` for random selection,
`'Range` for the full set of enum members, set difference (`-`), `case/when`
on enum values, inclusive range `1 .. trials`.

---

### dijkstra.ady — Priority queue, enum-keyed dicts, nimport

```python
#!/usr/bin/env py2nim
nimport stdlib

type Node_T     is enum A, B, C, D
type Distance_T is float
type Graph_T    is {Node_T}{Node_T}Distance_T

const MAX_DIST: float = 1e6

type Neighbour_T is tuple:
    distance: Distance_T
    neighbor: Node_T

def dijkstra(graph: Graph_T, start: Node_T) -> {Node_T}Distance_T:
    distances: {Node_T}Distance_T = {node: MAX_DIST for node in graph if node != start}
    distances[start] = 0.0

    visited: {}Node_T = {}
    queue:   PriorityQueue[Neighbour_T]
    queue.push((0.0, start))

    while queue:
        current_dist, node = queue.pop()
        if node in visited:
            continue
        visited.add(node)
        for neighbor in graph[node]:
            let new_dist: Distance_T = current_dist + graph[node][neighbor]
            if new_dist < distances[neighbor]:
                distances[neighbor] = new_dist
                queue.push((new_dist, neighbor))

    return distances

graph: Graph_T = {A: {B: 1.0, C: 4.0}, B: {C: 2.0, D: 5.0}, C: {D: 1.0}, D: {:}}
print dijkstra(graph, A)
```

Features: `nimport stdlib` for `PriorityQueue`, nested dict type `{K}{K}V`,
enum members as dict keys, `const`, comprehension-initialised dict.

---

### phonecode.ady — Full application structure

A complete solution to Prechelt's phone-code benchmark, demonstrating:

- Enum `Digit_T` as trie index
- `[Digit_T]TrieNode` — fixed-size array indexed by enum
- `?str` optional return type
- Nested function `word_to_digits` inside a method
- `$1`, `$2`, `$#` command-line argument variables
- `-f path` file-test operator
- `with open(…) as f:` file I/O

```python
type Digit_T is enum D0, D1, D2, D3, D4, D5, D6, D7, D8, D9

class TrieNode:
    var children: [Digit_T]TrieNode    # array[Digit_T, TrieNode] in Nim
    var words:    []str

    def find_exact_word(self, digits: []Digit_T) -> ?str:
        var node: TrieNode = self
        for digit in digits:
            if node.children[digit] is None:
                return None
            node = node.children[digit]
        if len(node.words) > 0:
            return node.words[0]
        return None

def main():
    if $# < 2:
        print("Usage: phonecode <dict_file> <phone_file>")
        quit(1)
    let dict_file:  str = $1
    let phone_file: str = $2
    if not -f dict_file:
        print(f"Error: {dict_file} not found")
        quit(1)
    ...
```

---

### shortest_path.ady — Generic framework

A 160-line generic optimiser that becomes 10+ complete algorithm examples
in `test_shortest_path.ady`. The key architectural pattern is **generic
class + `nimport` + subclassing**:

```python
# shortest_path.ady — library
@virtual
class Optimizer[S, D, C]:
    var offset:        float
    var decision_path: []D
    var start_state:   S

    def shortest_path(self, start_state: S, end_state: S, allsolutions: bool = True):
        fringe: PriorityQueue[Fringe_Element_T[S, D, C]] = PriorityQueue(...)
        while fringe:
            let (_, cost, path, current_state) = fringe.pop()
            ...
            if current_state == end_state or self.is_end_state(current_state):
                yield self.real_cost(cost), path

# Methods defined outside the class avoid Nim 2.x generic-method restrictions
def longest_path(self: Optimizer[S, D, C], start_state: S, end_state: S,
                 max_path_length: int = 1000) -> (float, []D):
    ...
```

```python
# test_shortest_path.ady — consumer
nimport shortest_path

def example7():   # Romania map, A* with heuristic
    type State_T    is str
    type Distance_T is float

    class BookMap(Optimizer[State_T, State_T, Distance_T]):
        var G: {State_T}[](State_T, Distance_T) = { 'arad': [('sibiu', 140.0), ...], ... }
        var _heuristic: {State_T}Distance_T = { 'arad': 366.0, 'bucharest': 0.0, ... }

        def get_state(self, past_decisions: []State_T) -> State_T:
            return past_decisions[-1]

        def get_next_decisions(self, curr: State_T) -> [](State_T, Distance_T):
            return self.G.get(curr, [])

        def get_heuristic_cost(self, city: State_T) -> float:
            return self._heuristic.get(city, 0.0)

    op: BookMap = BookMap()
    for solution in op.shortest_path('oradea', 'bucharest'):
        print(solution)
```

---

## Summary of Adascript-Only Syntax

| Feature                           | Adascript syntax                         |
|-----------------------------------|------------------------------------------|
| Mutable variable declaration      | `var x: int = 0`                         |
| Immutable binding                 | `let name: str = "hello"`                |
| Compile-time constant             | `const MAX: int = 1000`                  |
| Enum declaration                  | `type E is enum A, B, C`                 |
| Named tuple declaration           | `type P is tuple: x: float; y: float`   |
| Record declaration                | `type P is record: name: str; age: int` |
| Variant record                    | `type S (Kind: K) is record: case ...`  |
| Subrange type                     | `type T is lo .. hi`                     |
| List type annotation              | `[]T`                                    |
| Dict type annotation              | `{K}V`                                   |
| Set type annotation               | `{}T`                                    |
| Enum-indexed array annotation     | `[E]T`                                   |
| Optional type annotation          | `?T`                                     |
| Inclusive range                   | `lo .. hi`                               |
| Exclusive range                   | `lo ..< hi`                              |
| Enum first/last                   | `E'First`, `E'Last`                      |
| Full enum set                     | `E'Range`                                |
| Successor / predecessor           | `expr'Next`, `expr'Prev`                 |
| Random selection                  | `expr'Choice`                            |
| Empty dict literal                | `{:}`                                    |
| Named tuple literal               | `(field: value, ...)`                    |
| Enum-indexed array literal        | `[KEY: value, ...]`                      |
| Pattern matching                  | `case x: when P: ... when others: ...`  |
| Generator functions               | `def f(): ... yield value`               |
| Field with inline default         | `var x: int = 0` inside class body       |
| Mutable self (auto-detected)      | any `self.field =` / `self.method()`     |
| Cross-module inheritable class    | `@virtual class C: ...`                  |
| Generic class                     | `class C[S, D, C]: ...`                  |
| Nim-only import                   | `nimport module`                         |
| Shell command capture             | `let r = shell: cmd`                     |
| Shell lines capture               | `let ls = shellLines: cmd`               |
| Discard shell output              | `shell: cmd`                             |
| Command-line argument             | `$1`, `$@`, `$#`                         |
| Environment variable              | `$HOME`, `$PATH`                         |
| File-test operator                | `-e path`, `-f path`, `-d path`          |
| File comparison                   | `a -nt b`, `a -ot b`                     |
| Python 2-style print              | `print "text"` or `print expr, expr`    |
