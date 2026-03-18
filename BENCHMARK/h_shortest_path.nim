## Shortest-path / dynamic-programming optimiser framework.
## 
## ALL DYNAMIC PROGRAMMING PROBLEMS CAN BE TRANSFORMED INTO SHORTEST-PATH PROBLEMS
## UNDER THE CONDITION THAT for each decision there is only ONE next state.

import math, sets, sugar, tables
import stdlib
import math



# ---------------------------------------------------------------------------
# Core Optimizer
# ---------------------------------------------------------------------------
type Cost_T = float
type Fringe_Element_T[S, D] = tuple
    hcost: float
    new_cost: float
    new_path: seq[D]
    next_state: S
type Optimizer[S, D] = ref object of RootObj
    offset: float
    decision_path: seq[D]
    start_state: S

proc initOptimizer[S, D](self: Optimizer[S, D], offset: float = 0.0) =
    self.offset = offset

proc newOptimizer*[S, D](offset: float = 0.0): Optimizer[S, D] =
    new(result)
    initOptimizer(result, offset)
type State_T = string
type Decision_T = State_T
type MyOptimizer = ref object of Optimizer[State_T, Decision_T]
    G: Table[State_T, seq[(Decision_T, Cost_T)]]

proc newMyOptimizer(): MyOptimizer =
    new(result)
    result.G = {"s": @[("u", 10.0), ("x", 5.0)], "u": @[("v", 1.0), ("x", 2.0)], "v": @[("y", 4.0)], "x": @[("u", 3.0), ("v", 9.0), ("y", 2.0)], "y": @[("s", 7.0), ("v", 6.0)]}.toTable
method get_state(self: Optimizer[State_T, Decision_T], past_decisions: seq[Decision_T]): State_T {.base.} =
    raise newException(CatchableError, "Override get_state()")

method get_next_decisions(self: Optimizer[State_T, Decision_T], current_state: State_T): seq[(Decision_T, Cost_T)] {.base.} =
    raise newException(CatchableError, "Override get_next_decisions()")

method get_heuristic_cost(self: Optimizer[State_T, Decision_T], current_state: State_T): float {.base.} =
    return 0.0

method cost_operator(self: Optimizer[State_T, Decision_T], accumulated: Cost_T, step_cost: Cost_T): Cost_T {.base.} =
    var actual_cost: Cost_T = step_cost + self.offset
    assert actual_cost >= 0
    return accumulated + actual_cost

proc hcost_operator(self: Optimizer[State_T, Decision_T], past_cost: Cost_T, current_state: State_T): Cost_T =
    return past_cost + self.get_heuristic_cost(current_state)

proc real_cost(self: Optimizer[State_T, Decision_T], cost: Cost_T): Cost_T =
    return cost - self.offset * float(len(self.decision_path))

method is_end_state(self: Optimizer[State_T, Decision_T], state: State_T): bool {.base.} =
    return false

iterator shortest_path(self: Optimizer[State_T, Decision_T], start_state: State_T, end_state: State_T, allsolutions: bool = true): auto =
    self.start_state = start_state
    var empty_path: seq[Decision_T] = @[]
    var fringe: PriorityQueue[Fringe_Element_T[State_T, Decision_T]] = newPriorityQueueWith((0.0, 0.0, empty_path, start_state))
    var visited: HashSet[State_T] = initHashSet[State_T]()

    while fringe.len > 0:
        var item = fringe.pop()
        var cost: float = item[1]
        var path: seq[Decision_T] = item[2]
        var current_state: State_T = item[3]

        if not allsolutions and current_state in visited:
            continue

        self.decision_path = path
        visited.incl(current_state)

        if current_state == end_state or self.is_end_state(current_state):
            yield (self.real_cost(cost), path)
            if not allsolutions:
                break

        for (new_decision, step_cost) in self.get_next_decisions(current_state):
            var new_path: seq[Decision_T] = path & @[new_decision]
            var next_state: State_T = self.get_state(new_path)
            if next_state notin visited:
                var new_cost: float = self.cost_operator(cost, step_cost)
                var hcost: float = self.hcost_operator(new_cost, next_state)
                fringe.push((hcost, new_cost, new_path, next_state))

    # ------------------------------------------------------------------
    # Generic traversal (BFS / DFS / best-first)
    # ------------------------------------------------------------------

proc visit_state(self: Optimizer[State_T, Decision_T], state: var State_T): void =
    echo("state =", state)

proc longest_path_min(self: Optimizer[State_T, Decision_T], end_state: State_T, excluded_lengths: seq[int] = @[], offset: float = 1000.0): (float, seq[Decision_T]) =
    var excluded: HashSet[int] = excluded_lengths.toHashSet()
    var empty_path: seq[Decision_T] = @[]
    var fringe = newPriorityQueueWith((0.0, empty_path, self.start_state))
    var visited: Table[State_T, float] = initTable[State_T, float]()
    var solution: (float, seq[Decision_T]) = (0.0, @[])

    while fringe:
        var item = fringe.pop()
        var cost: float = item[0]
        var path: seq[Decision_T] = item[1]
        var current_state: State_T = item[2]
        var real_revenue: float = float(len(path)) * offset - cost

        if current_state in visited and real_revenue <= visited[current_state]:
            continue
        visited[current_state] = real_revenue

        if current_state == end_state:
            return (real_revenue, path)

        for (new_decision, revenue) in self.get_next_decisions(current_state):
            var new_path: seq[Decision_T] = path & @[new_decision]
            var next_state: State_T = self.get_state(new_path)
            var cost_step: float = -revenue + offset
            assert cost_step > 0
            var new_cost: float = cost + cost_step
            var new_real: float = float(len(new_path)) * offset - new_cost

            var penalty: float = 0.0
            if len(new_path) in excluded and next_state == end_state:
                penalty = 100000.0

            if next_state notin visited or new_real > visited[next_state]:
                fringe.push((new_cost + penalty, new_path, next_state))

    return solution

proc longest_path(self: Optimizer[State_T, Decision_T], start_state: State_T, end_state: State_T, max_path_length: int = 1000, offset: float = 1000.0): (float, seq[Decision_T]) =
    self.start_state = start_state
    let (revenue, path) = self.longest_path_min(end_state, offset = offset)
    if len(path) == 0:
        return (0.0, path)

    var excluded: seq[int] = @[len(path)]
    var best_revenue: float = revenue
    var best_path: seq[Decision_T] = path

    while true:
        let (new_revenue, new_path) = self.longest_path_min(end_state, excluded_lengths = excluded, offset = offset)
        if len(new_path) == 0 or len(new_path) <= len(best_path):
            break
        if len(new_path) > max_path_length:
            break
        excluded.add(len(new_path))
        if new_revenue > best_revenue:
            best_revenue = new_revenue
            best_path = new_path

    return (best_revenue, best_path)

method get_state(self: MyOptimizer, past_decisions: seq[Decision_T]): State_T =
    return past_decisions[^1]

method get_next_decisions(self: MyOptimizer, curr_state: State_T): seq[(Decision_T, Cost_T)] =
    return (self.G.getOrDefault(curr_state, @[]))

proc example1() =  # ===========================================================================
    # -----------------------------------------------------------------------
    # Example 1 -- simple weighted graph (Dijkstra / longest path)
    # -----------------------------------------------------------------------
    var op: MyOptimizer = newMyOptimizer()
    var solution: (Cost_T, seq[Decision_T]) = op.longest_path("s", "v", max_path_length = 4)
    echo("Longest path s->v:", solution)

type State_T_2 = string
type Cost_T_2 = float
type Decision_T_2 = State_T_2
type MyOptimizer2 = ref object of Optimizer[State_T_2, Decision_T_2]
    G: Table[State_T_2, seq[(Decision_T_2, Cost_T_2)]]

proc newMyOptimizer2(): MyOptimizer2 =
    new(result)
    result.G = {"a": @[("b", 2.0), ("c", 4.0), ("d", 3.0)], "b": @[("e", 7.0), ("f", 4.0), ("g", 6.0)], "c": @[("e", 3.0), ("f", 2.0), ("g", 4.0)], "d": @[("e", 4.0), ("f", 1.0), ("g", 5.0)], "e": @[("h", 1.0), ("i", 4.0)], "f": @[("h", 6.0), ("i", 3.0)], "g": @[("h", 3.0), ("i", 3.0)], "h": @[("j", 3.0)], "i": @[("j", 4.0)]}.toTable
method get_state(self: MyOptimizer2, past_decisions: seq[Decision_T_2]): State_T_2 =
    return past_decisions[^1]

method get_next_decisions(self: MyOptimizer2, curr_state: State_T_2): seq[(Decision_T_2, Cost_T_2)] =
    return (self.G.getOrDefault(curr_state, @[]))

proc example2() =
    # -----------------------------------------------------------------------
    # Example 2 -- DP tutorial graph
    # -----------------------------------------------------------------------
    echo("======= SHORTEST a->j =======")
    var op2: MyOptimizer2 = newMyOptimizer2()
    for solution in op2.shortest_path("a", "j"):
        echo(solution)
    echo("======= LONGEST  a->j =======")
    echo(op2.longest_path("a", "j"))

var ROD_SIZE: int = 5
type State_T_3 = (int, int)
type Revenue_T = float
type Decision_T_3 = int

type RodCutting = ref object of Optimizer[State_T_3, Decision_T_3]
    prices: seq[(Decision_T_3, Revenue_T)]

proc newRodCutting(): RodCutting =
    new(result)
    result.prices = @[(1, 1.0), (2, 5.0), (3, 8.0), (4, 9.0), (5, 10.0), (6, 17.0), (7, 17.0), (8, 20.0), (9, 24.0), (10, 30.0)]
method get_state(self: Optimizer[State_T_3, Decision_T_3], past_decisions: seq[Decision_T_3]): State_T_3 {.base.} =
    raise newException(CatchableError, "Override get_state()")

method get_next_decisions(self: Optimizer[State_T_3, Decision_T_3], current_state: State_T_3): seq[(Decision_T_3, Cost_T)] {.base.} =
    raise newException(CatchableError, "Override get_next_decisions()")

method get_heuristic_cost(self: Optimizer[State_T_3, Decision_T_3], current_state: State_T_3): float {.base.} =
    return 0.0

method cost_operator(self: Optimizer[State_T_3, Decision_T_3], accumulated: Cost_T, step_cost: Cost_T): Cost_T {.base.} =
    var actual_cost: Cost_T = step_cost + self.offset
    assert actual_cost >= 0
    return accumulated + actual_cost

proc hcost_operator(self: Optimizer[State_T_3, Decision_T_3], past_cost: Cost_T, current_state: State_T_3): Cost_T =
    return past_cost + self.get_heuristic_cost(current_state)

proc real_cost(self: Optimizer[State_T_3, Decision_T_3], cost: Cost_T): Cost_T =
    return cost - self.offset * float(len(self.decision_path))

method is_end_state(self: Optimizer[State_T_3, Decision_T_3], state: State_T_3): bool {.base.} =
    return false

iterator shortest_path(self: Optimizer[State_T_3, Decision_T_3], start_state: State_T_3, end_state: State_T_3, allsolutions: bool = true): auto =
    self.start_state = start_state
    var empty_path: seq[Decision_T_3] = @[]
    var fringe: PriorityQueue[Fringe_Element_T[State_T_3, Decision_T_3]] = newPriorityQueueWith((0.0, 0.0, empty_path, start_state))
    var visited: HashSet[State_T_3] = initHashSet[State_T_3]()

    while fringe.len > 0:
        var item = fringe.pop()
        var cost: float = item[1]
        var path: seq[Decision_T_3] = item[2]
        var current_state: State_T_3 = item[3]

        if not allsolutions and current_state in visited:
            continue

        self.decision_path = path
        visited.incl(current_state)

        if current_state == end_state or self.is_end_state(current_state):
            yield (self.real_cost(cost), path)
            if not allsolutions:
                break

        for (new_decision, step_cost) in self.get_next_decisions(current_state):
            var new_path: seq[Decision_T_3] = path & @[new_decision]
            var next_state: State_T_3 = self.get_state(new_path)
            if next_state notin visited:
                var new_cost: float = self.cost_operator(cost, step_cost)
                var hcost: float = self.hcost_operator(new_cost, next_state)
                fringe.push((hcost, new_cost, new_path, next_state))

    # ------------------------------------------------------------------
    # Generic traversal (BFS / DFS / best-first)
    # ------------------------------------------------------------------

proc visit_state(self: Optimizer[State_T_3, Decision_T_3], state: var State_T_3): void =
    echo("state =", state)

proc longest_path_min(self: Optimizer[State_T_3, Decision_T_3], end_state: State_T_3, excluded_lengths: seq[int] = @[], offset: float = 1000.0): (float, seq[Decision_T_3]) =
    var excluded: HashSet[int] = excluded_lengths.toHashSet()
    var empty_path: seq[Decision_T_3] = @[]
    var fringe = newPriorityQueueWith((0.0, empty_path, self.start_state))
    var visited: Table[State_T_3, float] = initTable[State_T_3, float]()
    var solution: (float, seq[Decision_T_3]) = (0.0, @[])

    while fringe:
        var item = fringe.pop()
        var cost: float = item[0]
        var path: seq[Decision_T_3] = item[1]
        var current_state: State_T_3 = item[2]
        var real_revenue: float = float(len(path)) * offset - cost

        if current_state in visited and real_revenue <= visited[current_state]:
            continue
        visited[current_state] = real_revenue

        if current_state == end_state:
            return (real_revenue, path)

        for (new_decision, revenue) in self.get_next_decisions(current_state):
            var new_path: seq[Decision_T_3] = path & @[new_decision]
            var next_state: State_T_3 = self.get_state(new_path)
            var cost_step: float = -revenue + offset
            assert cost_step > 0
            var new_cost: float = cost + cost_step
            var new_real: float = float(len(new_path)) * offset - new_cost

            var penalty: float = 0.0
            if len(new_path) in excluded and next_state == end_state:
                penalty = 100000.0

            if next_state notin visited or new_real > visited[next_state]:
                fringe.push((new_cost + penalty, new_path, next_state))

    return solution

proc longest_path(self: Optimizer[State_T_3, Decision_T_3], start_state: State_T_3, end_state: State_T_3, max_path_length: int = 1000, offset: float = 1000.0): (float, seq[Decision_T_3]) =
    self.start_state = start_state
    let (revenue, path) = self.longest_path_min(end_state, offset = offset)
    if len(path) == 0:
        return (0.0, path)

    var excluded: seq[int] = @[len(path)]
    var best_revenue: float = revenue
    var best_path: seq[Decision_T_3] = path

    while true:
        let (new_revenue, new_path) = self.longest_path_min(end_state, excluded_lengths = excluded, offset = offset)
        if len(new_path) == 0 or len(new_path) <= len(best_path):
            break
        if len(new_path) > max_path_length:
            break
        excluded.add(len(new_path))
        if new_revenue > best_revenue:
            best_revenue = new_revenue
            best_path = new_path

    return (best_revenue, best_path)

method get_state(self: RodCutting, past_decisions: seq[Decision_T_3]): State_T_3 =
    var stage: int = len(past_decisions)
    var remaining_size: int = ROD_SIZE - sum(collect(for d in past_decisions: d))
    if remaining_size <= 0:
        return (-1, 0)
    return (stage, remaining_size)

method get_next_decisions(self: RodCutting, current_state: State_T_3): seq[(Decision_T_3, Cost_T)] =
    let (stage, remaining_size) = current_state
    return (collect(for (size, rev) in self.prices: (if size <= remaining_size: (size, rev))))

proc example3() =
    # -----------------------------------------------------------------------
    # Example 3 -- Rod Cutting
    # You are given a rod of size n >0, it can be cut into any number of pieces k (k ≤ n).
    # Price for each piece of size i is represented as p(i) and maximum revenue from a rod of size i is r(i)
    # (could be split into multiple pieces). Find r(n) for the rod of size n.
    # -----------------------------------------------------------------------

    echo("======= ROD CUTTING =======")
    var op3: RodCutting = newRodCutting()
    echo(op3.longest_path((0, ROD_SIZE), (-1, 0)))

const CAPITAL: int = 5
type Cost_T_4 = float
type Stage_T = int
type State_T_4 = tuple
    stage: Stage_T
    budget: Cost_T_4
type Decision_T_4 = string
type Revenue_T_4 = float
type Choice_T = tuple
    cost: Cost_T_4
    revenue: Revenue_T_4
type CapitalBudgeting = ref object of Optimizer[State_T_4, Decision_T_4]
    choices: Table[Stage_T, Table[Decision_T_4, Choice_T]]

proc newCapitalBudgeting(): CapitalBudgeting =
    new(result)
    result.choices = {1: {"plant1-p1": (cost: 0.0, revenue: 0.0), "plant1-p2": (cost: 1.0, revenue: 5.0), "plant1-p3": (cost: 2.0, revenue: 6.0)}.toTable, 2: {"plant2-p1": (cost: 0.0, revenue: 0.0), "plant2-p2": (cost: 2.0, revenue: 8.0), "plant2-p3": (cost: 3.0, revenue: 9.0), "plant2-p4": (cost: 4.0, revenue: 12.0)}.toTable, 3: {"plant3-p1": (cost: 0.0, revenue: 0.0), "plant3-p2": (cost: 1.0, revenue: 4.0)}.toTable}.toTable
method get_state(self: Optimizer[State_T_4, Decision_T_4], past_decisions: seq[Decision_T_4]): State_T_4 {.base.} =
    raise newException(CatchableError, "Override get_state()")

method get_next_decisions(self: Optimizer[State_T_4, Decision_T_4], current_state: State_T_4): seq[(Decision_T_4, Cost_T)] {.base.} =
    raise newException(CatchableError, "Override get_next_decisions()")

method get_heuristic_cost(self: Optimizer[State_T_4, Decision_T_4], current_state: State_T_4): float {.base.} =
    return 0.0

method cost_operator(self: Optimizer[State_T_4, Decision_T_4], accumulated: Cost_T, step_cost: Cost_T): Cost_T {.base.} =
    var actual_cost: Cost_T = step_cost + self.offset
    assert actual_cost >= 0
    return accumulated + actual_cost

proc hcost_operator(self: Optimizer[State_T_4, Decision_T_4], past_cost: Cost_T, current_state: State_T_4): Cost_T =
    return past_cost + self.get_heuristic_cost(current_state)

proc real_cost(self: Optimizer[State_T_4, Decision_T_4], cost: Cost_T): Cost_T =
    return cost - self.offset * float(len(self.decision_path))

method is_end_state(self: Optimizer[State_T_4, Decision_T_4], state: State_T_4): bool {.base.} =
    return false

iterator shortest_path(self: Optimizer[State_T_4, Decision_T_4], start_state: State_T_4, end_state: State_T_4, allsolutions: bool = true): auto =
    self.start_state = start_state
    var empty_path: seq[Decision_T_4] = @[]
    var fringe: PriorityQueue[Fringe_Element_T[State_T_4, Decision_T_4]] = newPriorityQueueWith((0.0, 0.0, empty_path, start_state))
    var visited: HashSet[State_T_4] = initHashSet[State_T_4]()

    while fringe.len > 0:
        var item = fringe.pop()
        var cost: float = item[1]
        var path: seq[Decision_T_4] = item[2]
        var current_state: State_T_4 = item[3]

        if not allsolutions and current_state in visited:
            continue

        self.decision_path = path
        visited.incl(current_state)

        if current_state == end_state or self.is_end_state(current_state):
            yield (self.real_cost(cost), path)
            if not allsolutions:
                break

        for (new_decision, step_cost) in self.get_next_decisions(current_state):
            var new_path: seq[Decision_T_4] = path & @[new_decision]
            var next_state: State_T_4 = self.get_state(new_path)
            if next_state notin visited:
                var new_cost: float = self.cost_operator(cost, step_cost)
                var hcost: float = self.hcost_operator(new_cost, next_state)
                fringe.push((hcost, new_cost, new_path, next_state))

    # ------------------------------------------------------------------
    # Generic traversal (BFS / DFS / best-first)
    # ------------------------------------------------------------------

proc visit_state(self: Optimizer[State_T_4, Decision_T_4], state: var State_T_4): void =
    echo("state =", state)

proc longest_path_min(self: Optimizer[State_T_4, Decision_T_4], end_state: State_T_4, excluded_lengths: seq[int] = @[], offset: float = 1000.0): (float, seq[Decision_T_4]) =
    var excluded: HashSet[int] = excluded_lengths.toHashSet()
    var empty_path: seq[Decision_T_4] = @[]
    var fringe = newPriorityQueueWith((0.0, empty_path, self.start_state))
    var visited: Table[State_T_4, float] = initTable[State_T_4, float]()
    var solution: (float, seq[Decision_T_4]) = (0.0, @[])

    while fringe:
        var item = fringe.pop()
        var cost: float = item[0]
        var path: seq[Decision_T_4] = item[1]
        var current_state: State_T_4 = item[2]
        var real_revenue: float = float(len(path)) * offset - cost

        if current_state in visited and real_revenue <= visited[current_state]:
            continue
        visited[current_state] = real_revenue

        if current_state == end_state:
            return (real_revenue, path)

        for (new_decision, revenue) in self.get_next_decisions(current_state):
            var new_path: seq[Decision_T_4] = path & @[new_decision]
            var next_state: State_T_4 = self.get_state(new_path)
            var cost_step: float = -revenue + offset
            assert cost_step > 0
            var new_cost: float = cost + cost_step
            var new_real: float = float(len(new_path)) * offset - new_cost

            var penalty: float = 0.0
            if len(new_path) in excluded and next_state == end_state:
                penalty = 100000.0

            if next_state notin visited or new_real > visited[next_state]:
                fringe.push((new_cost + penalty, new_path, next_state))

    return solution

proc longest_path(self: Optimizer[State_T_4, Decision_T_4], start_state: State_T_4, end_state: State_T_4, max_path_length: int = 1000, offset: float = 1000.0): (float, seq[Decision_T_4]) =
    self.start_state = start_state
    let (revenue, path) = self.longest_path_min(end_state, offset = offset)
    if len(path) == 0:
        return (0.0, path)

    var excluded: seq[int] = @[len(path)]
    var best_revenue: float = revenue
    var best_path: seq[Decision_T_4] = path

    while true:
        let (new_revenue, new_path) = self.longest_path_min(end_state, excluded_lengths = excluded, offset = offset)
        if len(new_path) == 0 or len(new_path) <= len(best_path):
            break
        if len(new_path) > max_path_length:
            break
        excluded.add(len(new_path))
        if new_revenue > best_revenue:
            best_revenue = new_revenue
            best_path = new_path

    return (best_revenue, best_path)

method get_state(self: CapitalBudgeting, past_decisions: seq[Decision_T_4]): State_T_4 =
    var stage: int = len(past_decisions)
    var spent: float = 0.0
    for d in past_decisions:
        for choices in self.choices.values():
            if d in choices:
                spent += choices[d][0]
    return (stage, float(CAPITAL) - spent)

method get_next_decisions(self: CapitalBudgeting, current_state: State_T_4): seq[(Decision_T_4, Cost_T_4)] =
    let (stage, budget) = current_state
    if stage notin self.choices:
        return @[]
    var choices: Table[Decision_T_4, Choice_T] = self.choices[stage]
    return (collect(for (name, choice) in choices.pairs(): (if choice.cost <= budget: (name, choice.revenue))))

proc example4() =
    # -----------------------------------------------------------------------
    # Example 4 -- Capital Budgeting
    # -----------------------------------------------------------------------
    echo("======= CAPITAL BUDGETING =======")
    var op4: CapitalBudgeting = newCapitalBudgeting()
    echo(op4.longest_path((stage: 1, budget: float(CAPITAL)), (stage: 3, budget: 0.0)))

const MAX_WEIGHT: int = 5
type Stage_T_5 = enum STAGE1, STAGE2, STAGE3, END
type State_T_5 = tuple
    stage: Stage_T_5
    remaining: int
type Decision_T_5 = tuple
    stage: Stage_T_5
    quantity: int
type Choice_T5 = tuple
    weight: int
    benefit: int
type Knapsack = ref object of Optimizer[State_T_5, Decision_T_5]
    items: array[Stage_T_5, Choice_T5]

proc newKnapsack(): Knapsack =
    new(result)
    result.items = [(weight: 2, benefit: 65), (weight: 3, benefit: 80), (weight: 1, benefit: 30), default(typeof((weight: 2, benefit: 65)))]
method get_state(self: Optimizer[State_T_5, Decision_T_5], past_decisions: seq[Decision_T_5]): State_T_5 {.base.} =
    raise newException(CatchableError, "Override get_state()")

method get_next_decisions(self: Optimizer[State_T_5, Decision_T_5], current_state: State_T_5): seq[(Decision_T_5, Cost_T)] {.base.} =
    raise newException(CatchableError, "Override get_next_decisions()")

method get_heuristic_cost(self: Optimizer[State_T_5, Decision_T_5], current_state: State_T_5): float {.base.} =
    return 0.0

method cost_operator(self: Optimizer[State_T_5, Decision_T_5], accumulated: Cost_T, step_cost: Cost_T): Cost_T {.base.} =
    var actual_cost: Cost_T = step_cost + self.offset
    assert actual_cost >= 0
    return accumulated + actual_cost

proc hcost_operator(self: Optimizer[State_T_5, Decision_T_5], past_cost: Cost_T, current_state: State_T_5): Cost_T =
    return past_cost + self.get_heuristic_cost(current_state)

proc real_cost(self: Optimizer[State_T_5, Decision_T_5], cost: Cost_T): Cost_T =
    return cost - self.offset * float(len(self.decision_path))

method is_end_state(self: Optimizer[State_T_5, Decision_T_5], state: State_T_5): bool {.base.} =
    return false

iterator shortest_path(self: Optimizer[State_T_5, Decision_T_5], start_state: State_T_5, end_state: State_T_5, allsolutions: bool = true): auto =
    self.start_state = start_state
    var empty_path: seq[Decision_T_5] = @[]
    var fringe: PriorityQueue[Fringe_Element_T[State_T_5, Decision_T_5]] = newPriorityQueueWith((0.0, 0.0, empty_path, start_state))
    var visited: HashSet[State_T_5] = initHashSet[State_T_5]()

    while fringe.len > 0:
        var item = fringe.pop()
        var cost: float = item[1]
        var path: seq[Decision_T_5] = item[2]
        var current_state: State_T_5 = item[3]

        if not allsolutions and current_state in visited:
            continue

        self.decision_path = path
        visited.incl(current_state)

        if current_state == end_state or self.is_end_state(current_state):
            yield (self.real_cost(cost), path)
            if not allsolutions:
                break

        for (new_decision, step_cost) in self.get_next_decisions(current_state):
            var new_path: seq[Decision_T_5] = path & @[new_decision]
            var next_state: State_T_5 = self.get_state(new_path)
            if next_state notin visited:
                var new_cost: float = self.cost_operator(cost, step_cost)
                var hcost: float = self.hcost_operator(new_cost, next_state)
                fringe.push((hcost, new_cost, new_path, next_state))

    # ------------------------------------------------------------------
    # Generic traversal (BFS / DFS / best-first)
    # ------------------------------------------------------------------

proc visit_state(self: Optimizer[State_T_5, Decision_T_5], state: var State_T_5): void =
    echo("state =", state)

proc longest_path_min(self: Optimizer[State_T_5, Decision_T_5], end_state: State_T_5, excluded_lengths: seq[int] = @[], offset: float = 1000.0): (float, seq[Decision_T_5]) =
    var excluded: HashSet[int] = excluded_lengths.toHashSet()
    var empty_path: seq[Decision_T_5] = @[]
    var fringe = newPriorityQueueWith((0.0, empty_path, self.start_state))
    var visited: Table[State_T_5, float] = initTable[State_T_5, float]()
    var solution: (float, seq[Decision_T_5]) = (0.0, @[])

    while fringe:
        var item = fringe.pop()
        var cost: float = item[0]
        var path: seq[Decision_T_5] = item[1]
        var current_state: State_T_5 = item[2]
        var real_revenue: float = float(len(path)) * offset - cost

        if current_state in visited and real_revenue <= visited[current_state]:
            continue
        visited[current_state] = real_revenue

        if current_state == end_state:
            return (real_revenue, path)

        for (new_decision, revenue) in self.get_next_decisions(current_state):
            var new_path: seq[Decision_T_5] = path & @[new_decision]
            var next_state: State_T_5 = self.get_state(new_path)
            var cost_step: float = -revenue + offset
            assert cost_step > 0
            var new_cost: float = cost + cost_step
            var new_real: float = float(len(new_path)) * offset - new_cost

            var penalty: float = 0.0
            if len(new_path) in excluded and next_state == end_state:
                penalty = 100000.0

            if next_state notin visited or new_real > visited[next_state]:
                fringe.push((new_cost + penalty, new_path, next_state))

    return solution

proc longest_path(self: Optimizer[State_T_5, Decision_T_5], start_state: State_T_5, end_state: State_T_5, max_path_length: int = 1000, offset: float = 1000.0): (float, seq[Decision_T_5]) =
    self.start_state = start_state
    let (revenue, path) = self.longest_path_min(end_state, offset = offset)
    if len(path) == 0:
        return (0.0, path)

    var excluded: seq[int] = @[len(path)]
    var best_revenue: float = revenue
    var best_path: seq[Decision_T_5] = path

    while true:
        let (new_revenue, new_path) = self.longest_path_min(end_state, excluded_lengths = excluded, offset = offset)
        if len(new_path) == 0 or len(new_path) <= len(best_path):
            break
        if len(new_path) > max_path_length:
            break
        excluded.add(len(new_path))
        if new_revenue > best_revenue:
            best_revenue = new_revenue
            best_path = new_path

    return (best_revenue, best_path)

method get_state(self: Knapsack, past_decisions: seq[Decision_T_5]): State_T_5 =
    var stage: Stage_T_5 = past_decisions[^1].stage.succ
    var remaining: int = MAX_WEIGHT
    for decision in past_decisions:
        var prev_stage: Stage_T_5 = decision.stage
        var qty: int = decision.quantity
        remaining -= qty * self.items[prev_stage].weight
    return (stage, remaining)

method get_next_decisions(self: Knapsack, current_state: State_T_5): seq[(Decision_T_5, Cost_T)] =
    let (stage, remaining) = current_state
    if stage == END:
        return @[]
    let (weight, benefit) = self.items[stage]
    var decisions: seq[(Decision_T_5, Cost_T)] = @[]
    var qty: int = 0
    while qty * weight <= remaining:
        decisions.add(((stage: stage, quantity: qty), float(benefit * qty)))
        qty += 1
    return decisions

proc example5() =
    # -----------------------------------------------------------------------
    # Example 5 -- Knapsack
    # -----------------------------------------------------------------------
    echo("======= KNAPSACK =======")
    var op5: Knapsack = newKnapsack()
    echo(op5.longest_path((stage: STAGE1, remaining: MAX_WEIGHT), (stage: END, remaining: 0)))

type Decision_T_6 = enum BUY, SELL, KEEP, TRADE
type Cost_T_6 = float
const IRRELEVANT: int = -1
type State_T_6 = (int, int)

type EquipmentReplacement = ref object of Optimizer[State_T_6, Decision_T_6]
    maintenance_cost: Table[int, Cost_T_6]
    market_value: Table[int, Cost_T_6]

method get_state(self: Optimizer[State_T_6, Decision_T_6], past_decisions: seq[Decision_T_6]): State_T_6 {.base.} =
    raise newException(CatchableError, "Override get_state()")

method get_next_decisions(self: Optimizer[State_T_6, Decision_T_6], current_state: State_T_6): seq[(Decision_T_6, Cost_T)] {.base.} =
    raise newException(CatchableError, "Override get_next_decisions()")

method get_heuristic_cost(self: Optimizer[State_T_6, Decision_T_6], current_state: State_T_6): float {.base.} =
    return 0.0

method cost_operator(self: Optimizer[State_T_6, Decision_T_6], accumulated: Cost_T, step_cost: Cost_T): Cost_T {.base.} =
    var actual_cost: Cost_T = step_cost + self.offset
    assert actual_cost >= 0
    return accumulated + actual_cost

proc hcost_operator(self: Optimizer[State_T_6, Decision_T_6], past_cost: Cost_T, current_state: State_T_6): Cost_T =
    return past_cost + self.get_heuristic_cost(current_state)

proc real_cost(self: Optimizer[State_T_6, Decision_T_6], cost: Cost_T): Cost_T =
    return cost - self.offset * float(len(self.decision_path))

method is_end_state(self: Optimizer[State_T_6, Decision_T_6], state: State_T_6): bool {.base.} =
    return false

iterator shortest_path(self: Optimizer[State_T_6, Decision_T_6], start_state: State_T_6, end_state: State_T_6, allsolutions: bool = true): auto =
    self.start_state = start_state
    var empty_path: seq[Decision_T_6] = @[]
    var fringe: PriorityQueue[Fringe_Element_T[State_T_6, Decision_T_6]] = newPriorityQueueWith((0.0, 0.0, empty_path, start_state))
    var visited: HashSet[State_T_6] = initHashSet[State_T_6]()

    while fringe.len > 0:
        var item = fringe.pop()
        var cost: float = item[1]
        var path: seq[Decision_T_6] = item[2]
        var current_state: State_T_6 = item[3]

        if not allsolutions and current_state in visited:
            continue

        self.decision_path = path
        visited.incl(current_state)

        if current_state == end_state or self.is_end_state(current_state):
            yield (self.real_cost(cost), path)
            if not allsolutions:
                break

        for (new_decision, step_cost) in self.get_next_decisions(current_state):
            var new_path: seq[Decision_T_6] = path & @[new_decision]
            var next_state: State_T_6 = self.get_state(new_path)
            if next_state notin visited:
                var new_cost: float = self.cost_operator(cost, step_cost)
                var hcost: float = self.hcost_operator(new_cost, next_state)
                fringe.push((hcost, new_cost, new_path, next_state))

    # ------------------------------------------------------------------
    # Generic traversal (BFS / DFS / best-first)
    # ------------------------------------------------------------------

proc visit_state(self: Optimizer[State_T_6, Decision_T_6], state: var State_T_6): void =
    echo("state =", state)

proc longest_path_min(self: Optimizer[State_T_6, Decision_T_6], end_state: State_T_6, excluded_lengths: seq[int] = @[], offset: float = 1000.0): (float, seq[Decision_T_6]) =
    var excluded: HashSet[int] = excluded_lengths.toHashSet()
    var empty_path: seq[Decision_T_6] = @[]
    var fringe = newPriorityQueueWith((0.0, empty_path, self.start_state))
    var visited: Table[State_T_6, float] = initTable[State_T_6, float]()
    var solution: (float, seq[Decision_T_6]) = (0.0, @[])

    while fringe:
        var item = fringe.pop()
        var cost: float = item[0]
        var path: seq[Decision_T_6] = item[1]
        var current_state: State_T_6 = item[2]
        var real_revenue: float = float(len(path)) * offset - cost

        if current_state in visited and real_revenue <= visited[current_state]:
            continue
        visited[current_state] = real_revenue

        if current_state == end_state:
            return (real_revenue, path)

        for (new_decision, revenue) in self.get_next_decisions(current_state):
            var new_path: seq[Decision_T_6] = path & @[new_decision]
            var next_state: State_T_6 = self.get_state(new_path)
            var cost_step: float = -revenue + offset
            assert cost_step > 0
            var new_cost: float = cost + cost_step
            var new_real: float = float(len(new_path)) * offset - new_cost

            var penalty: float = 0.0
            if len(new_path) in excluded and next_state == end_state:
                penalty = 100000.0

            if next_state notin visited or new_real > visited[next_state]:
                fringe.push((new_cost + penalty, new_path, next_state))

    return solution

proc longest_path(self: Optimizer[State_T_6, Decision_T_6], start_state: State_T_6, end_state: State_T_6, max_path_length: int = 1000, offset: float = 1000.0): (float, seq[Decision_T_6]) =
    self.start_state = start_state
    let (revenue, path) = self.longest_path_min(end_state, offset = offset)
    if len(path) == 0:
        return (0.0, path)

    var excluded: seq[int] = @[len(path)]
    var best_revenue: float = revenue
    var best_path: seq[Decision_T_6] = path

    while true:
        let (new_revenue, new_path) = self.longest_path_min(end_state, excluded_lengths = excluded, offset = offset)
        if len(new_path) == 0 or len(new_path) <= len(best_path):
            break
        if len(new_path) > max_path_length:
            break
        excluded.add(len(new_path))
        if new_revenue > best_revenue:
            best_revenue = new_revenue
            best_path = new_path

    return (best_revenue, best_path)

method get_state(self: EquipmentReplacement, past_decisions: seq[Decision_T_6]): State_T_6
method get_next_decisions(self: EquipmentReplacement, current_state: State_T_6): seq[(Decision_T_6, Cost_T_6)]
proc initEquipmentReplacement(self: EquipmentReplacement, offset: float = 0.0) =
    self.maintenance_cost = {0: 60.0, 1: 80.0, 2: 120.0}.toTable
    self.market_value = {0: 1000.0, 1: 800.0, 2: 600.0, 3: 500.0}.toTable
    initOptimizer[State_T_6, Decision_T_6](self, offset)

proc newEquipmentReplacement(offset: float = 0.0): EquipmentReplacement =
    new(result)
    initEquipmentReplacement(result, offset)
method get_state(self: EquipmentReplacement, past_decisions: seq[Decision_T_6]): State_T_6 =
    var year: int = len(past_decisions)
    if year == 6:
        return (6, IRRELEVANT)
    var age: int = 0
    for decision in past_decisions:
        if decision == KEEP:
            age = age + 1
        else:
            age = 1
    return (year, age)

method get_next_decisions(self: EquipmentReplacement, current_state: State_T_6): seq[(Decision_T_6, Cost_T_6)] =
    let (year, age) = current_state
    if age == IRRELEVANT:
        return @[]
    if year == 0:
        return (@[(BUY, self.maintenance_cost[0] + 1000.0)])
    if year == 5:
        return (@[(SELL, -self.market_value[age])])
    if age == 3:
        return (@[(TRADE, -self.market_value[age] + 1000.0 + self.maintenance_cost[0])])
    return (@[(KEEP, self.maintenance_cost[age]), (TRADE, -self.market_value[age] + 1000.0 + self.maintenance_cost[0])])

proc example6() =
    # -----------------------------------------------------------------------
    # Example 6 -- Equipment Replacement
    # -----------------------------------------------------------------------
    echo("======= EQUIPMENT REPLACEMENT =======")
    var op6: EquipmentReplacement = newEquipmentReplacement(offset = 10000.0)
    var start_state: State_T_6 = (0, 0)
    var end_state: State_T_6 = (6, IRRELEVANT)
    for solution in op6.shortest_path(start_state, end_state):
        echo(solution)

type State_T_7 = string
type Distance_T = float
type Decision_T_7 = string
type BookMap = ref object of Optimizer[State_T_7, Decision_T_7]
    G: Table[State_T_7, seq[(Decision_T_7, Distance_T)]]
    heuristic: Table[State_T_7, Distance_T]

proc newBookMap(): BookMap =
    new(result)
    result.G = {"arad": @[("sibiu", 140.0), ("timisoara", 118.0), ("zerind", 75.0)], "bucharest": @[("giurgiu", 90.0), ("urzineci", 85.0), ("fagaras", 211.0), ("pitesti", 101.0)], "craiova": @[("rimnicu", 146.0), ("pitesti", 138.0), ("drobeta", 120.0)], "drobeta": @[("craiova", 120.0), ("mehadia", 75.0)], "eforie": @[("hirsova", 86.0)], "fagaras": @[("sibiu", 99.0), ("bucharest", 211.0)], "giurgiu": @[("bucharest", 90.0)], "hirsova": @[("eforie", 86.0), ("urzineci", 98.0)], "lasi": @[("neamt", 87.0), ("vaslui", 92.0)], "lugoj": @[("mehadia", 70.0), ("timisoara", 111.0)], "mehadia": @[("drobeta", 75.0), ("lugoj", 70.0)], "neamt": @[("lasi", 87.0)], "oradea": @[("zerind", 71.0), ("sibiu", 151.0)], "pitesti": @[("bucharest", 101.0), ("rimnicu", 97.0), ("craiova", 138.0)], "rimnicu": @[("pitesti", 97.0), ("sibiu", 80.0), ("craiova", 146.0)], "sibiu": @[("rimnicu", 80.0), ("arad", 140.0), ("oradea", 151.0), ("fagaras", 99.0)], "timisoara": @[("lugoj", 111.0), ("arad", 118.0)], "urzineci": @[("bucharest", 85.0), ("vaslui", 142.0), ("hirsova", 98.0)], "vaslui": @[("urzineci", 142.0), ("lasi", 92.0)], "zerind": @[("arad", 75.0), ("oradea", 71.0)]}.toTable
    result.heuristic = {"arad": 366.0, "bucharest": 0.0, "craiova": 160.0, "drobeta": 242.0, "eforie": 161.0, "fagaras": 176.0, "giurgiu": 77.0, "hirsova": 151.0, "lasi": 226.0, "lugoj": 244.0, "mehadia": 241.0, "neamt": 234.0, "oradea": 380.0, "pitesti": 100.0, "rimnicu": 193.0, "sibiu": 253.0, "timisoara": 329.0, "urzineci": 80.0, "vaslui": 199.0, "zerind": 374.0}.toTable
method get_state(self: BookMap, past_decisions: seq[State_T_7]): State_T_7 =
    return past_decisions[^1]

method get_next_decisions(self: BookMap, current_state: State_T_7): seq[(Decision_T_7, Cost_T)] =
    return (self.G.getOrDefault(current_state, @[]))

method get_heuristic_cost(self: BookMap, city: State_T_7): float =
    return (self.heuristic.getOrDefault(city, 0))

proc example7() =
    # -----------------------------------------------------------------------
    # Example 7 -- Romania map (A* with heuristic)
    # -----------------------------------------------------------------------
    var op7: BookMap = newBookMap()
    echo("======= ROMANIA MAP: oradea -> bucharest =======")
    for solution in op7.shortest_path("oradea", "bucharest"):
        echo(solution)


# ---------------------------------------------------------------------------
# HMM demo
# ---------------------------------------------------------------------------
type Hidden_State_T = enum HEALTHY, FEVER, NONE
type Symptom_T = enum NORMAL, COLD, DIZZY
type Prob_T = float
type State_T_8 = tuple
    stage: int
    hidden_state: Hidden_State_T
type HMM = ref object of Optimizer[State_T_8, Hidden_State_T]
    hidden_states: seq[Hidden_State_T]
    start_p: array[Hidden_State_T, Prob_T]
    trans_p: array[Hidden_State_T, array[Hidden_State_T, Prob_T]]
    emit_p: array[Hidden_State_T, array[Symptom_T, Prob_T]]
    obs: seq[Symptom_T]

method get_state(self: Optimizer[State_T_8, Hidden_State_T], past_decisions: seq[Hidden_State_T]): State_T_8 {.base.} =
    raise newException(CatchableError, "Override get_state()")

method get_next_decisions(self: Optimizer[State_T_8, Hidden_State_T], current_state: State_T_8): seq[(Hidden_State_T, Cost_T)] {.base.} =
    raise newException(CatchableError, "Override get_next_decisions()")

method get_heuristic_cost(self: Optimizer[State_T_8, Hidden_State_T], current_state: State_T_8): float {.base.} =
    return 0.0

method cost_operator(self: Optimizer[State_T_8, Hidden_State_T], accumulated: Cost_T, step_cost: Cost_T): Cost_T {.base.} =
    var actual_cost: Cost_T = step_cost + self.offset
    assert actual_cost >= 0
    return accumulated + actual_cost

proc hcost_operator(self: Optimizer[State_T_8, Hidden_State_T], past_cost: Cost_T, current_state: State_T_8): Cost_T =
    return past_cost + self.get_heuristic_cost(current_state)

proc real_cost(self: Optimizer[State_T_8, Hidden_State_T], cost: Cost_T): Cost_T =
    return cost - self.offset * float(len(self.decision_path))

method is_end_state(self: Optimizer[State_T_8, Hidden_State_T], state: State_T_8): bool {.base.} =
    return false

iterator shortest_path(self: Optimizer[State_T_8, Hidden_State_T], start_state: State_T_8, end_state: State_T_8, allsolutions: bool = true): auto =
    self.start_state = start_state
    var empty_path: seq[Hidden_State_T] = @[]
    var fringe: PriorityQueue[Fringe_Element_T[State_T_8, Hidden_State_T]] = newPriorityQueueWith((0.0, 0.0, empty_path, start_state))
    var visited: HashSet[State_T_8] = initHashSet[State_T_8]()

    while fringe.len > 0:
        var item = fringe.pop()
        var cost: float = item[1]
        var path: seq[Hidden_State_T] = item[2]
        var current_state: State_T_8 = item[3]

        if not allsolutions and current_state in visited:
            continue

        self.decision_path = path
        visited.incl(current_state)

        if current_state == end_state or self.is_end_state(current_state):
            yield (self.real_cost(cost), path)
            if not allsolutions:
                break

        for (new_decision, step_cost) in self.get_next_decisions(current_state):
            var new_path: seq[Hidden_State_T] = path & @[new_decision]
            var next_state: State_T_8 = self.get_state(new_path)
            if next_state notin visited:
                var new_cost: float = self.cost_operator(cost, step_cost)
                var hcost: float = self.hcost_operator(new_cost, next_state)
                fringe.push((hcost, new_cost, new_path, next_state))

    # ------------------------------------------------------------------
    # Generic traversal (BFS / DFS / best-first)
    # ------------------------------------------------------------------

proc visit_state(self: Optimizer[State_T_8, Hidden_State_T], state: var State_T_8): void =
    echo("state =", state)

proc longest_path_min(self: Optimizer[State_T_8, Hidden_State_T], end_state: State_T_8, excluded_lengths: seq[int] = @[], offset: float = 1000.0): (float, seq[Hidden_State_T]) =
    var excluded: HashSet[int] = excluded_lengths.toHashSet()
    var empty_path: seq[Hidden_State_T] = @[]
    var fringe = newPriorityQueueWith((0.0, empty_path, self.start_state))
    var visited: Table[State_T_8, float] = initTable[State_T_8, float]()
    var solution: (float, seq[Hidden_State_T]) = (0.0, @[])

    while fringe:
        var item = fringe.pop()
        var cost: float = item[0]
        var path: seq[Hidden_State_T] = item[1]
        var current_state: State_T_8 = item[2]
        var real_revenue: float = float(len(path)) * offset - cost

        if current_state in visited and real_revenue <= visited[current_state]:
            continue
        visited[current_state] = real_revenue

        if current_state == end_state:
            return (real_revenue, path)

        for (new_decision, revenue) in self.get_next_decisions(current_state):
            var new_path: seq[Hidden_State_T] = path & @[new_decision]
            var next_state: State_T_8 = self.get_state(new_path)
            var cost_step: float = -revenue + offset
            assert cost_step > 0
            var new_cost: float = cost + cost_step
            var new_real: float = float(len(new_path)) * offset - new_cost

            var penalty: float = 0.0
            if len(new_path) in excluded and next_state == end_state:
                penalty = 100000.0

            if next_state notin visited or new_real > visited[next_state]:
                fringe.push((new_cost + penalty, new_path, next_state))

    return solution

proc longest_path(self: Optimizer[State_T_8, Hidden_State_T], start_state: State_T_8, end_state: State_T_8, max_path_length: int = 1000, offset: float = 1000.0): (float, seq[Hidden_State_T]) =
    self.start_state = start_state
    let (revenue, path) = self.longest_path_min(end_state, offset = offset)
    if len(path) == 0:
        return (0.0, path)

    var excluded: seq[int] = @[len(path)]
    var best_revenue: float = revenue
    var best_path: seq[Hidden_State_T] = path

    while true:
        let (new_revenue, new_path) = self.longest_path_min(end_state, excluded_lengths = excluded, offset = offset)
        if len(new_path) == 0 or len(new_path) <= len(best_path):
            break
        if len(new_path) > max_path_length:
            break
        excluded.add(len(new_path))
        if new_revenue > best_revenue:
            best_revenue = new_revenue
            best_path = new_path

    return (best_revenue, best_path)

method get_state(self: HMM, past_decisions: seq[Hidden_State_T]): State_T_8
method get_next_decisions(self: HMM, curr_state: State_T_8): seq[(Hidden_State_T, Prob_T)]
method cost_operator(self: HMM, accumulated_cost: Cost_T, step_prob: Prob_T): Cost_T
method get_probability(self: HMM, seq: seq[Hidden_State_T]): Prob_T {.base.}
method is_end_state(self: HMM, state: State_T_8): bool
proc initHMM(self: HMM, obs: seq[Symptom_T]) =
    initOptimizer[State_T_8, Hidden_State_T](self, offset = 1.0)
    self.obs = obs
    self.hidden_states = @[HEALTHY, FEVER]
    self.start_p = [0.6, 0.4, default(typeof(0.6))]
    self.trans_p = [[0.7, 0.3, default(typeof(0.7))], [0.4, 0.6, default(typeof(0.4))], default(typeof([0.7, 0.3, default(typeof(0.7))]))]
    self.emit_p = [[0.5, 0.4, 0.1], [0.1, 0.3, 0.6], default(typeof([0.5, 0.4, 0.1]))]
proc newHMM(obs: seq[Symptom_T]): HMM =
    new(result)
    initHMM(result, obs)
method get_state(self: HMM, past_decisions: seq[Hidden_State_T]): State_T_8 =
    if past_decisions.len == 0:
        return (stage: 0, hidden_state: NONE)
    return (stage: len(past_decisions), hidden_state: past_decisions[^1])
method get_next_decisions(self: HMM, curr_state: State_T_8): seq[(Hidden_State_T, Prob_T)] =
    let (stage, curr_hidden_state) = curr_state
    if stage == len(self.obs):
        return @[]
    var o: Symptom_T = self.obs[stage]
    if stage == 0:
        return (collect(for h in self.hidden_states: (h, self.start_p[h] * self.emit_p[h][o])))
    return (collect(for h in self.hidden_states: (h, self.trans_p[curr_hidden_state][h] * self.emit_p[h][o])))
method cost_operator(self: HMM, accumulated_cost: Cost_T, step_prob: Prob_T): Cost_T =
    return accumulated_cost + ln(self.offset / step_prob)
method get_probability(self: HMM, seq: seq[Hidden_State_T]): Prob_T {.base.} =
    var prob: Prob_T = self.start_p[seq[0]] * self.emit_p[seq[0]][self.obs[0]]
    for i in 1 ..< len(seq):
        var prev: Hidden_State_T = seq[i - 1]
        var curr: Hidden_State_T = seq[i]
        var o: Symptom_T = self.obs[i]
        prob *= self.trans_p[prev][curr] * self.emit_p[curr][o]
    return prob
method is_end_state(self: HMM, state: State_T_8): bool =
    return state.stage == len(self.obs)

proc example8(): auto =
    ## Run the HMM Viterbi demo and return the most probable sequence.
    var obs = @[NORMAL, COLD, DIZZY]
    var hmm = newHMM(obs)
    hmm.obs = obs
    echo("##################################################")
    echo("HIDDEN MARKOV MODEL")
    echo("##################################################")
    echo("Observations:", obs)
    echo("Most probable hidden-state sequences (best first):")
    for solution in hmm.shortest_path((stage: 0, hidden_state: NONE), (stage: len(obs), hidden_state: NONE)):
        var seq = solution[1]
        var prob = hmm.get_probability(seq)
        echo("  seq=", seq, " prob=", round(prob, 6))
    echo("Predicting next state/observation:")
    var best: seq[Hidden_State_T] = @[]
    for solution in hmm.shortest_path((stage: 0, hidden_state: NONE), (stage: len(obs), hidden_state: NONE)):
        best = solution[1]
        break
    var last_state = best[^1]
    for next_obs in @[NORMAL, COLD, DIZZY]:
        for next_state in hmm.hidden_states:
            var prob: float = hmm.trans_p[last_state][next_state] * hmm.emit_p[next_state][next_obs]
            echo("  next_obs=", next_obs, ", next_state=", next_state, ", prob=", round(prob, 6))

example8()

when isMainModule:
    example1()
    example2()
    example3()
    example4()
    example5()
    example6()
    example7()
    example8()
