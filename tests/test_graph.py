"""Tests for graph build and merge functions."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hydrolitagent.graph.build import _merge_chunks
from hydrolitagent.graph.merge import merge_graphs


@pytest.fixture
def chunk_dir(tmp_path):
    """Create a fake working dir with two chunk files."""
    chunk1 = {
        "nodes": [
            {"id": "topic_a_paper1", "label": "Paper 1", "file_type": "paper"},
            {"id": "topic_a_concept_x", "label": "Concept X", "file_type": "concept"},
        ],
        "edges": [
            {"source": "topic_a_paper1", "target": "topic_a_concept_x", "type": "uses", "confidence_score": 1.0},
        ],
        "hyperedges": [],
    }
    chunk2 = {
        "nodes": [
            {"id": "topic_a_paper2", "label": "Paper 2", "file_type": "paper"},
            {"id": "topic_a_concept_x", "label": "Concept X", "file_type": "concept"},
        ],
        "edges": [
            {"source": "topic_a_paper2", "target": "topic_a_concept_x", "type": "uses", "confidence_score": "0.8"},
        ],
        "hyperedges": [
            {"id": "hyper_1", "nodes": ["topic_a_paper1", "topic_a_paper2", "topic_a_concept_x"], "confidence_score": "EXTRACTED"},
        ],
    }
    (tmp_path / ".graphify_chunk_01.json").write_text(json.dumps(chunk1), encoding="utf-8")
    (tmp_path / ".graphify_chunk_02.json").write_text(json.dumps(chunk2), encoding="utf-8")
    return tmp_path


def test_merge_chunks_dedup_nodes(chunk_dir):
    result = _merge_chunks(chunk_dir)
    assert len(result["nodes"]) == 3  # 4 raw, 1 dup
    ids = {n["id"] for n in result["nodes"]}
    assert ids == {"topic_a_paper1", "topic_a_paper2", "topic_a_concept_x"}


def test_merge_chunks_concat_edges(chunk_dir):
    result = _merge_chunks(chunk_dir)
    assert len(result["edges"]) == 2


def test_merge_chunks_normalize_confidence(chunk_dir):
    result = _merge_chunks(chunk_dir)
    for e in result["edges"]:
        assert isinstance(e["confidence_score"], (int, float))


def test_merge_chunks_hyperedges(chunk_dir):
    result = _merge_chunks(chunk_dir)
    assert len(result["hyperedges"]) == 1
    assert isinstance(result["hyperedges"][0]["confidence_score"], float)


def test_merge_chunks_no_chunks(tmp_path):
    with pytest.raises(FileNotFoundError):
        _merge_chunks(tmp_path)


def test_merge_graphs_creates_obsidian_vault(tmp_path):
    """merge_graphs() should generate an Obsidian vault with .md files."""
    topic_a = tmp_path / "topic_a"
    topic_a.mkdir()
    graph_a = {
        "nodes": [
            {"id": "a_concept_alpha", "label": "Alpha Concept", "file_type": "concept"},
            {"id": "a_paper_one", "label": "Paper One", "file_type": "paper"},
        ],
        "edges": [
            {"source": "a_paper_one", "target": "a_concept_alpha", "type": "uses", "confidence": 1.0},
        ],
        "hyperedges": [],
    }
    (topic_a / "graph.json").write_text(json.dumps(graph_a), encoding="utf-8")

    topic_b = tmp_path / "topic_b"
    topic_b.mkdir()
    graph_b = {
        "nodes": [
            {"id": "b_concept_beta", "label": "Beta Concept", "file_type": "concept"},
        ],
        "edges": [],
        "hyperedges": [],
    }
    (topic_b / "graph.json").write_text(json.dumps(graph_b), encoding="utf-8")

    output_dir = tmp_path / "unified"
    merge_graphs([topic_a / "graph.json", topic_b / "graph.json"], output_dir)

    obsidian_dir = output_dir / "obsidian"
    assert obsidian_dir.is_dir()
    md_files = list(obsidian_dir.glob("*.md"))
    assert len(md_files) > 0


def test_write_topic_indexes_creates_topic_pages(tmp_path):
    """_write_topic_indexes should generate _TOPIC_*.md per topic."""
    import networkx as nx
    from hydrolitagent.graph.merge import _write_topic_indexes

    G = nx.Graph()
    G.add_node("a_concept", label="Alpha", file_type="concept", topics=["physics", "flood"])
    G.add_node("b_concept", label="Beta", file_type="concept", topics=["physics"])
    G.add_node("c_concept", label="Gamma", file_type="paper", topics=["flood"])

    _write_topic_indexes(G, tmp_path)

    physics_idx = tmp_path / "_TOPIC_physics.md"
    assert physics_idx.is_file()
    content = physics_idx.read_text(encoding="utf-8")
    assert "[[Alpha]]" in content
    assert "[[Beta]]" in content
    assert "Gamma" not in content

    flood_idx = tmp_path / "_TOPIC_flood.md"
    assert flood_idx.is_file()
    content = flood_idx.read_text(encoding="utf-8")
    assert "[[Alpha]]" in content
    assert "[[Gamma]]" in content


def test_write_topic_indexes_creates_cross_topic_bridges(tmp_path):
    """_write_topic_indexes should generate _CROSS_TOPIC_BRIDGES.md."""
    import networkx as nx
    from hydrolitagent.graph.merge import _write_topic_indexes

    G = nx.Graph()
    G.add_node("a_concept", label="Alpha", file_type="concept", topics=["physics", "flood"])
    G.add_node("b_concept", label="Beta", file_type="concept", topics=["physics"])
    G.add_node("c_concept", label="Gamma", file_type="paper", topics=["flood"])

    _write_topic_indexes(G, tmp_path)

    bridges = tmp_path / "_CROSS_TOPIC_BRIDGES.md"
    assert bridges.is_file()
    content = bridges.read_text(encoding="utf-8")
    assert "[[Alpha]]" in content
    assert "Beta" not in content
    assert "Gamma" not in content


def test_write_topic_indexes_no_topics_field(tmp_path):
    """_write_topic_indexes should handle nodes without topics field."""
    import networkx as nx
    from hydrolitagent.graph.merge import _write_topic_indexes

    G = nx.Graph()
    G.add_node("orphan", label="Orphan", file_type="concept")

    _write_topic_indexes(G, tmp_path)

    assert not list(tmp_path.glob("_TOPIC_*.md"))
    assert not (tmp_path / "_CROSS_TOPIC_BRIDGES.md").exists()


def test_prepare_hierarchical_data_builds_topic_edges(tmp_path):
    """_prepare_hierarchical_data should compute cross-topic shared concept edges."""
    import networkx as nx
    from hydrolitagent.graph.merge import _prepare_hierarchical_data

    G = nx.Graph()
    G.add_node("a", label="Alpha", file_type="concept", topics=["physics", "flood"])
    G.add_node("b", label="Beta", file_type="concept", topics=["physics"])
    G.add_node("c", label="Gamma", file_type="paper", topics=["flood"])

    communities = {1: ["a", "b"], 2: ["c"]}
    labels = {1: "Physics Core", 2: "Flood Core"}
    scores = {1: 0.85, 2: 0.60}

    data = _prepare_hierarchical_data(G, communities, labels, scores)

    assert len(data["topics"]) == 2
    assert any(t["id"] == "topic_physics" for t in data["topics"])
    assert any(t["id"] == "topic_flood" for t in data["topics"])
    # "Alpha" is shared between physics and flood → 1 shared concept
    assert len(data["topic_edges"]) >= 1

    assert len(data["communities"]) == 2
    # Community 1 should list both topics
    c1 = next(c for c in data["communities"] if c["id"] == "comm_1")
    assert "physics" in c1["topics"]
