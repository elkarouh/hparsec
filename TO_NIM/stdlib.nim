## stdlib.nim -- Nim support types for HPython transpiled code
## Provides: AnyType/ANY sentinel, FifoQueue, LifoQueue, PriorityQueue

import std/deques
import hashes

# ---------------------------------------------------------------------------
# ANY sentinel -- matches every value via ==
# ---------------------------------------------------------------------------
type AnyType* = object

func `==`*(a: AnyType; b: auto): bool = true
func `==`*(a: auto; b: AnyType): bool = true
func hash*(a: AnyType): int = hash("ANY")
func `$`*(a: AnyType): string = "ANY"

const ANY* = AnyType()

# ---------------------------------------------------------------------------
# FifoQueue (FIFO)
# ---------------------------------------------------------------------------
type FifoQueue*[T] = object
  data: Deque[T]

proc initFifoQueue*[T](): FifoQueue[T] =
  result.data = initDeque[T]()

proc push*[T](q: var FifoQueue[T]; item: T) = q.data.addLast(item)
proc pop*[T](q: var FifoQueue[T]): T = q.data.popFirst()
proc len*[T](q: FifoQueue[T]): int = q.data.len
proc isEmpty*[T](q: FifoQueue[T]): bool = q.data.len == 0

# ---------------------------------------------------------------------------
# LifoQueue (Stack)
# ---------------------------------------------------------------------------
type LifoQueue*[T] = object
  data: Deque[T]

proc initLifoQueue*[T](): LifoQueue[T] =
  result.data = initDeque[T]()

proc push*[T](q: var LifoQueue[T]; item: T) = q.data.addLast(item)
proc pop*[T](q: var LifoQueue[T]): T = q.data.popLast()
proc len*[T](q: LifoQueue[T]): int = q.data.len
proc isEmpty*[T](q: LifoQueue[T]): bool = q.data.len == 0

# ---------------------------------------------------------------------------
# PriorityQueue (min-heap)
# ---------------------------------------------------------------------------
type PriorityQueue*[T] = object
  data: seq[T]

proc initPriorityQueue*[T](): PriorityQueue[T] =
  result.data = @[]

proc swap[T](q: var PriorityQueue[T]; a, b: int) =
  let tmp = q.data[a]
  q.data[a] = q.data[b]
  q.data[b] = tmp

proc siftUp[T](q: var PriorityQueue[T]; i: int) =
  var i = i
  while i > 0:
    let parent = (i - 1) shr 1
    if q.data[i][0] < q.data[parent][0]:
      q.swap(i, parent)
      i = parent
    else: break

proc siftDown[T](q: var PriorityQueue[T]; i: int) =
  let n = q.data.len
  var i = i
  while true:
    var smallest = i
    let l = 2 * i + 1
    let r = 2 * i + 2
    if l < n and q.data[l][0] < q.data[smallest][0]: smallest = l
    if r < n and q.data[r][0] < q.data[smallest][0]: smallest = r
    if smallest == i: break
    q.swap(i, smallest)
    i = smallest

proc push*[T](q: var PriorityQueue[T]; item: T) =
  q.data.add(item)
  q.siftUp(q.data.high)

proc pop*[T](q: var PriorityQueue[T]): T =
  result = q.data[0]
  q.data[0] = q.data[^1]
  q.data.setLen(q.data.high)
  if q.data.len > 0: q.siftDown(0)

proc len*[T](q: PriorityQueue[T]): int = q.data.len
proc isEmpty*[T](q: PriorityQueue[T]): bool = q.data.len == 0

# Convenience constructors with first element (for type inference)
proc newPriorityQueueWith*[T](first: T): PriorityQueue[T] =
  result.data = @[first]

proc newFifoQueueWith*[T](first: T): FifoQueue[T] =
  result.data = initDeque[T]()
  result.data.addLast(first)

proc newLifoQueueWith*[T](first: T): LifoQueue[T] =
  result.data = initDeque[T]()
  result.data.addLast(first)

# Bool converters for Python-style truthiness
converter toBool*[T](q: PriorityQueue[T]): bool = q.data.len > 0
converter toBool*[T](q: FifoQueue[T]): bool = q.data.len > 0
converter toBool*[T](q: LifoQueue[T]): bool = q.data.len > 0
