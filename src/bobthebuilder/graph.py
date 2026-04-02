"""Dependency graph - topological ordering of repos for builds."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class DepGraph:
    """Dependency graph for workspace repos.

    Edges go from dependency -> dependent (A -> B means B depends on A).
    """

    nodes: list[str] = field(default_factory=list)
    edges: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))
    reverse_edges: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))

    def add_node(self, name: str) -> None:
        if name not in self.nodes:
            self.nodes.append(name)

    def add_edge(self, dependency: str, dependent: str) -> None:
        """Add edge: `dependent` depends on `dependency`."""
        self.add_node(dependency)
        self.add_node(dependent)
        if dependent not in self.edges[dependency]:
            self.edges[dependency].append(dependent)
        if dependency not in self.reverse_edges[dependent]:
            self.reverse_edges[dependent].append(dependency)

    def topological_sort(self) -> list[str]:
        """Return nodes in build order (dependencies first).

        Raises ValueError if there's a cycle.
        """
        in_degree: dict[str, int] = {n: 0 for n in self.nodes}
        for node in self.nodes:
            for dep in self.reverse_edges[node]:
                in_degree[node] = in_degree.get(node, 0)
            in_degree[node] = len(self.reverse_edges[node])

        queue: deque[str] = deque()
        for node in self.nodes:
            if in_degree[node] == 0:
                queue.append(node)

        result: list[str] = []
        while queue:
            node = queue.popleft()
            result.append(node)
            for dependent in self.edges.get(node, []):
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    queue.append(dependent)

        if len(result) != len(self.nodes):
            cycle_nodes = set(self.nodes) - set(result)
            raise ValueError(f"Dependency cycle detected involving: {', '.join(sorted(cycle_nodes))}")

        return result

    def parallel_groups(self) -> list[list[str]]:
        """Return groups of nodes that can build in parallel.

        Each group contains nodes whose dependencies are all in previous groups.
        """
        in_degree: dict[str, int] = {n: len(self.reverse_edges[n]) for n in self.nodes}

        groups: list[list[str]] = []
        remaining = set(self.nodes)

        while remaining:
            # Find all nodes with in_degree 0
            ready = [n for n in remaining if in_degree[n] == 0]
            if not ready:
                cycle_nodes = remaining
                raise ValueError(f"Dependency cycle detected involving: {', '.join(sorted(cycle_nodes))}")

            groups.append(sorted(ready))

            for node in ready:
                remaining.remove(node)
                for dependent in self.edges.get(node, []):
                    in_degree[dependent] -= 1

        return groups

    def dependents_of(self, node: str) -> list[str]:
        """Get all direct dependents of a node."""
        return self.edges.get(node, [])

    def dependencies_of(self, node: str) -> list[str]:
        """Get all direct dependencies of a node."""
        return self.reverse_edges.get(node, [])

    def to_dict(self) -> dict:
        return {
            "nodes": self.nodes,
            "edges": {k: v for k, v in self.edges.items() if v},
            "build_order": self.topological_sort(),
            "parallel_groups": self.parallel_groups(),
        }


def build_dep_graph(repos: list[tuple[str, list[str]]]) -> DepGraph:
    """Build a dependency graph from repos and their depends_on lists.

    Args:
        repos: List of (repo_name, depends_on_list).
    """
    graph = DepGraph()

    # Normalize names (strip ./ prefix, use just dirname)
    name_map: dict[str, str] = {}
    for repo_name, _ in repos:
        clean = Path(repo_name).name
        name_map[repo_name] = clean
        graph.add_node(clean)

    reverse_map = {v: k for k, v in name_map.items()}

    for repo_name, depends_on in repos:
        clean_name = name_map[repo_name]
        for dep in depends_on:
            dep_clean = Path(dep).name
            if dep_clean in [name_map[r] for r, _ in repos]:
                graph.add_edge(dep_clean, clean_name)

    return graph
