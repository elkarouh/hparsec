# HPython Language

HPython is a superset of Python with Ada/Nim-inspired type system features. It transpiles to both **Python 3** and **Nim**, letting you write statically-typed code in a familiar Python syntax.

## Quick Example

```python
nimport sequtils

type Stage_T is enum STAGE1, STAGE2, STAGE3

type Choice_T is tuple:
    weight: int
    benefit: int

type State_T is tuple:
    stage: Stage_T
    budget: float

var items: [Stage_T]Choice_T = [
    STAGE1: (weight:2, benefit:65),
    STAGE2: (weight:3, benefit:80),
    STAGE3: (weight:1, benefit:30)
]

for s in Stage_T'First .. Stage_T'Last:
    let choice: Choice_T = items[s]
    print(f"Stage {s}: weight={choice.weight}, benefit={choice.benefit}")
```

## Type Annotations

HPython uses a concise left-to-right annotation syntax instead of Python's `typing` module.

| HPython | Python | Nim |
|---------|--------|-----|
| `[]T` | `list[T]` | `seq[T]` |
| `[N]T` | `tuple[T, ...]` | `array[N, T]` |
| `[*]T` | `Sequence[T]` | `openArray[T]` |
| `[E]T` | `dict[E, T]` | `array[E, T]` (enum-indexed) |
| `{K}V` | `dict[K, V]` | `Table[K, V]` |
| `{}T` | `set[T]` | `HashSet[T]` |
| `?T` | `T \| None` | `Option[T]` |
| `(T, U)` | `tuple[T, U]` | `(T, U)` |
| `[(T, U)]R` | `Callable[[T, U], R]` | `proc(a0: T, a1: U): R` |

```python
var words: []str = ["hello", "world"]
var counts: {str}int = {"hello": 1}
var maybe: ?int = None
var matrix: [][]float = [[1.0, 2.0], [3.0, 4.0]]
```

## Type Declarations

### Enums

```python
type Color is enum RED, GREEN, BLUE
type Digit_T = enum D0, D1, D2, D3, D4, D5, D6, D7, D8, D9
```

### Subranges

```python
type SmallInt is 0 .. 255
type Index is 0 ..< 10
```

### Named Tuples

```python
type Point is tuple:
    x: int
    y: int
```

### Records (Dataclasses)

```python
type Person is record:
    name: str
    age: int
```

### Discriminated Records (Variant Types)

Ada/Nim-style variant records where fields depend on an enum discriminant:

```python
type Shape_Kind is enum Circle, Rectangle

type Shape (Kind : Shape_Kind) is record:
    case Kind is
        when Circle:
            Radius : float
        when Rectangle:
            Width : float
            Height : float
```

**Nim output:**
```nim
type Shape = object
    case Kind: ShapeKind
    of Circle:
        Radius: float
    of Rectangle:
        Width: float
        Height: float
```

**Python output (flattened with defaults):**
```python
@dataclass
class Shape:
    Kind: Shape_Kind
    Radius: float = None
    Width: float = None
    Height: float = None
```

## Variable Declarations

```python
var x: int = 10          # Mutable
let name: str = "hello"  # Immutable
const MAX: int = 1000    # Compile-time constant
```

Tuple unpacking:
```python
let (x, y) = point
var (a, b) = (1, 2)
```

## Range Expressions

```python
for i in 0 .. 10:        # 0 to 10 inclusive
    pass

for i in 0 ..< 10:       # 0 to 9 (exclusive upper bound)
    pass

if x in 1 .. 100:        # Range check
    pass
```

## Case/When Statements

Pattern matching with Ada/Nim-inspired syntax:

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

Supports guards, enum patterns, sequence patterns, mapping patterns, class patterns, and `as` bindings — the full Python `match/case` pattern set.

## Tick Attributes

Ada-style attributes for enums and subranges:

```python
type Stage_T is enum A, B, C

Stage_T'First            # First member (A)
Stage_T'Last             # Last member (C)
current'Next             # Next value (succ)
current'Prev             # Previous value (pred)
```

## Enum Array Literals

Arrays indexed by enum members use `[KEY: value]` syntax:

```python
var costs: [Stage_T]int = [A: 10, B: 20, C: 30]
```

## Named Tuple Literals

Construct named tuples with `(field: value)` syntax:

```python
type Point is tuple:
    x: int
    y: int

p = Point(x: 10, y: 20)
```

## Classes and Inheritance

Standard Python class syntax with automatic virtual dispatch:

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

In Nim, classes with inheritance are emitted as `ref object` types with method dispatch.

### Generic Classes

```python
class Optimizer[S, D]:
    var offset: float

    def __init__(self, offset: float = 0.0):
        self.offset = offset

    def evaluate(self, state: S) -> float:
        return 0.0
```

## Nim-Only Imports

Use `nimport` for imports that only appear in Nim output (stripped from Python):

```python
nimport strutils, sequtils
```

## Transpilation

```
hpython_source.hpy
       |
       +---> python3 TO_PYTHON/py2py.py source.hpy   --> Python 3
       |
       +---> python3 TO_NIM/py2nim.py source.hpy      --> Nim
```

HPython is a superset of Python — all valid Python 3.14 code is valid HPython. The additional features provide static typing and Ada/Nim-inspired constructs while maintaining Python's readability.
