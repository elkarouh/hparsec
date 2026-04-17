from enum import Enum
from typing import NamedTuple
"""
Shortest-path / dynamic-programming optimiser framework.

ALL DYNAMIC PROGRAMMING PROBLEMS CAN BE TRANSFORMED INTO SHORTEST-PATH PROBLEMS
UNDER THE CONDITION THAT for each decision there is only ONE next state.
"""

from stdlib import ANY, PriorityQueue, FifoQueue, LifoQueue
from math import log

# nimport stdlib


# ---------------------------------------------------------------------------
# Core Optimizer
# ---------------------------------------------------------------------------
Cost_T = float
class Fringe_Element_T(NamedTuple):
    hcost: float
    new_cost: float
    new_path: list[D]
    next_state: S
class Optimizer[S, D]:
    """
        Generic shortest-path / dynamic-programming optimiser.
    
        Subclass and override:
          - get_state(past_decisions)       -> current state
          - get_next_decisions(state)       -> list of (decision, cost) pairs
          - get_heuristic_cost(state)       -> admissible heuristic (default 0)
          - cost_operator(accumulated, new) -> how costs combine (default: addition)
        """
    offset: float
    decision_path: list[D]
    start_state: S
    def __init__(self, offset: float = 0.0):
        self.offset = offset
        self.decision_path = []

    # ------------------------------------------------------------------
    # Methods to override
    # ------------------------------------------------------------------

    def get_state(self, past_decisions: list[D]) -> S:
        raise NotImplementedError("Override get_state()")

    def get_next_decisions(self, current_state: S) -> list[tuple[D, Cost_T]]:
        raise NotImplementedError("Override get_next_decisions()")

    def get_heuristic_cost(self, current_state: S) -> float:
        return 0.0

    def cost_operator(self, accumulated: Cost_T, step_cost: Cost_T) -> Cost_T:
        actual_cost: Cost_T = step_cost + self.offset
        assert actual_cost >= 0
        return accumulated + actual_cost

    def hcost_operator(self, past_cost: Cost_T, current_state: S) -> Cost_T:
        return past_cost + self.get_heuristic_cost(current_state)

    def real_cost(self, cost: Cost_T) -> Cost_T:
        return cost - self.offset * float(len(self.decision_path))

    def is_end_state(self, state: S) -> bool:
        return False

    # ------------------------------------------------------------------
    # Shortest-path (A* / Dijkstra)
    # ------------------------------------------------------------------

    def shortest_path(self, start_state: S, end_state: S, allsolutions: bool = True):
        self.start_state = start_state
        empty_path: list[D] = []
        fringe: PriorityQueue = PriorityQueue((0.0, 0.0, empty_path, start_state))
        visited: set[S] = set()

        while fringe:
            item = fringe.pop()
            cost: float = item[1]
            path: list[D] = item[2]
            current_state: S = item[3]

            if not allsolutions and current_state in visited:
                continue

            self.decision_path = path
            visited.add(current_state)

            if current_state == end_state or self.is_end_state(current_state):
                yield self.real_cost(cost), path
                if not allsolutions:
                    break

            for new_decision, step_cost in self.get_next_decisions(current_state):
                new_path: list[D] = path + [new_decision]
                next_state: S = self.get_state(new_path)
                if next_state not in visited:
                    new_cost: float = self.cost_operator(cost, step_cost)
                    hcost: float = self.hcost_operator(new_cost, next_state)
                    fringe.push((hcost, new_cost, new_path, next_state))

    # ------------------------------------------------------------------
    # Generic traversal (BFS / DFS / best-first)
    # ------------------------------------------------------------------

    def visit_state(self, state: S) -> None:
        print("state =", state)

    # ------------------------------------------------------------------
    # Longest-path helpers
    # ------------------------------------------------------------------

    def longest_path_min(self, end_state: S, excluded_lengths: list[int] = [], offset: float = 1000.0) -> tuple[float, list[D]]:
        excluded: set[int] = set(excluded_lengths)
        empty_path: list[D] = []
        fringe = PriorityQueue((0.0, empty_path, self.start_state))
        visited: dict[S, float] = {}
        solution: tuple[float, list[D]] = (0.0, [])

        while fringe:
            item = fringe.pop()
            cost: float = item[0]
            path: list[D] = item[1]
            current_state: S = item[2]
            real_revenue: float = float(len(path)) * offset - cost

            if current_state in visited and real_revenue <= visited[current_state]:
                continue
            visited[current_state] = real_revenue

            if current_state == end_state:
                return real_revenue, path

            for new_decision, revenue in self.get_next_decisions(current_state):
                new_path: list[D] = path + [new_decision]
                next_state: S = self.get_state(new_path)
                cost_step: float = -revenue + offset
                assert cost_step > 0
                new_cost: float = cost + cost_step
                new_real: float = float(len(new_path)) * offset - new_cost

                penalty: float = 0.0
                if len(new_path) in excluded and next_state == end_state:
                    penalty = 100000.0

                if next_state not in visited or new_real > visited[next_state]:
                    fringe.push((new_cost + penalty, new_path, next_state))

        return solution

    def longest_path(self, start_state: S, end_state: S, max_path_length: int = 1000, offset: float = 1000.0) -> tuple[float, list[D]]:
        self.start_state = start_state
        (revenue, path) = self.longest_path_min(end_state, offset=offset)
        if len(path) == 0:
            return (0.0, path)

        excluded: list[int] = [len(path)]
        best_revenue: float = revenue
        best_path: list[D] = path

        while True:
            (new_revenue, new_path) = self.longest_path_min(end_state, excluded_lengths=excluded, offset=offset)
            if len(new_path) == 0 or len(new_path) <= len(best_path):
                break
            if len(new_path) > max_path_length:
                break
            excluded.append(len(new_path))
            if new_revenue > best_revenue:
                best_revenue = new_revenue
                best_path = new_path

        return best_revenue, best_path

# ===========================================================================
# EXAMPLES / TESTS
def example1():  # ===========================================================================
    # -----------------------------------------------------------------------
    # Example 1 -- simple weighted graph (Dijkstra / longest path)
    # -----------------------------------------------------------------------
    State_T = str
    Cost_T = float
    Decision_T = State_T  # the decision is which state we will choose
    class MyOptimizer(Optimizer[State_T, Decision_T]):
        G: dict[State_T, list[tuple[Decision_T, Cost_T]]] = {
                    's': [('u', 10.0), ('x', 5.0)],
                    'u': [('v', 1.0), ('x', 2.0)],
                    'v': [('y', 4.0)],
                    'x': [('u', 3.0), ('v', 9.0), ('y', 2.0)],
                    'y': [('s', 7.0), ('v', 6.0)],
                }

        def get_state(self, past_decisions: list[Decision_T]) -> State_T:
            return past_decisions[-1]

        def get_next_decisions(self, curr_state: State_T) -> list[tuple[Decision_T, Cost_T]]:
            return self.G.get(curr_state, [])

    op: MyOptimizer = MyOptimizer()
    solution: tuple[Cost_T, list[Decision_T]] = op.longest_path('s', 'v', max_path_length=4)
    print("Longest path s->v:", solution)

def example2():
    # -----------------------------------------------------------------------
    # Example 2 -- DP tutorial graph
    # -----------------------------------------------------------------------
    State_T = str
    Cost_T = float
    Decision_T = State_T
    class MyOptimizer2(Optimizer[State_T, Decision_T]):
        G: dict[State_T, list[tuple[Decision_T, Cost_T]]] = {
                    'a': [('b', 2.0), ('c', 4.0), ('d', 3.0)],
                    'b': [('e', 7.0), ('f', 4.0), ('g', 6.0)],
                    'c': [('e', 3.0), ('f', 2.0), ('g', 4.0)],
                    'd': [('e', 4.0), ('f', 1.0), ('g', 5.0)],
                    'e': [('h', 1.0), ('i', 4.0)],
                    'f': [('h', 6.0), ('i', 3.0)],
                    'g': [('h', 3.0), ('i', 3.0)],
                    'h': [('j', 3.0)],
                    'i': [('j', 4.0)],
                }

        def get_state(self, past_decisions: list[Decision_T]) -> State_T:
            return past_decisions[-1]

        def get_next_decisions(self, curr_state: State_T) -> list[tuple[Decision_T, Cost_T]]:
            return self.G.get(curr_state, [])

    print('======= SHORTEST a->j =======')
    op2: MyOptimizer2 = MyOptimizer2()
    for solution in op2.shortest_path('a', 'j'):
        print(solution)
    print('======= LONGEST  a->j =======')
    print(op2.longest_path('a', 'j'))

def example3():
    # -----------------------------------------------------------------------
    # Example 3 -- Rod Cutting
    # You are given a rod of size n >0, it can be cut into any number of pieces k (k ≤ n).
    # Price for each piece of size i is represented as p(i) and maximum revenue from a rod of size i is r(i)
    # (could be split into multiple pieces). Find r(n) for the rod of size n.
    # -----------------------------------------------------------------------
    ROD_SIZE: int = 5

    State_T = tuple[int, int]
    Revenue_T = float
    Decision_T = int  # decision os what length we cut

    class RodCutting(Optimizer[State_T, Decision_T]):
        prices: list[tuple[Decision_T, Revenue_T]] = [(1, 1.0), (2, 5.0), (3, 8.0), (4, 9.0), (5, 10.0), (6, 17.0), (7, 17.0), (8, 20.0), (9, 24.0), (10, 30.0)]

        def get_state(self, past_decisions: list[Decision_T]) -> State_T:
            stage: int = len(past_decisions)
            remaining_size: int = ROD_SIZE - sum(d for d in past_decisions)
            if remaining_size <= 0:
                return (-1, 0)
            return (stage, remaining_size)

        def get_next_decisions(self, current_state: State_T) -> list[tuple[Decision_T, Cost_T]]:
            (stage, remaining_size) = current_state
            return [(size, rev) for size, rev in self.prices if size <= remaining_size]

    print('======= ROD CUTTING =======')
    op3: RodCutting = RodCutting()
    print(op3.longest_path((0, ROD_SIZE), (-1, 0)))

def example4():
    # -----------------------------------------------------------------------
    # Example 4 -- Capital Budgeting
    # -----------------------------------------------------------------------
    CAPITAL: int = 5
    Cost_T = float
    class Stage_T(Enum):
        STAGE1 = 0
        STAGE2 = 1
        STAGE3 = 2
        END = 3
    STAGE1 = Stage_T.STAGE1
    STAGE2 = Stage_T.STAGE2
    STAGE3 = Stage_T.STAGE3
    END = Stage_T.END
    class State_T(NamedTuple):
        stage: Stage_T
        budget: Cost_T
    Decision_T = str  # decision is which project for the plant
    Revenue_T = float
    class Choice_T(NamedTuple):
        cost: Cost_T
        revenue: Revenue_T
    class CapitalBudgeting(Optimizer[State_T, Decision_T]):
        _choices: dict[Stage_T, dict[Decision_T, Choice_T]] = {STAGE1: {'plant1-p1': Choice_T(cost=0.0, revenue=0.0), 'plant1-p2': Choice_T(cost=1.0, revenue=5.0), 'plant1-p3': Choice_T(cost=2.0, revenue=6.0)}, STAGE2: {'plant2-p1': Choice_T(cost=0.0, revenue=0.0), 'plant2-p2': Choice_T(cost=2.0, revenue=8.0), 'plant2-p3': Choice_T(cost=3.0, revenue=9.0), 'plant2-p4': Choice_T(cost=4.0, revenue=12.0)}, STAGE3: {'plant3-p1': Choice_T(cost=0.0, revenue=0.0), 'plant3-p2': Choice_T(cost=1.0, revenue=4.0)}}

        def get_state(self, past_decisions: list[Decision_T]) -> State_T:
            stage: Stage_T = Stage_T(len(past_decisions))
            spent: float = 0.0
            for d in past_decisions:
                for s in [STAGE1, STAGE2, STAGE3]:
                    choices: dict[Decision_T, Choice_T] = self._choices[s]
                    if d in choices:
                        spent += choices[d][0]
            return stage, float(CAPITAL) - spent

        def get_next_decisions(self, current_state: State_T) -> list[tuple[Decision_T, Cost_T]]:
            (stage, budget) = current_state
            if stage == END:
                return []
            choices: dict[Decision_T, Choice_T] = self._choices[stage]
            return [(name, choice.revenue) for name, choice in choices.items() if choice.cost <= budget]

    print('======= CAPITAL BUDGETING =======')
    op4: CapitalBudgeting = CapitalBudgeting()
    print(op4.longest_path(State_T(stage=STAGE1, budget=float(CAPITAL)), State_T(stage=END, budget=0.0)))

def example5():
    # -----------------------------------------------------------------------
    # Example 5 -- Knapsack
    # -----------------------------------------------------------------------
    MAX_WEIGHT: int = 5
    class Stage_T(Enum):
        STAGE1 = 0
        STAGE2 = 1
        STAGE3 = 2
        END = 3
    STAGE1 = Stage_T.STAGE1
    STAGE2 = Stage_T.STAGE2
    STAGE3 = Stage_T.STAGE3
    END = Stage_T.END
    class State_T(NamedTuple):
        stage: Stage_T
        remaining: int
    class Decision_T(NamedTuple):
        stage: Stage_T
        quantity: int  # the quantity of items to choose
    class Choice_T5(NamedTuple):
        weight: int
        benefit: int
    class Knapsack(Optimizer[State_T, Decision_T]):
        items: dict[Stage_T, Choice_T5] = {STAGE1: Choice_T5(weight=2, benefit=65), STAGE2: Choice_T5(weight=3, benefit=80), STAGE3: Choice_T5(weight=1, benefit=30)}

        def get_state(self, past_decisions: list[Decision_T]) -> State_T:
            stage: Stage_T = type(past_decisions[-1].stage)(past_decisions[-1].stage.value + 1)
            remaining: int = MAX_WEIGHT
            for decision in past_decisions:
                prev_stage: Stage_T = decision.stage
                qty: int = decision.quantity
                remaining -= qty * self.items[prev_stage].weight
            return stage, remaining

        def get_next_decisions(self, current_state: State_T) -> list[tuple[Decision_T, Cost_T]]:
            (stage, remaining) = current_state
            if stage == END:
                return []
            (weight, benefit) = self.items[stage]
            decisions: list[tuple[Decision_T, Cost_T]] = []
            qty: int = 0
            while qty * weight <= remaining:
                decisions.append((Decision_T(stage=stage, quantity=qty), float(benefit * qty)))
                qty += 1
            return decisions

    print('======= KNAPSACK =======')
    op5: Knapsack = Knapsack()
    print(op5.longest_path(State_T(stage=STAGE1, remaining=MAX_WEIGHT), State_T(stage=END, remaining=0)))

def example6():
    # -----------------------------------------------------------------------
    # Example 6 -- Equipment Replacement
    # -----------------------------------------------------------------------
    class Decision_T(Enum):
        BUY = 0
        SELL = 1
        KEEP = 2
        TRADE = 3
    BUY = Decision_T.BUY
    SELL = Decision_T.SELL
    KEEP = Decision_T.KEEP
    TRADE = Decision_T.TRADE
    Cost_T = float
    IRRELEVANT: int = -1
    State_T = tuple[int, int]

    class EquipmentReplacement(Optimizer[State_T, Decision_T]):
        maintenance_cost: dict[int, Cost_T] = {0: 60.0, 1: 80.0, 2: 120.0}
        market_value: dict[int, Cost_T] = {0: 1000.0, 1: 800.0, 2: 600.0, 3: 500.0}

        def __init__(self, offset: float = 0.0):
            super().__init__(offset)

        def get_state(self, past_decisions: list[Decision_T]) -> State_T:
            year: int = len(past_decisions)
            if year == 6:
                return (6, IRRELEVANT)
            age: int = 0
            for decision in past_decisions:
                if decision == KEEP:
                    age = age + 1
                else:
                    age = 1
            return (year, age)

        def get_next_decisions(self, current_state: State_T) -> list[tuple[Decision_T, Cost_T]]:
            (year, age) = current_state
            if age == IRRELEVANT:
                return []
            if year == 0:
                return [(BUY, self.maintenance_cost[0] + 1000.0)]
            if year == 5:
                return [(SELL, -self.market_value[age])]
            if age == 3:
                return [(TRADE, -self.market_value[age] + 1000.0 + self.maintenance_cost[0])]
            return [
                            (KEEP, self.maintenance_cost[age]),
                            (TRADE, -self.market_value[age] + 1000.0 + self.maintenance_cost[0]),
                        ]

    print('======= EQUIPMENT REPLACEMENT =======')
    op6: EquipmentReplacement = EquipmentReplacement(offset=10000.0)
    start_state: State_T = (0, 0)
    end_state: State_T = (6, IRRELEVANT)
    for solution in op6.shortest_path(start_state, end_state):
        print(solution)

def example7():
    # -----------------------------------------------------------------------
    # Example 7 -- Romania map (A* with heuristic)
    # -----------------------------------------------------------------------
    State_T = str
    Distance_T = float
    Decision_T = str
    class BookMap(Optimizer[State_T, Decision_T]):
        G: dict[State_T, list[tuple[Decision_T, Distance_T]]] = {
                    'arad':      [('sibiu', 140.0), ('timisoara', 118.0), ('zerind', 75.0)],
                    'bucharest': [('giurgiu', 90.0), ('urzineci', 85.0), ('fagaras', 211.0), ('pitesti', 101.0)],
                    'craiova':   [('rimnicu', 146.0), ('pitesti', 138.0), ('drobeta', 120.0)],
                    'drobeta':   [('craiova', 120.0), ('mehadia', 75.0)],
                    'eforie':    [('hirsova', 86.0)],
                    'fagaras':   [('sibiu', 99.0), ('bucharest', 211.0)],
                    'giurgiu':   [('bucharest', 90.0)],
                    'hirsova':   [('eforie', 86.0), ('urzineci', 98.0)],
                    'lasi':      [('neamt', 87.0), ('vaslui', 92.0)],
                    'lugoj':     [('mehadia', 70.0), ('timisoara', 111.0)],
                    'mehadia':   [('drobeta', 75.0), ('lugoj', 70.0)],
                    'neamt':     [('lasi', 87.0)],
                    'oradea':    [('zerind', 71.0), ('sibiu', 151.0)],
                    'pitesti':   [('bucharest', 101.0), ('rimnicu', 97.0), ('craiova', 138.0)],
                    'rimnicu':   [('pitesti', 97.0), ('sibiu', 80.0), ('craiova', 146.0)],
                    'sibiu':     [('rimnicu', 80.0), ('arad', 140.0), ('oradea', 151.0), ('fagaras', 99.0)],
                    'timisoara': [('lugoj', 111.0), ('arad', 118.0)],
                    'urzineci':  [('bucharest', 85.0), ('vaslui', 142.0), ('hirsova', 98.0)],
                    'vaslui':    [('urzineci', 142.0), ('lasi', 92.0)],
                    'zerind':    [('arad', 75.0), ('oradea', 71.0)],
                }
        _heuristic: dict[State_T, Distance_T] = {
                    'arad': 366.0, 'bucharest': 0.0, 'craiova': 160.0, 'drobeta': 242.0,
                    'eforie': 161.0, 'fagaras': 176.0, 'giurgiu': 77.0, 'hirsova': 151.0,
                    'lasi': 226.0, 'lugoj': 244.0, 'mehadia': 241.0, 'neamt': 234.0,
                    'oradea': 380.0, 'pitesti': 100.0, 'rimnicu': 193.0, 'sibiu': 253.0,
                    'timisoara': 329.0, 'urzineci': 80.0, 'vaslui': 199.0, 'zerind': 374.0,
                }

        def get_state(self, past_decisions: list[State_T]) -> State_T:
            return past_decisions[-1]

        def get_next_decisions(self, current_state: State_T) -> list[tuple[Decision_T, Cost_T]]:
            return self.G.get(current_state, [])

        def get_heuristic_cost(self, city: State_T) -> float:
            return self._heuristic.get(city, 0)

    op7: BookMap = BookMap()
    print('======= ROMANIA MAP: oradea -> bucharest =======')
    for solution in op7.shortest_path('oradea', 'bucharest'):
        print(solution)


# ---------------------------------------------------------------------------
# HMM demo
# ---------------------------------------------------------------------------
def example8():
    """Run the HMM Viterbi demo and return the most probable sequence."""
    from math import log
    class Hidden_State_T(Enum):
        HEALTHY = 0
        FEVER = 1
        NONE = 2
    HEALTHY = Hidden_State_T.HEALTHY
    FEVER = Hidden_State_T.FEVER
    NONE = Hidden_State_T.NONE
    class Symptom_T(Enum):
        NORMAL = 0
        COLD = 1
        DIZZY = 2
    NORMAL = Symptom_T.NORMAL
    COLD = Symptom_T.COLD
    DIZZY = Symptom_T.DIZZY
    Prob_T = float
    class State_T(NamedTuple):
        stage: int
        hidden_state: Hidden_State_T
    class HMM(Optimizer[State_T, Hidden_State_T]):
        hidden_states: list[Hidden_State_T]
        start_p: dict[Hidden_State_T, Prob_T]
        trans_p: dict[Hidden_State_T, dict[Hidden_State_T, Prob_T]]
        emit_p: dict[Hidden_State_T, dict[Symptom_T, Prob_T]]
        obs: list[Symptom_T]
        def __init__(self, obs: list[Symptom_T]):
            super().__init__(offset=1.0)
            self.obs = obs
            self.hidden_states = [HEALTHY, FEVER]
            self.start_p = {HEALTHY: 0.6, FEVER: 0.4}
            self.trans_p = {HEALTHY: {HEALTHY: 0.7, FEVER: 0.3}, FEVER: {HEALTHY: 0.4, FEVER: 0.6}}
            self.emit_p = {HEALTHY: {NORMAL: 0.5, COLD: 0.4, DIZZY: 0.1}, FEVER: {NORMAL: 0.1, COLD: 0.3, DIZZY: 0.6}}
        def get_state(self, past_decisions: list[Hidden_State_T]) -> State_T:
            if not past_decisions:
                return State_T(stage=0, hidden_state=NONE)
            return State_T(stage=len(past_decisions), hidden_state=past_decisions[-1])
        def get_next_decisions(self, curr_state: State_T) -> list[tuple[Hidden_State_T, Prob_T]]:
            (stage, curr_hidden_state) = curr_state
            if stage == len(self.obs):
                return []
            o: Symptom_T = self.obs[stage]
            if stage == 0:
                return [(h, self.start_p[h] * self.emit_p[h][o])
                                        for h in self.hidden_states]
            return [(h, self.trans_p[curr_hidden_state][h] * self.emit_p[h][o])
                                for h in self.hidden_states]
        def cost_operator(self, accumulated_cost: Cost_T, step_prob: Prob_T) -> Cost_T:
            return accumulated_cost + log(self.offset / step_prob)
        def get_probability(self, seq: list[Hidden_State_T]) -> Prob_T:
            prob: Prob_T = self.start_p[seq[0]] * self.emit_p[seq[0]][self.obs[0]]
            for i in range(1, len(seq)):
                prev: Hidden_State_T = seq[i - 1]
                curr: Hidden_State_T = seq[i]
                o: Symptom_T = self.obs[i]
                prob *= self.trans_p[prev][curr] * self.emit_p[curr][o]
            return prob
        def is_end_state(self, state: State_T) -> bool:
            return state.stage == len(self.obs)

    obs = [NORMAL, COLD, DIZZY]
    hmm = HMM(obs)
    hmm.obs = obs
    print("##################################################")
    print("HIDDEN MARKOV MODEL")
    print("##################################################")
    print("Observations:", obs)
    print("Most probable hidden-state sequences (best first):")
    for solution in hmm.shortest_path(State_T(stage=0, hidden_state=NONE), State_T(stage=len(obs), hidden_state=NONE)):
        seq = solution[1]
        prob = hmm.get_probability(seq)
        print("  seq=", seq, " prob=", round(prob, 6))
    print("Predicting next state/observation:")
    best: list[Hidden_State_T] = []
    for solution in hmm.shortest_path(State_T(stage=0, hidden_state=NONE), State_T(stage=len(obs), hidden_state=NONE)):
        best = solution[1]
        break
    last_state = best[-1]
    for next_obs in [NORMAL, COLD, DIZZY]:
        for next_state in hmm.hidden_states:
            prob: float = hmm.trans_p[last_state][next_state] * hmm.emit_p[next_state][next_obs]
            print("  next_obs=", next_obs, ", next_state=", next_state, ", prob=", round(prob, 6))

example8()

if __name__ == "__main__":
    example1()
    example2()
    example3()
    example4()
    example5()
    example6()
    example7()
    example8()
