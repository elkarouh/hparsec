from logeye import log

@log
def dijkstra(graph, start):
    distances = {node: float("inf") for node in graph}
    distances[start] = 0

    visited = set()
    queue = [(0, start)]

    while queue:
        queue.sort()
        current_dist, node = queue.pop(0)
        if node in visited:
            continue
        visited.add(node)
        for neighbor in graph[node]:
            new_dist = current_dist + graph[node][neighbor]
            if new_dist < distances[neighbor]:
                distances[neighbor] = new_dist
                queue.append((new_dist, neighbor))
    return distances


graph = {
    "A": {"B": 1, "C": 4},
    "B": {"C": 2, "D": 5},
    "C": {"D": 1},
    "D": {}
}

dijkstra(graph, "A")