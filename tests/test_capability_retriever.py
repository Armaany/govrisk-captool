"""Tests for capability_retriever.py — Task 3.6"""
import sys
import os
import json
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import patch
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

import chromadb

from capability_retriever import retrieve_chunks
from config import MAX_RETRIEVAL_RESULTS, GEOGRAPHY_OPTIONS


# ---------------------------------------------------------------------------
# Fixture: seeded ChromaDB with 30 test chunks
# ---------------------------------------------------------------------------

@pytest.fixture
def seeded_chroma(tmp_path):
    """
    Creates a temp ChromaDB with 30 test chunks having varied metadata.
    Returns the chroma_path string.
    """
    chroma_path = str(tmp_path / "chroma_seed")
    client = chromadb.PersistentClient(path=chroma_path)
    collection = client.get_or_create_collection("govrisk_capabilities")

    # Geography options to cycle through
    geo_options = [
        ["Mexico"], ["Colombia"], ["Peru"], ["Brazil"],
        ["Mexico", "Colombia"], ["Caribbean"], ["Central America"],
        ["Argentina"], ["Chile"], ["Regional / LATAM"],
    ]
    thematic_options = [
        ["AML/CFT"], ["Anti-corruption"], ["FIU Strengthening"],
        ["Asset Recovery"], ["Justice Reform"],
    ]

    ids = []
    documents = []
    metadatas = []

    for i in range(30):
        geo = geo_options[i % len(geo_options)]
        thematic = thematic_options[i % len(thematic_options)]
        source_file = f"doc_{i % 5}.pdf"   # 5 distinct source files
        page_number = (i % 6) + 1          # pages 1-6 per file

        ids.append(f"chunk-{i:03d}")
        documents.append(
            f"Chunk {i}: GovRisk experience in {', '.join(geo)} covering {', '.join(thematic)}."
        )
        metadatas.append({
            "source_file": source_file,
            "page_number": page_number,
            "chunk_index": i,
            "geography": json.dumps(geo),
            "thematic_areas": json.dumps(thematic),
            "project_name": "",
            "year": 0,
            "donor": "",
            "country": "",
            "doc_type": "pdf",
        })

    collection.add(ids=ids, documents=documents, metadatas=metadatas)
    return chroma_path


# ---------------------------------------------------------------------------
# Unit test: empty ChromaDB returns empty result
# ---------------------------------------------------------------------------

def test_empty_chromadb_returns_empty_result(tmp_path):
    """
    Requirement 4.6: If ChromaDB contains no documents, retriever returns empty result.
    """
    empty_chroma_path = str(tmp_path / "empty_chroma")
    # Create an empty ChromaDB (no chunks added)
    client = chromadb.PersistentClient(path=empty_chroma_path)
    client.get_or_create_collection("govrisk_capabilities")

    tor_data = {
        "thematic_areas": ["AML/CFT"],
        "key_requirements": ["risk assessment"],
        "geography": ["Mexico"],
    }
    filters = {"geography": [], "thematic_areas": [], "funder": []}

    with patch("capability_retriever.CHROMA_DB_PATH", empty_chroma_path):
        result = retrieve_chunks(tor_data, filters)

    assert result["retrieved_chunks"] == []
    assert result["total_chunks_retrieved"] == 0


# ---------------------------------------------------------------------------
# Helper: seed a ChromaDB at the given path with 30 test chunks
# ---------------------------------------------------------------------------

def _seed_chroma(chroma_path: str) -> None:
    """Seed a ChromaDB at chroma_path with 30 varied test chunks."""
    client = chromadb.PersistentClient(path=chroma_path)
    collection = client.get_or_create_collection("govrisk_capabilities")

    if collection.count() > 0:
        return  # already seeded (reuse across hypothesis examples)

    geo_options = [
        ["Mexico"], ["Colombia"], ["Peru"], ["Brazil"],
        ["Mexico", "Colombia"], ["Caribbean"], ["Central America"],
        ["Argentina"], ["Chile"], ["Regional / LATAM"],
    ]
    thematic_options = [
        ["AML/CFT"], ["Anti-corruption"], ["FIU Strengthening"],
        ["Asset Recovery"], ["Justice Reform"],
    ]

    ids = [f"chunk-{i:03d}" for i in range(30)]
    docs = [
        f"Chunk {i}: GovRisk experience in {', '.join(geo_options[i % len(geo_options)])}."
        for i in range(30)
    ]
    metas = [
        {
            "source_file": f"doc_{i % 5}.pdf",
            "page_number": (i % 6) + 1,
            "chunk_index": i,
            "geography": json.dumps(geo_options[i % len(geo_options)]),
            "thematic_areas": json.dumps(thematic_options[i % len(thematic_options)]),
            "project_name": "",
            "year": 0,
            "donor": "",
            "country": "",
            "doc_type": "pdf",
        }
        for i in range(30)
    ]
    collection.add(ids=ids, documents=docs, metadatas=metas)


# ---------------------------------------------------------------------------
# PBT P7: result count ≤ MAX_RETRIEVAL_RESULTS
# ---------------------------------------------------------------------------

@given(st.integers(min_value=1, max_value=50))
@settings(max_examples=15, deadline=None, suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture])
def test_p7_result_count_bound(tmp_path, top_k):
    """
    P7: Retriever returns at most MAX_RETRIEVAL_RESULTS chunks.
    **Validates: Requirements 4.3**
    """
    chroma_path = str(tmp_path / "chroma_p7")
    _seed_chroma(chroma_path)

    tor_data = {"thematic_areas": ["AML/CFT"], "key_requirements": [], "geography": ["Mexico"]}
    filters = {"geography": [], "thematic_areas": [], "funder": []}

    with patch("capability_retriever.CHROMA_DB_PATH", chroma_path):
        result = retrieve_chunks(tor_data, filters, top_k=top_k)

    assert len(result["retrieved_chunks"]) <= MAX_RETRIEVAL_RESULTS


# ---------------------------------------------------------------------------
# PBT P8: relevance scores are non-increasing
# ---------------------------------------------------------------------------

@given(st.text(min_size=1, max_size=100))
@settings(max_examples=15, deadline=None, suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture])
def test_p8_relevance_scores_non_increasing(tmp_path, query_text):
    """
    P8: Chunks are ordered by relevance score descending (non-increasing).
    **Validates: Requirements 4.3**
    """
    chroma_path = str(tmp_path / "chroma_p8")
    _seed_chroma(chroma_path)

    tor_data = {"thematic_areas": [query_text], "key_requirements": [], "geography": []}
    filters = {"geography": [], "thematic_areas": [], "funder": []}

    with patch("capability_retriever.CHROMA_DB_PATH", chroma_path):
        result = retrieve_chunks(tor_data, filters)

    scores = [c["relevance_score"] for c in result["retrieved_chunks"]]
    for i in range(len(scores) - 1):
        assert scores[i] >= scores[i + 1], (
            f"Score at index {i} ({scores[i]}) < score at index {i+1} ({scores[i+1]})"
        )


# ---------------------------------------------------------------------------
# PBT P9: no duplicate (source_file, page_number) pairs
# ---------------------------------------------------------------------------

@given(st.text(min_size=1, max_size=100))
@settings(max_examples=15, deadline=None, suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture])
def test_p9_no_duplicate_source_page_pairs(tmp_path, query_text):
    """
    P9: No two returned chunks share the same (source_file, page_number).
    **Validates: Requirements 4.4**
    """
    chroma_path = str(tmp_path / "chroma_p9")
    _seed_chroma(chroma_path)

    tor_data = {"thematic_areas": [query_text], "key_requirements": [], "geography": []}
    filters = {"geography": [], "thematic_areas": [], "funder": []}

    with patch("capability_retriever.CHROMA_DB_PATH", chroma_path):
        result = retrieve_chunks(tor_data, filters)

    pairs = [(c["source_file"], c["page_number"]) for c in result["retrieved_chunks"]]
    assert len(pairs) == len(set(pairs)), (
        f"Duplicate (source_file, page_number) pairs found: {pairs}"
    )


# ---------------------------------------------------------------------------
# PBT P10: filter logic — returned chunks satisfy active filters
# ---------------------------------------------------------------------------

@given(st.sampled_from(GEOGRAPHY_OPTIONS))
@settings(max_examples=15, deadline=None, suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture])
def test_p10_filter_logic(seeded_chroma, geography_value):
    """
    P10: All returned chunks satisfy the active geography filter.
    **Validates: Requirements 4.2**
    """
    tor_data = {"thematic_areas": [], "key_requirements": [], "geography": []}
    filters = {"geography": [geography_value], "thematic_areas": [], "funder": []}

    with patch("capability_retriever.CHROMA_DB_PATH", seeded_chroma):
        result = retrieve_chunks(tor_data, filters)

    for chunk in result["retrieved_chunks"]:
        assert geography_value in chunk["geography"], (
            f"Chunk geography {chunk['geography']} does not contain filter value '{geography_value}'"
        )
