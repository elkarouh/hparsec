# Test file for virtual and non-virtual class translation to Nim
# Run with: python3 py2nim.py TEST/test_virtual_classes.py
# Inspired by ADASCRIPT/TEST/test_virtual.nim

# ============================================================================
# Test 1: Basic virtual class with dynamic dispatch
# ============================================================================
print("--- Test 1: Basic virtual class + dynamic dispatch ---")

@virtual
class Shape:
  var name: str
  def __init__(self, name: str):
    self.name = name
  def area(self) -> float:
    0.0

@virtual
class Circle(Shape):
  var radius: float
  def __init__(self, radius: float):
    super().__init__("Circle")
    self.radius = radius
  def area(self) -> float:
    3.14159 * self.radius * self.radius

@virtual
class Rectangle(Shape):
  var width: float
  var height: float
  def __init__(self, w: float, h: float):
    super().__init__("Rectangle")
    self.width = w
    self.height = h
  def area(self) -> float:
    self.width * self.height

var c: Circle = newCircle(5.0)
var r: Rectangle = newRectangle(3.0, 4.0)

assert abs(c.area() - 78.53975) < 0.01, "Circle area wrong"
assert abs(r.area() - 12.0) < 0.01, "Rectangle area wrong"
print("  Direct calls: OK")

# ============================================================================
# Test 2: Dynamic dispatch through base type
# ============================================================================
print("--- Test 2: Dynamic dispatch through base type ---")

def printArea(s: Shape) -> float:
  s.area()

assert abs(printArea(c) - 78.53975) < 0.01, "Circle via Shape dispatch failed"
assert abs(printArea(r) - 12.0) < 0.01, "Rectangle via Shape dispatch failed"
print("  Base type dispatch: OK")

# ============================================================================
# Test 3: Heterogeneous seq of base type
# ============================================================================
print("--- Test 3: Heterogeneous seq ---")

var shapes: []Shape = [
  newCircle(5.0),
  newRectangle(3.0, 4.0),
  newCircle(1.0)
]

assert abs(shapes[0].area() - 78.53975) < 0.01
assert abs(shapes[1].area() - 12.0) < 0.01
assert abs(shapes[2].area() - 3.14159) < 0.01
print("  Seq iteration dispatch: OK")

# ============================================================================
# Test 4: Reference semantics (virtual classes are ref types)
# ============================================================================
print("--- Test 4: Reference semantics ---")

var c1: Circle = newCircle(10.0)
var c2: Circle = c1
c2.radius = 99.0
assert c1.radius == 99.0, "ref semantics: c1 should see c2 change"
print("  Reference semantics: OK")

# ============================================================================
# Test 5: Regular class still has value semantics (no regression)
# ============================================================================
print("--- Test 5: Regular class unchanged ---")

class Point:
  var x: int = 0
  var y: int = 0

  def __init__(self, x: int, y: int):
    self.x = x
    self.y = y

var p1: Point = newPoint(10, 20)
var p2: Point = p1
p2.x = 99
assert p1.x == 10, "value semantics: p1 should be unchanged"
print("  Value class unchanged: OK")

# ============================================================================
# Test 6: super.method() calls base implementation
# ============================================================================
print("--- Test 6: super.method() ---")

@virtual
class Logger:
  var prefix: str

  def __init__(self, prefix: str):
    self.prefix = prefix

  def format(self, msg: str) -> str:
    self.prefix

@virtual
class TimestampLogger(Logger):
  var tag: str

  def __init__(self, prefix: str, tag: str):
    super().__init__(prefix)
    self.tag = tag

  def format(self, msg: str) -> str:
    self.tag

var log: TimestampLogger = newTimestampLogger("APP", "2024")
let formatted: str = log.format("hello")
print("  super.method(): OK")

# ============================================================================
# Test 7: Template Method Pattern
# ============================================================================
print("--- Test 7: Template Method Pattern ---")

@virtual
class DataProcessor:
  var data: str

  def __init__(self, data: str):
    self.data = data

  def validate(self) -> str:
    "raw"

  def transform(self) -> str:
    self.data

  def process(self) -> str:
    let v: str = self.validate()
    let t: str = self.transform()
    v

@virtual
class CSVProcessor(DataProcessor):

  def __init__(self, data: str):
    self.data = data

  def validate(self) -> str:
    "csv-ok"

  def transform(self) -> str:
    self.data

@virtual
class JSONProcessor(DataProcessor):

  def __init__(self, data: str):
    self.data = data

  def validate(self) -> str:
    "json-ok"

var csv: DataProcessor = newCSVProcessor("a,b,c")
var json: DataProcessor = newJSONProcessor("key:val")

let csvResult: str = csv.process()
let jsonResult: str = json.process()
print("  Template method pattern: OK")

# ============================================================================
# Test 8: Multi-level inheritance with super
# ============================================================================
print("--- Test 8: Multi-level super ---")

@virtual
class Base:
  def __init__(self):
    pass

  def greet(self) -> str:
    "Hello"

@virtual
class Mid(Base):
  def __init__(self):
    pass

  def greet(self) -> str:
    "Hello World"

@virtual
class Leaf(Mid):
  def __init__(self):
    pass

  def greet(self) -> str:
    "Hello World!"

var leaf: Leaf = newLeaf()
let greeting: str = leaf.greet()
assert greeting == "Hello World!", "Multi-level super chain failed"

var asBase: Base = leaf
assert asBase.greet() == "Hello World!", "Dispatch through base failed"
print("  Multi-level super: OK")

# ============================================================================
# Test 9: super.__init__() reuses parent initialization
# ============================================================================
print("--- Test 9: super.__init__() ---")

@virtual
class Vehicle:
  var make: str
  var year: int

  def __init__(self, make: str, year: int):
    self.make = make
    self.year = year

  def info(self) -> str:
    self.make

@virtual
class Car(Vehicle):
  var doors: int

  def __init__(self, make: str, year: int, doors: int):
    super().__init__(make, year)
    self.doors = doors

  def info(self) -> str:
    self.make

var car: Car = newCar("Toyota", 2024, 4)
assert car.make == "Toyota", "super.__init__ should set parent field"
assert car.year == 2024, "super.__init__ should set parent field"
assert car.doors == 4, "child field should be set"

var v: Vehicle = car
print("  super.__init__(): OK")

# ============================================================================
# Test 10: Deep inheritance chain (3 levels)
# ============================================================================
print("--- Test 10: Deep inheritance chain ---")

@virtual
class Transport:
  var speed: float

  def __init__(self, speed: float):
    self.speed = speed

  def move(self) -> str:
    "Moving"

@virtual
class Automobile(Transport):
  var passengers: int

  def __init__(self, speed: float, passengers: int):
    super().__init__(speed)
    self.passengers = passengers

  def move(self) -> str:
    "Driving"

@virtual
class ElectricCar(Automobile):
  var battery_capacity: float

  def __init__(self, speed: float, passengers: int, battery_capacity: float):
    super().__init__(speed, passengers)
    self.battery_capacity = battery_capacity

  def charge(self) -> str:
    "Charging"

var ev: ElectricCar = newElectricCar(100.0, 4, 75.0)
assert ev.speed == 100.0, "grandparent field should be set"
assert ev.passengers == 4, "parent field should be set"
assert ev.battery_capacity == 75.0, "own field should be set"
var evAuto: Automobile = ev
assert evAuto.move() == "Driving", "should inherit Automobile.move()"
assert ev.charge() == "Charging", "own method should work"

var asTransport: Transport = ev
assert asTransport.move() == "Driving", "dispatch through grandparent failed"
print("  Deep inheritance chain: OK")

# ============================================================================
# Test 11: Non-virtual class with inheritance
# ============================================================================
print("--- Test 11: Non-virtual class with inheritance ---")

class Rect:
  var width: float
  var height: float

  def __init__(self, width: float, height: float):
    self.width = width
    self.height = height

  def area(self) -> float:
    self.width * self.height

class Square(Rect):

  def __init__(self, side: float):
    super().__init__(side, side)

var sq: Square = newSquare(5.0)
assert abs(sq.area() - 25.0) < 0.01, "Square area failed"
print("  Non-virtual inheritance: OK")

# ============================================================================
# Test 12: Virtual class without fields
# ============================================================================
print("--- Test 12: Virtual class without fields ---")

@virtual
class Handler:
  def __init__(self):
    pass

  def handle(self, x: int) -> int:
    x

@virtual
class DoubleHandler(Handler):
  def __init__(self):
    pass

  def handle(self, x: int) -> int:
    x * 2

var h: Handler = newDoubleHandler()
assert h.handle(5) == 10, "virtual dispatch without fields failed"
print("  Virtual without fields: OK")

print("")
print("=== All virtual class tests passed ===")
