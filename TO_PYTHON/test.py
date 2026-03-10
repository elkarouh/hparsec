# ============================================================================
# Test 1: Basic class with dynamic dispatch
# ============================================================================
print("--- Test 1: Basic class + dynamic dispatch ---")
@virtual
class Shape:
  var name: string

  def init(self, name: string):
    self.name = name

  def area(self) -> float:
    0.0

  def describe(self) -> string:
    f"{self.name}: area= {self.area()}" #  {self.area()} should translate to $self.area()
@virtual
class Circle(Shape):
  var radius: float

  def init(self, radius: float):
    super.init("Circle")   # initialize parent fields
    self.radius = radius

  def area(self) -> float:
    3.14159 * self.radius * self.radius
@virtual
class Rectangle(Shape):
  var width, height: float

  def init(self, w: float, h: float):
    super.init("Rectangle")  # initialize parent fields
    self.width = w
    self.height = h

  def area(self) -> float:
    self.width * self.height

var c = newCircle(5.0)
var r = newRectangle(3.0, 4.0)

assert abs(c.area() - 78.53975) < 0.01, "Circle area wrong"
assert abs(r.area() - 12.0) < 0.01, "Rectangle area wrong"
print("  Direct calls: OK")

# ============================================================================
# Test 2: Dynamic dispatch through base type
# ============================================================================
print("--- Test 2: Dynamic dispatch through base type ---")

def printArea(s: Shape) -> float:
  s.area()

# These should dispatch to the derived area() at runtime
assert abs(printArea(c) - 78.53975) < 0.01, "Circle via Shape should dispatch to Circle.area()"
assert abs(printArea(r) - 12.0) < 0.01, "Rectangle via Shape should dispatch to Rectangle.area()"
print("  Base type dispatch: OK")

# ============================================================================
# Test 3: Heterogeneous seq of base type
# ============================================================================
print("--- Test 3: Heterogeneous seq ---")

var shapes: []Shape = @[
  newCircle(5.0).Shape,
  newRectangle(3.0, 4.0).Shape,
  newCircle(1.0).Shape
]

assert abs(shapes[0].area() - 78.53975) < 0.01
assert abs(shapes[1].area() - 12.0) < 0.01
assert abs(shapes[2].area() - 3.14159) < 0.01
print("  Seq iteration dispatch: OK")

# ============================================================================
# Test 4: describe() calls area() polymorphically
# ============================================================================
print("--- Test 4: Cross-method virtual dispatch ---")

# describe() is defined in Shape but calls self.area() which should dispatch
let circleDesc = c.describe()
let rectDesc = r.describe()
assert "78.5397" in circleDesc, "describe should use Circle.area(): got " & circleDesc
assert "12.0" in rectDesc, "describe should use Rectangle.area(): got " & rectDesc
print("  Cross-method dispatch: OK")

# =============================@virtual===============================================
# Test 5: Reference semantics (classes are ref types)
# ============================================================================
print("--- Test 5: Reference semantics ---")

var c1 = newCircle(10.0)
var c2 = c1  # reference copy, not value copy
c2.radius = 99.0
assert c1.radius == 99.0, "ref semantics: c1 should see c2's change"
print("  Reference semantics: OK")

# ============================================================================
# Test 6: Regular class still has value semantics (no regression)
# ============================================================================
print("--- Test 6: Regular class unchanged ---")

class Point:
  var x, y: int
  def init(self, x: int, y: int):
    self.x = x
    self.y = y

var p1 = newPoint(10, 20)
var p2 = p1  # value copy
p2.x = 99
assert p1.x == 10, "value semantics: p1 should be unchanged"
print("  Value class unchanged: OK")

# ============================================================================
# Test 7: super.method() calls base implementation
# ============================================================================
print("--- Test 7: super.method() ---")
@virtual
class Logger:
  var prefix: string

  def init(self, prefix: string):
    self.prefix = prefix

  def format(self, msg: string) -> string:
    self.prefix & ": " & msg
@virtual
class TimestampLogger(Logger):
  var tag: string

  def init(self, prefix: string, tag: string):
    super.init(prefix)   # reuse parent's init
    self.tag = tag

  def format(self, msg: string) -> string:
    "[" & self.tag & "] " & super.format(msg)

var log = newTimestampLogger("APP", "2024")
let formatted = log.format("hello")
assert formatted == "[2024] APP: hello", "super.format() should call Logger.format(): got " & formatted

# Also works through base type
def doFormat(l: Logger, msg: string) -> string:
  l.format(msg)

let viaBase = doFormat(log, "world")
assert viaBase == "[2024] APP: world", "dispatch through base + super: got " & viaBase
print("  super.method(): OK")

# ============================================================================
# Test 8: Template Method Pattern
# ============================================================================
print("--- Test 8: Template Method Pattern ---")
@virtual
class DataProcessor:
  var data: string

  def init(self, data: string):
    self.data = data

  def validate(self) -> string:
    "raw"

  def transform(self) -> string:
    self.data

  def format(self) -> string:
    self.data

  # Template method: defines the algorithm skeleton
  def process(self) -> string:
    let v = self.validate()
    let t = self.transform()
    let f = self.format()
    "[" & v & "] {" & t & "} (" & f & ")"
@virtual
class CSVProcessor(DataProcessor):
  def init(self, data: string):
    self.data = data

  def validate(self) -> string:
    "csv-ok"

  def transform(self) -> string:
    self.data.toUpperAscii()
@virtual
class JSONProcessor(DataProcessor):
  def init(self, data: string):
    self.data = data

  def validate(self) -> string:
    "json-ok"

  def format(self) -> string:
    "{" & self.data & "}"

# Template method dispatches to overrides
var csv: DataProcessor = newCSVProcessor("a,b,c")
var json: DataProcessor = newJSONProcessor("key:val")

let csvResult = csv.process()
assert csvResult == "[csv-ok] {A,B,C} (a,b,c)", "CSV template method: got " & csvResult

let jsonResult = json.process()
assert jsonResult == "[json-ok] {key:val} ({key:val})", "JSON template method: got " & jsonResult
print("  Template method pattern: OK")

# ============================================================================
# Test 9: Multi-level inheritance with super
# ============================================================================
print("--- Test 9: Multi-level super ---")
@virtual
class Base:
  def init(self):
    discard

  def greet(self) -> string:
    "Hello"
@virtual
class Mid(Base):
  def init(self):
    discard

  def greet(self) -> string:
    super.greet() & " World"
@virtual
class Leaf(Mid):
  def init(self):
    discard

  def greet(self) -> string:
    super.greet() & "!"

var leaf = newLeaf()
let greeting = leaf.greet()
assert greeting == "Hello World!", "Multi-level super chain: got " & greeting

var asBase: Base = leaf
assert asBase.greet() == "Hello World!", "Dispatch through base: got " & asBase.greet()
print("  Multi-level super: OK")

# ============================================================================
# Test 10: super.init() reuses parent initialization (no double allocation)
# ============================================================================
print("--- Test 10: super.init() ---")
@virtual
class Vehicle:
  var make: string
  var year: int

  def init(self, make: string, year: int):
    self.make = make
    self.year = year

  def info(self) -> string:
    self.make & " (" & $self.year & ")"
@virtual
class Car(Vehicle):
  var doors: int

  def init(self, make: string, year: int, doors: int):
    super.init(make, year)  # reuse parent init
    self.doors = doors

  def info(self) -> string:
    super.info() & " " & $self.doors & "-door"

var car = newCar("Toyota", 2024, 4)
assert car.make == "Toyota", "super.init should set parent field: got " & car.make
assert car.year == 2024, "super.init should set parent field"
assert car.doors == 4, "child field should be set"
assert car.info() == "Toyota (2024) 4-door", "got " & car.info()

# Through base type
var v: Vehicle = car
assert v.info() == "Toyota (2024) 4-door", "dispatch through base: got " & v.info()
print("  super.init(): OK")

print("")@virtual
print("=== All class tests passed ===")
