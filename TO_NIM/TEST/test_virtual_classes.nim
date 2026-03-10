# Test file for virtual and non-virtual class translation to Nim
# Run with: python3 py2nim.py TEST/test_virtual_classes.py
# Inspired by ADASCRIPT/TEST/test_virtual.nim

# ============================================================================
# Test 1: Basic virtual class with dynamic dispatch
# ============================================================================
echo("--- Test 1: Basic virtual class + dynamic dispatch ---")

type Shape = ref object of RootObj
    name: string

proc initShape(self: Shape, name: string) =
    self.name = name
proc newShape*(name: string): Shape =
    new(result)
    initShape(result, name)
method area(self: Shape): float {.base.} =
    0.0

type Circle = ref object of Shape
    radius: float

proc initCircle(self: Circle, radius: float) =
    initShape(self, "Circle")
    self.radius = radius
proc newCircle*(radius: float): Circle =
    new(result)
    initCircle(result, radius)
method area(self: Circle): float =
    3.14159 * self.radius * self.radius

type Rectangle = ref object of Shape
    width: float
    height: float

proc initRectangle(self: Rectangle, w: float, h: float) =
    initShape(self, "Rectangle")
    self.width = w
    self.height = h
proc newRectangle*(w: float, h: float): Rectangle =
    new(result)
    initRectangle(result, w, h)
method area(self: Rectangle): float =
    self.width * self.height

var c: Circle = newCircle(5.0)
var r: Rectangle = newRectangle(3.0, 4.0)

assert abs(c.area() - 78.53975) < 0.01, "Circle area wrong"
assert abs(r.area() - 12.0) < 0.01, "Rectangle area wrong"
echo("  Direct calls: OK")

# ============================================================================
# Test 2: Dynamic dispatch through base type
# ============================================================================
echo("--- Test 2: Dynamic dispatch through base type ---")

proc printArea(s: Shape): float =
    s.area()

assert abs(printArea(c) - 78.53975) < 0.01, "Circle via Shape dispatch failed"
assert abs(printArea(r) - 12.0) < 0.01, "Rectangle via Shape dispatch failed"
echo("  Base type dispatch: OK")

# ============================================================================
# Test 3: Heterogeneous seq of base type
# ============================================================================
echo("--- Test 3: Heterogeneous seq ---")

var shapes: seq[Shape] = @[newCircle(5.0), newRectangle(3.0, 4.0), newCircle(1.0)]

assert abs(shapes[0].area() - 78.53975) < 0.01
assert abs(shapes[1].area() - 12.0) < 0.01
assert abs(shapes[2].area() - 3.14159) < 0.01
echo("  Seq iteration dispatch: OK")

# ============================================================================
# Test 4: Reference semantics (virtual classes are ref types)
# ============================================================================
echo("--- Test 4: Reference semantics ---")

var c1: Circle = newCircle(10.0)
var c2: Circle = c1
c2.radius = 99.0
assert c1.radius == 99.0, "ref semantics: c1 should see c2 change"
echo("  Reference semantics: OK")

# ============================================================================
# Test 5: Regular class still has value semantics (no regression)
# ============================================================================
echo("--- Test 5: Regular class unchanged ---")

type Point = object of RootObj
    x: int = 0
    y: int = 0

proc initPoint(self: var Point, x: int, y: int) =
    self.x = x
    self.y = y

proc newPoint*(x: int, y: int): Point =
    initPoint(result, x, y)
var p1: Point = newPoint(10, 20)
var p2: Point = p1
p2.x = 99
assert p1.x == 10, "value semantics: p1 should be unchanged"
echo("  Value class unchanged: OK")

# ============================================================================
# Test 6: super.method() calls base implementation
# ============================================================================
echo("--- Test 6: super.method() ---")

type Logger = ref object of RootObj
    prefix: string

proc initLogger(self: Logger, prefix: string) =
    self.prefix = prefix

proc newLogger*(prefix: string): Logger =
    new(result)
    initLogger(result, prefix)
method format(self: Logger, msg: string): string {.base.} =
    self.prefix

type TimestampLogger = ref object of Logger
    tag: string

proc initTimestampLogger(self: TimestampLogger, prefix: string, tag: string) =
    initLogger(self, prefix)
    self.tag = tag

proc newTimestampLogger*(prefix: string, tag: string): TimestampLogger =
    new(result)
    initTimestampLogger(result, prefix, tag)
method format(self: TimestampLogger, msg: string): string =
    self.tag

var log: TimestampLogger = newTimestampLogger("APP", "2024")
let formatted: string = log.format("hello")
echo("  super.method(): OK")

# ============================================================================
# Test 7: Template Method Pattern
# ============================================================================
echo("--- Test 7: Template Method Pattern ---")

type DataProcessor = ref object of RootObj
    data: string

proc initDataProcessor(self: DataProcessor, data: string) =
    self.data = data

proc newDataProcessor*(data: string): DataProcessor =
    new(result)
    initDataProcessor(result, data)
method validate(self: DataProcessor): string {.base.} =
    "raw"

method transform(self: DataProcessor): string {.base.} =
    self.data

method process(self: DataProcessor): string {.base.} =
    let v: string = self.validate()
    let t: string = self.transform()
    v

type CSVProcessor = ref object of DataProcessor
proc initCSVProcessor(self: CSVProcessor, data: string) =
    self.data = data

proc newCSVProcessor*(data: string): CSVProcessor =
    new(result)
    initCSVProcessor(result, data)
method validate(self: CSVProcessor): string =
    "csv-ok"

method transform(self: CSVProcessor): string =
    self.data

type JSONProcessor = ref object of DataProcessor
proc initJSONProcessor(self: JSONProcessor, data: string) =
    self.data = data

proc newJSONProcessor*(data: string): JSONProcessor =
    new(result)
    initJSONProcessor(result, data)
method validate(self: JSONProcessor): string =
    "json-ok"

var csv: DataProcessor = newCSVProcessor("a,b,c")
var json: DataProcessor = newJSONProcessor("key:val")

let csvResult: string = csv.process()
let jsonResult: string = json.process()
echo("  Template method pattern: OK")

# ============================================================================
# Test 8: Multi-level inheritance with super
# ============================================================================
echo("--- Test 8: Multi-level super ---")

type Base = ref object of RootObj
proc initBase(self: Base) =
    discard

proc newBase*(): Base =
    new(result)
    initBase(result)
method greet(self: Base): string {.base.} =
    "Hello"

type Mid = ref object of Base
proc initMid(self: Mid) =
    discard

proc newMid*(): Mid =
    new(result)
    initMid(result)
method greet(self: Mid): string =
    "Hello World"

type Leaf = ref object of Mid
proc initLeaf(self: Leaf) =
    discard

proc newLeaf*(): Leaf =
    new(result)
    initLeaf(result)
method greet(self: Leaf): string =
    "Hello World!"

var leaf: Leaf = newLeaf()
let greeting: string = leaf.greet()
assert greeting == "Hello World!", "Multi-level super chain failed"

var asBase: Base = leaf
assert asBase.greet() == "Hello World!", "Dispatch through base failed"
echo("  Multi-level super: OK")

# ============================================================================
# Test 9: super.__init__() reuses parent initialization
# ============================================================================
echo("--- Test 9: super.__init__() ---")

type Vehicle = ref object of RootObj
    make: string
    year: int

proc initVehicle(self: Vehicle, make: string, year: int) =
    self.make = make
    self.year = year

proc newVehicle*(make: string, year: int): Vehicle =
    new(result)
    initVehicle(result, make, year)
method info(self: Vehicle): string {.base.} =
    self.make

type Car = ref object of Vehicle
    doors: int

proc initCar(self: Car, make: string, year: int, doors: int) =
    initVehicle(self, make, year)
    self.doors = doors

proc newCar*(make: string, year: int, doors: int): Car =
    new(result)
    initCar(result, make, year, doors)
method info(self: Car): string =
    self.make

var car: Car = newCar("Toyota", 2024, 4)
assert car.make == "Toyota", "super.__init__ should set parent field"
assert car.year == 2024, "super.__init__ should set parent field"
assert car.doors == 4, "child field should be set"

var v: Vehicle = car
echo("  super.__init__(): OK")

# ============================================================================
# Test 10: Deep inheritance chain (3 levels)
# ============================================================================
echo("--- Test 10: Deep inheritance chain ---")

type Transport = ref object of RootObj
    speed: float

proc initTransport(self: Transport, speed: float) =
    self.speed = speed

proc newTransport*(speed: float): Transport =
    new(result)
    initTransport(result, speed)
method move(self: Transport): string {.base.} =
    "Moving"

type Automobile = ref object of Transport
    passengers: int

proc initAutomobile(self: Automobile, speed: float, passengers: int) =
    initTransport(self, speed)
    self.passengers = passengers

proc newAutomobile*(speed: float, passengers: int): Automobile =
    new(result)
    initAutomobile(result, speed, passengers)
method move(self: Automobile): string =
    "Driving"

type ElectricCar = ref object of Automobile
    battery_capacity: float

proc initElectricCar(self: ElectricCar, speed: float, passengers: int, battery_capacity: float) =
    initAutomobile(self, speed, passengers)
    self.battery_capacity = battery_capacity

proc newElectricCar*(speed: float, passengers: int, battery_capacity: float): ElectricCar =
    new(result)
    initElectricCar(result, speed, passengers, battery_capacity)
method charge(self: ElectricCar): string {.base.} =
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
echo("  Deep inheritance chain: OK")

# ============================================================================
# Test 11: Non-virtual class with inheritance
# ============================================================================
echo("--- Test 11: Non-virtual class with inheritance ---")

type Rect = object of RootObj
    width: float
    height: float

proc initRect(self: var Rect, width: float, height: float) =
    self.width = width
    self.height = height

proc newRect*(width: float, height: float): Rect =
    initRect(result, width, height)
proc area(self: Rect): float =
    self.width * self.height

type Square = object of Rect
proc initSquare(self: var Square, side: float) =
    initRect(self, side, side)

proc newSquare*(side: float): Square =
    initSquare(result, side)
var sq: Square = newSquare(5.0)
assert abs(sq.area() - 25.0) < 0.01, "Square area failed"
echo("  Non-virtual inheritance: OK")

# ============================================================================
# Test 12: Virtual class without fields
# ============================================================================
echo("--- Test 12: Virtual class without fields ---")

type Handler = ref object of RootObj
proc initHandler(self: Handler) =
    discard

proc newHandler*(): Handler =
    new(result)
    initHandler(result)
method handle(self: Handler, x: int): int {.base.} =
    x

type DoubleHandler = ref object of Handler
proc initDoubleHandler(self: DoubleHandler) =
    discard

proc newDoubleHandler*(): DoubleHandler =
    new(result)
    initDoubleHandler(result)
method handle(self: DoubleHandler, x: int): int =
    x * 2

var h: Handler = newDoubleHandler()
assert h.handle(5) == 10, "virtual dispatch without fields failed"
echo("  Virtual without fields: OK")

echo("")
echo("=== All virtual class tests passed ===")
