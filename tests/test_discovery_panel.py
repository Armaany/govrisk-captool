"""
tests/test_discovery_panel.py — Component 1, v1.3
Tests for discovery_panel.py.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from discovery_panel import (
    _clean_display_name,
    _group_chunks_by_project,
    _build_prompt_txt,
)


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_chunks():
    """6 chunk dicts across 3 source files."""
    return [
        # PECEL_Mexico.pdf — 3 chunks
        {
            "chunk_id": "c1", "source_file": "PECEL_Mexico.pdf",
            "text": "PECEL project in Mexico focused on AML/CFT.",
            "relevance_score": 0.91, "page_number": 1,
            "geography": ["Mexico"], "thematic_areas": ["AML/CFT"],
            "donor": "US State Dept",
        },
        {
            "chunk_id": "c2", "source_file": "PECEL_Mexico.pdf",
            "text": "FIU strengthening activities in 2021.",
            "relevance_score": 0.85, "page_number": 3,
            "geography": ["Mexico"], "thematic_areas": ["FIU Strengthening"],
            "donor": "US State Dept",
        },
        {
            "chunk_id": "c3", "source_file": "PECEL_Mexico.pdf",
            "text": "Asset recovery workshop outcomes.",
            "relevance_score": 0.80, "page_number": 5,
            "geography": ["Mexico"], "thematic_areas": ["Asset Recovery"],
            "donor": "US State Dept",
        },
        # ACROL_Programme.pdf — 2 chunks
        {
            "chunk_id": "c4", "source_file": "ACROL_Programme.pdf",
            "text": "Anti-corruption regional programme in Colombia.",
            "relevance_score": 0.87, "page_number": 2,
            "geography": ["Colombia"], "thematic_areas": ["Anti-corruption"],
            "donor": "UK FCDO",
        },
        {
            "chunk_id": "c5", "source_file": "ACROL_Programme.pdf",
            "text": "Justice reform components across LAC.",
            "relevance_score": 0.75, "page_number": 4,
            "geography": ["Regional / LATAM"], "thematic_areas": ["Justice Reform"],
            "donor": "UK FCDO",
        },
        # IDB_Study.pdf — 1 chunk
        {
            "chunk_id": "c6", "source_file": "IDB_Study.pdf",
            "text": "Illicit financial flows study for IDB.",
            "relevance_score": 0.64, "page_number": 1,
            "geography": ["Regional / LATAM"], "thematic_areas": ["Illicit Financial Flows"],
            "donor": "IDB",
        },
    ]


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------

def test_clean_display_name_strips_extension():
    """Input: 'PECEL_Mexico_Final_Report.pdf' -> 'Pecel Mexico Final Report'"""
    result = _clean_display_name("PECEL_Mexico_Final_Report.pdf")
    assert result == "Pecel Mexico Final Report"


def test_clean_display_name_handles_hyphens():
    """Input: 'acrol-programme-2022.pdf' -> 'Acrol Programme 2022'"""
    result = _clean_display_name("acrol-programme-2022.pdf")
    assert result == "Acrol Programme 2022"


def test_group_chunks_by_project_count(sample_chunks):
    """Assert: _group_chunks_by_project returns 3 groups."""
    groups = _group_chunks_by_project(sample_chunks)
    assert len(groups) == 3


def test_group_chunks_sorted_by_top_score(sample_chunks):
    """Assert: groups sorted descending by top_score."""
    groups = _group_chunks_by_project(sample_chunks)
    scores = [g["top_score"] for g in groups]
    assert scores == sorted(scores, reverse=True)


def test_group_top_score_is_max_of_chunk_scores(sample_chunks):
    """Assert: PECEL group top_score == 0.91."""
    groups = _group_chunks_by_project(sample_chunks)
    pecel_group = next(g for g in groups if "PECEL" in g["project_id"])
    assert pecel_group["top_score"] == 0.91


def test_build_prompt_txt_contains_system_header(sample_chunks):
    """Call _build_prompt_txt with 2 selected projects. Assert result starts with 'SYSTEM'."""
    groups = _group_chunks_by_project(sample_chunks)
    selected = groups[:2]
    tor_data = {
        "title": "Test ToR",
        "funder": "Test Funder",
        "geography": ["Mexico"],
        "thematic_areas": ["AML/CFT"],
        "key_requirements": ["Risk assessment"],
    }
    result = _build_prompt_txt(selected, tor_data, "exact", ["AML/CFT"])
    assert result.startswith("SYSTEM")


def test_build_prompt_txt_contains_all_selected_projects(sample_chunks):
    """Assert: both selected project display_names appear in the prompt string."""
    groups = _group_chunks_by_project(sample_chunks)
    # Select first two groups
    selected = groups[:2]
    tor_data = {
        "title": "Test ToR",
        "funder": "Test Funder",
        "geography": ["Mexico"],
        "thematic_areas": ["AML/CFT"],
        "key_requirements": [],
    }
    result = _build_prompt_txt(selected, tor_data, "equal", [])
    for project in selected:
        assert project["display_name"] in result, (
            f"Expected display_name '{project['display_name']}' in prompt"
        )


# ---------------------------------------------------------------------------
# Property test
# ---------------------------------------------------------------------------

@given(st.lists(st.booleans(), min_size=3, max_size=3))
@settings(max_examples=20, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_p_no_unselected_project_chunks_in_output(sample_chunks, selections):
    """
    For any boolean selection over 3 projects, chunks from deselected projects
    do not appear in selected_chunks.
    """
    groups = _group_chunks_by_project(sample_chunks)

    # Apply boolean selection mask to groups
    selected_projects = [g for g, sel in zip(groups, selections) if sel]
    deselected_projects = [g for g, sel in zip(groups, selections) if not sel]

    # Collect selected chunk IDs
    selected_chunk_ids = set(
        c["chunk_id"] for p in selected_projects for c in p["chunks"]
    )

    # Collect deselected chunk IDs
    deselected_chunk_ids = set(
        c["chunk_id"] for p in deselected_projects for c in p["chunks"]
    )

    # No deselected chunk should appear in the selected set
    overlap = selected_chunk_ids & deselected_chunk_ids
    assert len(overlap) == 0, (
        f"Chunks from deselected projects appeared in selected_chunks: {overlap}"
    )
