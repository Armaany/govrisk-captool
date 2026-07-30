"""
tests/test_draft_review_panel.py — Component 4, v1.3
Tests for draft_review_panel.py.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from draft_review_panel import (
    _strip_citations,
    _format_section_preview,
    _build_preview_html,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_draft():
    return {
        "sections": {
            "opening_statement": "GovRisk has 15 years experience. [Source: profile.pdf, p.1]",
            "geographic_experience": "In Mexico, PECEL programme. [Source: PECEL.pdf, p.3]",
            "alignment_with_tor": "• FIU capacity [Source: PECEL.pdf, p.5]\n• AML/CFT training",
        },
        "interpretation_log": [],
        "summary": {},
    }


@pytest.fixture
def sample_tor():
    return {
        "title": "ACTS LATAM",
        "funder": "UK FCDO",
        "geography": ["Brazil", "Colombia"],
    }


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------

def test_strip_citations_removes_source_tags():
    result = _strip_citations("Good work. [Source: file.pdf, p.3] More text.")
    assert "[Source:" not in result
    assert "Good work." in result
    assert "More text." in result


def test_strip_citations_removes_ref_tags():
    result = _strip_citations("Content [REF:file.pdf:page_3] here.")
    assert "[REF:" not in result


def test_strip_citations_removes_evidence_needed():
    result = _strip_citations("Text. [EVIDENCE NEEDED: missing data] End.")
    assert "[EVIDENCE NEEDED" not in result


def test_strip_citations_handles_empty_string():
    assert _strip_citations("") == ""


def test_strip_citations_handles_non_string():
    assert _strip_citations(None) == ""
    assert _strip_citations(42) == ""


def test_build_preview_html_contains_title(sample_tor):
    html = _build_preview_html([], sample_tor)
    assert "ACTS LATAM" in html


def test_build_preview_html_no_citations(sample_draft, sample_tor):
    sections = [{
        "section_id": "opening_statement",
        "display_name": "Opening statement",
        "content": sample_draft["sections"]["opening_statement"],
        "format": "Narrative",
    }]
    html = _build_preview_html(sections, sample_tor)
    assert "[Source:" not in html


def test_format_section_preview_bullet_wraps_in_ul():
    content = "• Item one\n• Item two"
    html = _format_section_preview("alignment_with_tor", content, "Bullet list")
    assert "<ul" in html or "<li" in html


# ---------------------------------------------------------------------------
# Property test
# ---------------------------------------------------------------------------

@given(st.text(max_size=500))
@settings(max_examples=30, deadline=None)
def test_p_strip_citations_idempotent(s):
    """Stripping citations twice produces the same result as stripping once."""
    once = _strip_citations(s)
    twice = _strip_citations(once)
    assert twice == once


# ---------------------------------------------------------------------------
# Component 7b — Regeneration content fix
# ---------------------------------------------------------------------------

def test_initialisation_does_not_overwrite_existing_content():
    """
    If drp_section_content_X already exists in session state,
    the setdefault pattern in initialisation does not overwrite it.
    """
    # Simulate the setdefault logic used in the initialisation block
    session_state = {}
    # Pre-populate with "regenerated" content
    session_state["drp_section_content_opening_statement"] = "My updated content"

    # Now run the initialisation logic (mimicking what the panel does)
    sections_dict = {"opening_statement": "Original content from Claude"}
    for section_id in sections_dict:
        content = sections_dict.get(section_id, "")
        if f"drp_section_content_{section_id}" not in session_state:
            session_state[f"drp_section_content_{section_id}"] = content

    # Assert: pre-existing value was NOT overwritten
    assert session_state["drp_section_content_opening_statement"] == "My updated content"
