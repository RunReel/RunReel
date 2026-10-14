import heapq


def dijkstra(graph, source):
    dist = {node: float("inf") for node in graph}
    dist[source] = 0
    heap = [(0, source)]
    while heap:
        d, node = heapq.heappop(heap)
        if d > dist[node]:
            continue
        for neighbour, weight in graph[node]:
            nd = d + weight
            if nd < dist[neighbour]:
                dist[neighbour] = nd
                heapq.heappush(heap, (nd, neighbour))
    return dist


G = {0: [(1, 4), (2, 1)], 1: [(3, 1)], 2: [(1, 2), (3, 5)], 3: []}

if __name__ == "__main__":
    print(dijkstra(G, 0))
