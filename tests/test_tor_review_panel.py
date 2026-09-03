"""
tests/test_tor_review_panel.py — Component 3b, v1.3
Tests for tor_review_panel.py.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from tor_review_panel import (
    _build_tor_at_a_glance,
    _apply_review_state,
    _build_paragraph_highlights,
    _get_highlight_color,
    _get_left_border_color,
)


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_tor_data():
    return {
        "title": "Test ToR",
        "funder": "UK FCDO",
        "geography": ["Brazil", "Colombia", "Peru"],
        "thematic_areas": ["Financial Intelligence", "AML/CFT"],
        "key_requirements": ["cross-border cooperation"],
        "evaluation_criteria": [],
        "language": "English",
        "extraction_confidence": "HIGH",
        "source_file": "test.pdf",
        "paragraphs": [
            "The programme is funded by UK FCDO.",
            "Priority countries are Brazil, Colombia and Peru.",
            "Thematic focus includes Financial Intelligence and AML/CFT.",
            "Applicants must demonstrate cross-border cooperation.",
            "This paragraph has no extracted entities.",
        ],
        "source_map": {
            "geography": [
                {"term": "Brazil",   "paragraph_index": 1, "snippet": "...Brazil, Colombia and Peru..."},
                {"term": "Colombia", "paragraph_index": 1, "snippet": "...Brazil, Colombia and Peru..."},
                {"term": "Peru",     "paragraph_index": 1, "snippet": "...Brazil, Colombia and Peru..."},
            ],
            "thematic_areas": [
                {"term": "Financial Intelligence", "paragraph_index": 2, "snippet": "...Financial Intelligence..."},
                {"term": "AML/CFT",               "paragraph_index": 2, "snippet": "...AML/CFT..."},
            ],
            "funder": [
                {"term": "UK FCDO", "paragraph_index": 0, "snippet": "...funded by UK FCDO..."},
            ],
            "key_requirements": [
                {"term": "cross-border cooperation", "paragraph_index": 3, "snippet": "...cross-border cooperation..."},
            ],
        },
    }


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------

def test_tor_at_a_glance_uses_only_extracted_fields(sample_tor_data):
    summary = _build_tor_at_a_glance(sample_tor_data)

    assert summary == {
        "title": "Test ToR",
        "funder": "UK FCDO",
        "geography": ["Brazil", "Colombia", "Peru"],
        "thematic_areas": ["Financial Intelligence", "AML/CFT"],
        "key_requirements": ["cross-border cooperation"],
        "evaluation_criteria": [],
        "language": "English",
        "extraction_confidence": "HIGH",
        "missing_fields": [],
    }


def test_tor_at_a_glance_deduplicates_without_losing_first_spelling(sample_tor_data):
    sample_tor_data["thematic_areas"] = [
        "Integridad",
        "integridad",
        "  Justicia  ",
        "",
        None,
    ]

    summary = _build_tor_at_a_glance(sample_tor_data)

    assert summary["thematic_areas"] == ["Integridad", "Justicia"]


def test_tor_at_a_glance_flags_missing_decision_fields():
    summary = _build_tor_at_a_glance(
        {
            "title": "",
            "funder": None,
            "geography": "Mexico",
            "thematic_areas": [],
            "key_requirements": None,
            "evaluation_criteria": "Quality",
            "extraction_confidence": "unexpected",
        }
    )

    assert summary["title"] == "Title not identified"
    assert summary["funder"] == "Not identified"
    assert summary["geography"] == []
    assert summary["evaluation_criteria"] == []
    assert summary["extraction_confidence"] == "UNKNOWN"
    assert summary["missing_fields"] == [
        "funder",
        "geography",
        "thematic areas",
        "key requirements",
    ]


def test_tor_at_a_glance_reflects_current_review_edits(sample_tor_data):
    review_state = {
        "trp_funder": ["Inter-American Development Bank"],
        "trp_geography": ["Mexico"],
        "trp_thematic_areas": ["Asset Recovery"],
        "trp_key_requirements": ["Demonstrate regional delivery experience"],
    }

    current = _apply_review_state(sample_tor_data, review_state)
    summary = _build_tor_at_a_glance(current)

    assert summary["funder"] == "Inter-American Development Bank"
    assert summary["geography"] == ["Mexico"]
    assert summary["thematic_areas"] == ["Asset Recovery"]
    assert summary["key_requirements"] == [
        "Demonstrate regional delivery experience"
    ]
    assert "Brazil" not in summary["geography"]

def test_build_paragraph_highlights_count(sample_tor_data):
    """Assert: _build_paragraph_highlights returns 5 items (one per paragraph)."""
    result = _build_paragraph_highlights(sample_tor_data)
    assert len(result) == 5


def test_build_paragraph_highlights_geo_detected(sample_tor_data):
    """Assert: paragraph at index 1 has 'geo' in highlight_types."""
    result = _build_paragraph_highlights(sample_tor_data)
    assert "geo" in result[1]["highlight_types"]


def test_build_paragraph_highlights_theme_detected(sample_tor_data):
    """Assert: paragraph at index 2 has 'theme' in highlight_types."""
    result = _build_paragraph_highlights(sample_tor_data)
    assert "theme" in result[2]["highlight_types"]


def test_build_paragraph_highlights_no_highlight(sample_tor_data):
    """Assert: paragraph at index 4 has empty highlight_types."""
    result = _build_paragraph_highlights(sample_tor_data)
    assert result[4]["highlight_types"] == []


def test_highlight_color_geo():
    """Assert: _get_highlight_color(['geo']) == '#E6F1FB'"""
    assert _get_highlight_color(["geo"]) == "#E6F1FB"


def test_highlight_color_no_type():
    """Assert: _get_highlight_color([]) == ''"""
    assert _get_highlight_color([]) == ""


# ---------------------------------------------------------------------------
# Property test
# ---------------------------------------------------------------------------

@given(
    st.lists(
        st.text(min_size=1, max_size=100),
        min_size=1,
        max_size=20,
    )
)
@settings(max_examples=20, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_p_all_paragraphs_represented(paragraphs):
    """
    For any tor_data with N paragraphs, _build_paragraph_highlights
    returns exactly N items.
    """
    # Build a minimal source_map using a subset of valid paragraph indices
    n = len(paragraphs)
    source_map = {
        "geography": [{"term": "Country", "paragraph_index": 0, "snippet": "..."}] if n > 0 else [],
        "thematic_areas": [],
        "funder": [],
        "key_requirements": [],
    }
    tor_data = {
        "paragraphs": paragraphs,
        "source_map": source_map,
    }
    result = _build_paragraph_highlights(tor_data)
    assert len(result) == len(paragraphs), (
        f"Expected {len(paragraphs)} highlights, got {len(result)}"
    )
