"""stdlib.py -- Python support types for Adascript transpiled code.
Mirrors stdlib.nim for Nim targets.
Provides: ANY sentinel, PriorityQueue, FifoQueue, LifoQueue.
"""

import heapq
import itertools
from collections import deque


# ---------------------------------------------------------------------------
# ANY sentinel -- matches every value via ==
# ---------------------------------------------------------------------------
class _Any:
    """Singleton wildcard: ANY == x is always True."""
    _instance = None
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    def __eq__(self, _other):
        return True
    def __hash__(self):
        return hash("ANY")
    def __repr__(self):
        return "ANY"

ANY = _Any()


# ---------------------------------------------------------------------------
# Queue implementations
# ---------------------------------------------------------------------------
class PriorityQueue:
    """Min-heap priority queue. Items must support < on their first element."""

    def __init__(self, first=None):
        self._counter = itertools.count()
        self._heap = []
        if first is not None:
            self.push(first)

    def push(self, item):
        heapq.heappush(self._heap, (item[0], next(self._counter), item[1:]))

    def pop(self):
        priority, _count, rest = heapq.heappop(self._heap)
        return (priority,) + rest

    def __bool__(self):
        return bool(self._heap)


class FifoQueue:
    """FIFO queue backed by a deque."""

    def __init__(self, first=None):
        self._dq = deque()
        if first is not None:
            self.push(first)

    def push(self, item):
        self._dq.append(item)

    def pop(self):
        return self._dq.popleft()

    def __bool__(self):
        return bool(self._dq)


class LifoQueue:
    """LIFO (stack) queue."""

    def __init__(self, first=None):
        self._stack = []
        if first is not None:
            self.push(first)

    def push(self, item):
        self._stack.append(item)

    def pop(self):
        return self._stack.pop()

    def __bool__(self):
        return bool(self._stack)
