"""Tests for deterministic graph queries."""

from __future__ import annotations

import pytest

from hydrolitagent.query.search import (
    find_path,
    get_community,
    get_neighbors,
    load_graph,
    search_nodes,
)


@pytest.fixture
def sample_graph() -> dict:
    return {
        "nodes": [
            {
                "id": "topic_a_paper1",
                "file_type": "paper",
                "label": "LSTM for flood forecasting (Smith 2020)",
                "attributes": {"authors": "Smith J", "year": 2020, "rationale": "Uses LSTM"},
                "community": 0,
                "topics": ["topic-a"],
            },
            {
                "id": "topic_a_concept_lstm",
                "file_type": "concept",
                "label": "LSTM",
                "attributes": {"rationale": "Long Short-Term Memory network"},
                "community": 0,
                "topics": ["topic-a"],
            },
            {
                "id": "topic_a_concept_gru",
                "file_type": "concept",
                "label": "GRU",
                "attributes": {"rationale": "Gated Recurrent Unit"},
                "community": 0,
                "topics": ["topic-a"],
            },
            {
                "id": "topic_b_paper1",
                "file_type": "paper",
                "label": "GRU for streamflow (Jones 2021)",
                "attributes": {"authors": "Jones A", "year": 2021, "rationale": "Uses GRU"},
                "community": 1,
                "topics": ["topic-b"],
            },
            {
                "id": "topic_b_concept_cnn",
                "file_type": "concept",
                "label": "CNN",
                "attributes": {"rationale": "Convolutional Neural Network"},
                "community": 1,
                "topics": ["topic-b"],
            },
        ],
        "edges": [
            {"source": "topic_a_paper1", "target": "topic_a_concept_lstm", "type": "uses", "confidence": 1.0},
            {"source": "topic_a_concept_lstm", "target": "topic_a_concept_gru", "type": "related_to", "confidence": 0.8},
            {"source": "topic_b_paper1", "target": "topic_a_concept_gru", "type": "uses", "confidence": 1.0},
            {"source": "topic_b_paper1", "target": "topic_b_concept_cnn", "type": "uses", "confidence": 0.9},
        ],
        "communities": [
            {"id": 0, "label": "LSTM Methods", "nodes": ["topic_a_paper1", "topic_a_concept_lstm", "topic_a_concept_gru"], "cohesion": 0.75},
            {"id": 1, "label": "CNN Methods", "nodes": ["topic_b_paper1", "topic_b_concept_cnn"], "cohesion": 0.6},
        ],
        "hyperedges": [],
    }


@pytest.fixture
def tmp_graph_file(tmp_path, sample_graph):
    import json
    p = tmp_path / "test_graph.json"
    p.write_text(json.dumps(sample_graph), encoding="utf-8")
    return str(p)


# ——— load_graph ——————————————————————————————————

def test_load_graph_returns_dict(tmp_graph_file):
    g = load_graph(tmp_graph_file)
    assert isinstance(g, dict)
    assert "nodes" in g
    assert "edges" in g


# ——— search_nodes ————————————————————————————————

def test_search_nodes_by_label(sample_graph):
    results = search_nodes(sample_graph, "LSTM")
    assert len(results) >= 1
    assert any("LSTM" in r["label"] for r in results)


def test_search_nodes_by_field(sample_graph):
    results = search_nodes(sample_graph, "Jones", field="authors")
    assert len(results) == 1
    assert results[0]["id"] == "topic_b_paper1"


def test_search_nodes_limit(sample_graph):
    results = search_nodes(sample_graph, "network", limit=2)
    assert len(results) <= 2


def test_search_nodes_no_match(sample_graph):
    results = search_nodes(sample_graph, "nonexistent_xyz")
    assert len(results) == 0


# ——— get_neighbors ————————————————————————————————

def test_get_neighbors_depth_1(sample_graph):
    result = get_neighbors(sample_graph, "topic_a_concept_lstm", depth=1)
    assert "error" not in result
    assert result["total_neighbors"] >= 2
    neighbor_ids = {n["id"] for layer in result["neighbors"] for n in layer}
    assert "topic_a_paper1" in neighbor_ids
    assert "topic_a_concept_gru" in neighbor_ids


def test_get_neighbors_depth_2(sample_graph):
    result = get_neighbors(sample_graph, "topic_a_paper1", depth=2)
    assert not result.get("error")
    assert result["depth"] >= 1


def test_get_neighbors_missing_node(sample_graph):
    result = get_neighbors(sample_graph, "no_such_node")
    assert "error" in result


# ——— find_path ————————————————————————————————————

def test_find_path_direct_neighbors(sample_graph):
    result = find_path(sample_graph, "topic_a_paper1", "topic_a_concept_lstm")
    assert result["length"] == 1
    assert len(result["path"]) == 2


def test_find_path_two_hops(sample_graph):
    result = find_path(sample_graph, "topic_a_paper1", "topic_a_concept_gru")
    assert result["length"] == 2
    assert result["path"][0]["id"] == "topic_a_paper1"
    assert result["path"][-1]["id"] == "topic_a_concept_gru"


def test_find_path_cross_topic(sample_graph):
    result = find_path(sample_graph, "topic_a_paper1", "topic_b_concept_cnn")
    assert result["length"] >= 1


def test_find_path_missing_source(sample_graph):
    result = find_path(sample_graph, "no_such_node", "topic_a_concept_lstm")
    assert "error" in result


def test_find_path_missing_target(sample_graph):
    result = find_path(sample_graph, "topic_a_paper1", "no_such_node")
    assert "error" in result


def test_find_path_no_connection(sample_graph):
    sample_graph["nodes"].append({
        "id": "isolated_node",
        "file_type": "concept",
        "label": "Isolated",
        "attributes": {},
        "community": 2,
        "topics": [],
    })
    sample_graph["communities"].append({
        "id": 2, "label": "Isolated", "nodes": ["isolated_node"], "cohesion": 0,
    })
    result = find_path(sample_graph, "topic_a_paper1", "isolated_node")
    assert "error" in result


# ——— get_community ————————————————————————————————

def test_get_community_valid(sample_graph):
    result = get_community(sample_graph, 0)
    assert "error" not in result
    assert result["community"]["label"] == "LSTM Methods"
    assert len(result["nodes"]) == 3
    assert len(result["edges"]) >= 2


def test_get_community_missing(sample_graph):
    result = get_community(sample_graph, 999)
    assert "error" in result
