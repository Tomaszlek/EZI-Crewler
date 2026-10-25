"""Adjacency matrices, prestige calculations, and graph requirement checks."""

from collections import deque
from dataclasses import dataclass
from typing import Dict, Iterable, List, Set, Tuple


Edge = Tuple[str, str]
Matrix = List[List[float]]


@dataclass
class RankingResult:
    nodes: List[str]
    adjacency: Matrix
    weighted_adjacency: Matrix
    in_degrees: Dict[str, int]
    raw_prestige: Dict[str, float]
    weighted_prestige: Dict[str, float]
    eigenvector_prestige: Dict[str, float]
    raw_eigenvalue: float
    weighted_eigenvalue: float
    raw_iterations: int
    weighted_iterations: int
    raw_converged: bool
    weighted_converged: bool
    cycle: List[str]
    requirement_messages: List[str]


def analyze_graph(edges: Iterable[Edge], max_iterations: int = 10_000) -> RankingResult:
    """Build source-column adjacency matrices and calculate prestige rankings.

    For an edge source -> target, A[target][source] is 1. The weighted matrix
    divides each source column by its out-degree. Iteration starts uniformly
    and uses (A + I), which has the same eigenvectors as A while preventing
    oscillation on periodic cycles.
    """
    edge_set = {(source.strip(), target.strip()) for source, target in edges}
    edge_set = {(source, target) for source, target in edge_set if source and target}
    nodes = sorted({node for edge in edge_set for node in edge})
    index = {node: position for position, node in enumerate(nodes)}
    size = len(nodes)
    adjacency = [[0.0] * size for _ in range(size)]
    in_degrees = {node: 0 for node in nodes}
    out_degrees = {node: 0 for node in nodes}

    for source, target in edge_set:
        adjacency[index[target]][index[source]] = 1.0
        in_degrees[target] += 1
        out_degrees[source] += 1

    weighted_adjacency = [[0.0] * size for _ in range(size)]
    for target_index in range(size):
        for source_index in range(size):
            degree = out_degrees[nodes[source_index]]
            if degree:
                weighted_adjacency[target_index][source_index] = (
                    adjacency[target_index][source_index] / degree
                )

    raw_vector, raw_eigenvalue, raw_iterations, raw_converged = _dominant_vector(
        adjacency, max_iterations
    )
    weighted_vector, weighted_eigenvalue, weighted_iterations, weighted_converged = (
        _dominant_vector(weighted_adjacency, max_iterations)
    )
    cycle = _find_cycle_of_length_at_least_three(nodes, edge_set)

    messages = []
    if size >= 20:
        messages.append(f"OK: graf zawiera {size} adresów (wymagane co najmniej 20).")
    else:
        messages.append(f"Nie spełnia wymogu 20 adresów: graf zawiera {size}.")
    two_incoming = sum(degree >= 2 for degree in in_degrees.values())
    if two_incoming >= 3:
        messages.append(
            f"OK: wymóg 3 stron z co najmniej 2 linkami wchodzącymi spełniony ({two_incoming})."
        )
    else:
        messages.append(
            f"Nie spełnia wymogu: {two_incoming} strony mają co najmniej 2 linki wchodzące (wymagane 3)."
        )
    three_incoming = sum(degree >= 3 for degree in in_degrees.values())
    if three_incoming:
        messages.append(
            f"OK: strona z co najmniej 3 linkami wchodzącymi znaleziona ({three_incoming})."
        )
    else:
        messages.append("Nie spełnia wymogu: brak strony z co najmniej 3 linkami wchodzącymi.")
    if cycle:
        messages.append(f"OK: znaleziono cykl długości {len(cycle) - 1}.")
    else:
        messages.append("Nie spełnia wymogu: brak cyklu obejmującego co najmniej 3 strony.")

    return RankingResult(
        nodes=nodes,
        adjacency=adjacency,
        weighted_adjacency=weighted_adjacency,
        in_degrees=in_degrees,
        raw_prestige=dict(zip(nodes, raw_vector)),
        weighted_prestige=dict(zip(nodes, weighted_vector)),
        eigenvector_prestige=dict(zip(nodes, weighted_vector)),
        raw_eigenvalue=raw_eigenvalue,
        weighted_eigenvalue=weighted_eigenvalue,
        raw_iterations=raw_iterations,
        weighted_iterations=weighted_iterations,
        raw_converged=raw_converged,
        weighted_converged=weighted_converged,
        cycle=cycle,
        requirement_messages=messages,
    )


def _dominant_vector(
    matrix: Matrix,
    max_iterations: int,
    tolerance: float = 1e-12,
) -> Tuple[List[float], float, int, bool]:
    size = len(matrix)
    if not size:
        return [], 0.0, 0, True

    sparse_rows = [
        [(column, value) for column, value in enumerate(row) if value]
        for row in matrix
    ]
    vector = [1.0 / size] * size
    for iteration in range(1, max_iterations + 1):
        next_vector = [
            vector[row] + sum(value * vector[column] for column, value in sparse_rows[row])
            for row in range(size)
        ]
        total = sum(next_vector)
        if total == 0:
            return vector, 0.0, iteration, True
        next_vector = [value / total for value in next_vector]
        difference = sum(abs(new - old) for new, old in zip(next_vector, vector))
        vector = next_vector
        if difference < tolerance:
            eigenvalue = sum(
                sum(value * vector[column] for column, value in sparse_rows[row])
                for row in range(size)
            )
            return vector, eigenvalue, iteration, True

    eigenvalue = sum(
        sum(value * vector[column] for column, value in sparse_rows[row])
        for row in range(size)
    )
    return vector, eigenvalue, max_iterations, False


def _find_cycle_of_length_at_least_three(
    nodes: List[str], edges: Set[Edge]
) -> List[str]:
    adjacency: Dict[str, List[str]] = {node: [] for node in nodes}
    for source, target in edges:
        adjacency[source].append(target)

    for source, target in edges:
        pending = deque([(target, [target])])
        visited = {target}
        while pending:
            current, path = pending.popleft()
            for neighbor in adjacency[current]:
                if neighbor == source:
                    if len(path) >= 2:
                        return [source] + path + [source]
                elif neighbor not in visited:
                    visited.add(neighbor)
                    pending.append((neighbor, path + [neighbor]))
    return []
