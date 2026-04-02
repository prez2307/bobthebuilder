"""Tests for dependency graph and build ordering."""

import pytest

from bobthebuilder.graph import DepGraph, build_dep_graph


class TestDepGraph:
    def test_empty_graph(self):
        g = DepGraph()
        assert g.topological_sort() == []

    def test_single_node(self):
        g = DepGraph()
        g.add_node("a")
        assert g.topological_sort() == ["a"]

    def test_linear_chain(self):
        g = DepGraph()
        g.add_edge("a", "b")  # b depends on a
        g.add_edge("b", "c")  # c depends on b
        order = g.topological_sort()
        assert order.index("a") < order.index("b")
        assert order.index("b") < order.index("c")

    def test_diamond_graph(self):
        g = DepGraph()
        g.add_edge("shared", "frontend")
        g.add_edge("shared", "backend")
        g.add_edge("frontend", "app")
        g.add_edge("backend", "app")
        order = g.topological_sort()
        assert order[0] == "shared"
        assert order[-1] == "app"

    def test_cycle_detection(self):
        g = DepGraph()
        g.add_edge("a", "b")
        g.add_edge("b", "c")
        g.add_edge("c", "a")
        with pytest.raises(ValueError, match="cycle"):
            g.topological_sort()

    def test_parallel_groups_independent(self):
        g = DepGraph()
        g.add_node("a")
        g.add_node("b")
        g.add_node("c")
        groups = g.parallel_groups()
        assert len(groups) == 1
        assert set(groups[0]) == {"a", "b", "c"}

    def test_parallel_groups_chain(self):
        g = DepGraph()
        g.add_edge("a", "b")
        g.add_edge("b", "c")
        groups = g.parallel_groups()
        assert len(groups) == 3
        assert groups[0] == ["a"]
        assert groups[1] == ["b"]
        assert groups[2] == ["c"]

    def test_parallel_groups_diamond(self):
        g = DepGraph()
        g.add_edge("lib", "frontend")
        g.add_edge("lib", "backend")
        g.add_edge("frontend", "app")
        g.add_edge("backend", "app")
        groups = g.parallel_groups()
        assert len(groups) == 3
        assert groups[0] == ["lib"]
        assert set(groups[1]) == {"backend", "frontend"}
        assert groups[2] == ["app"]

    def test_dependents_of(self):
        g = DepGraph()
        g.add_edge("lib", "frontend")
        g.add_edge("lib", "backend")
        assert set(g.dependents_of("lib")) == {"frontend", "backend"}
        assert g.dependents_of("frontend") == []

    def test_dependencies_of(self):
        g = DepGraph()
        g.add_edge("lib", "app")
        g.add_edge("utils", "app")
        assert set(g.dependencies_of("app")) == {"lib", "utils"}
        assert g.dependencies_of("lib") == []

    def test_to_dict(self):
        g = DepGraph()
        g.add_edge("a", "b")
        d = g.to_dict()
        assert "nodes" in d
        assert "edges" in d
        assert "build_order" in d
        assert "parallel_groups" in d

    def test_parallel_groups_cycle_detection(self):
        g = DepGraph()
        g.add_edge("a", "b")
        g.add_edge("b", "a")
        with pytest.raises(ValueError, match="cycle"):
            g.parallel_groups()


class TestBuildDepGraph:
    def test_builds_from_repo_list(self):
        repos = [
            ("./shared-lib", []),
            ("./frontend", ["shared-lib"]),
            ("./backend", ["shared-lib"]),
        ]
        graph = build_dep_graph(repos)
        order = graph.topological_sort()
        assert order.index("shared-lib") < order.index("frontend")
        assert order.index("shared-lib") < order.index("backend")

    def test_no_dependencies(self):
        repos = [
            ("./repo1", []),
            ("./repo2", []),
        ]
        graph = build_dep_graph(repos)
        groups = graph.parallel_groups()
        assert len(groups) == 1
        assert set(groups[0]) == {"repo1", "repo2"}

    def test_strips_path_prefix(self):
        repos = [
            ("./libs/core", ["utils"]),
            ("./libs/utils", []),
        ]
        graph = build_dep_graph(repos)
        assert "core" in graph.nodes
        assert "utils" in graph.nodes
