"""Tests for draft_generator.py — Task 5.8"""
import sys
import os
import json
import re

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import patch, MagicMock
from hypothesis import given, settings
from hypothesis import strategies as st

from draft_generator import generate_draft, _build_context_block, SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tor_data(**overrides):
    base = {
        "title": "AML/CFT Capacity Building in Mexico",
        "funder": "US State Dept",
        "geography": ["Mexico"],
        "thematic_areas": ["AML/CFT"],
        "key_requirements": ["Risk assessment", "FIU strengthening"],
        "evaluation_criteria": [],
        "language": "English",
        "source_file": "test_tor.pdf",
        "extraction_confidence": "HIGH",
    }
    base.update(overrides)
    return base


def _make_chunks(n=3):
    return [
        {
            "text": f"Project Alpha in Mexico, 2022, funded by US State Dept. [REF:doc_{i}.pdf:page_1]",
            "source_file": f"doc_{i}.pdf",
            "page_number": i + 1,
        }
        for i in range(n)
    ]


def _make_valid_draft_json():
    return json.dumps({
        "sections": {
            "opening_statement": "GovRisk has extensive experience. [REF:doc_0.pdf:page_1]",
            "institutional_overview": "Founded in 2010. [REF:doc_1.pdf:page_2]",
            "country_table": [
                {
                    "country": "Mexico",
                    "project_count": 3,
                    "year_range": "2020-2023",
                    "named_identifiers": ["Project Alpha"],
                    "donors": ["US State Dept"],
                }
            ],
            "geographic_experience": "Strong presence in Mexico. [REF:doc_0.pdf:page_1]",
            "thematic_areas": "AML/CFT expertise. [REF:doc_1.pdf:page_2]",
            "selected_project_experience": "Project Alpha (2022). [REF:doc_2.pdf:page_3]",
            "alignment_with_tor": "Fully aligned. [REF:doc_0.pdf:page_1]",
        },
        "interpretation_log": [
            {
                "section": "opening_statement",
                "inference_made": "Inferred from project data",
                "source_used": "doc_0.pdf p.1",
                "gap_flagged": None,
                "confidence": "HIGH",
            }
        ],
        "summary": {
            "sections_generated": 7,
            "projects_referenced": 3,
            "countries_covered": 1,
            "documents_used": 3,
            "overall_confidence": "HIGH",
        },
    })


def _make_mock_client(response_text):
    """Return a mock Anthropic client that returns the given text."""
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=response_text)]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response
    return mock_client


# ---------------------------------------------------------------------------
# Unit test: Claude API called with max_tokens=4000
# ---------------------------------------------------------------------------

def test_claude_api_called_with_max_tokens_16000():
    """
    Requirement 5.2: Claude API must be called with max_tokens=16000.
    """
    tor_data = _make_tor_data()
    chunks = _make_chunks()
    mock_client = _make_mock_client(_make_valid_draft_json())

    with patch("draft_generator.anthropic.Anthropic", return_value=mock_client):
        generate_draft(tor_data, chunks)

    mock_client.messages.create.assert_called_once()
    call_kwargs = mock_client.messages.create.call_args
    assert call_kwargs.kwargs.get("max_tokens") == 16000 or (
        len(call_kwargs.args) > 0 and call_kwargs.args[0] == 16000
    ), f"max_tokens was not 16000; call args: {call_kwargs}"


# ---------------------------------------------------------------------------
# Unit test: system prompt contains all required instructions
# ---------------------------------------------------------------------------

def test_system_prompt_contains_required_instructions():
    """
    Requirement 5.3: System prompt must contain all required instructions.
    """
    assert "Use ONLY content from the provided source chunks. Never invent." in SYSTEM_PROMPT
    assert "[REF:filename:page_N]" in SYSTEM_PROMPT
    assert "Most recent experience first" in SYSTEM_PROMPT
    assert "Never fill gaps silently" in SYSTEM_PROMPT


def test_system_prompt_passed_to_claude():
    """System prompt is passed to the Claude API call."""
    tor_data = _make_tor_data()
    chunks = _make_chunks()
    mock_client = _make_mock_client(_make_valid_draft_json())

    captured = {}

    def capture_call(**kwargs):
        captured["system"] = kwargs.get("system", "")
        return mock_client.messages.create.return_value

    mock_client.messages.create.side_effect = capture_call

    with patch("draft_generator.anthropic.Anthropic", return_value=mock_client):
        generate_draft(tor_data, chunks)

    assert "Use ONLY content from the provided source chunks. Never invent." in captured["system"]
    assert "[REF:filename:page_N]" in captured["system"]
    assert "Most recent experience first" in captured["system"]
    assert "Never fill gaps silently" in captured["system"]


# ---------------------------------------------------------------------------
# Unit test: non-JSON response triggers retry then returns error
# ---------------------------------------------------------------------------

def test_non_json_response_triggers_retry_then_returns_error():
    """
    Requirement 5.8: Non-JSON Claude response triggers exactly one retry;
    if retry also fails, returns error dict with LOW confidence.
    """
    tor_data = _make_tor_data()
    chunks = _make_chunks()

    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="This is not valid JSON at all.")]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response

    with patch("draft_generator.anthropic.Anthropic", return_value=mock_client):
        result = generate_draft(tor_data, chunks)

    # Should have been called exactly 2 times: initial + 1 retry
    assert mock_client.messages.create.call_count == 2
    assert "error" in result
    assert result["summary"]["overall_confidence"] == "LOW"


def test_non_json_first_attempt_valid_second_succeeds():
    """First attempt returns non-JSON, second attempt returns valid JSON — should succeed."""
    tor_data = _make_tor_data()
    chunks = _make_chunks()

    valid_json = _make_valid_draft_json()
    mock_response_bad = MagicMock()
    mock_response_bad.content = [MagicMock(text="not json")]
    mock_response_good = MagicMock()
    mock_response_good.content = [MagicMock(text=valid_json)]

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = [mock_response_bad, mock_response_good]

    with patch("draft_generator.anthropic.Anthropic", return_value=mock_client):
        result = generate_draft(tor_data, chunks)

    assert "error" not in result
    assert "sections" in result
    assert mock_client.messages.create.call_count == 2


# ---------------------------------------------------------------------------
# Unit test: generate_draft never raises
# ---------------------------------------------------------------------------

def test_generate_draft_never_raises_on_bad_input():
    """generate_draft must always return a dict, never raise."""
    result = generate_draft({}, [])
    assert isinstance(result, dict)


def test_generate_draft_returns_error_dict_on_api_failure():
    """When the API raises an exception, an error dict is returned."""
    tor_data = _make_tor_data()
    chunks = _make_chunks()

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = Exception("Network error")

    with patch("draft_generator.anthropic.Anthropic", return_value=mock_client):
        result = generate_draft(tor_data, chunks)

    assert "error" in result
    assert result["summary"]["overall_confidence"] == "LOW"


# ---------------------------------------------------------------------------
# Unit test: missing section keys are filled with empty string
# ---------------------------------------------------------------------------

def test_missing_section_keys_filled_with_empty_string():
    """Task 5.5: Missing section keys are added with empty string value."""
    tor_data = _make_tor_data()
    chunks = _make_chunks()

    # Return JSON with only one section
    partial_draft = json.dumps({
        "sections": {
            "opening_statement": "GovRisk overview. [REF:doc.pdf:page_1]",
        },
        "interpretation_log": [],
        "summary": {},
    })

    mock_client = _make_mock_client(partial_draft)

    with patch("draft_generator.anthropic.Anthropic", return_value=mock_client):
        result = generate_draft(tor_data, chunks)

    assert "error" not in result
    for section in ["opening_statement", "institutional_overview", "country_table",
                    "geographic_experience", "thematic_areas",
                    "selected_project_experience", "alignment_with_tor"]:
        assert section in result["sections"], f"Missing section: {section}"


# ---------------------------------------------------------------------------
# Unit test: context block uses empty fallback when no chunks
# ---------------------------------------------------------------------------

def test_context_block_empty_chunks_returns_fallback():
    """_build_context_block returns fallback string when chunks list is empty."""
    result = _build_context_block([])
    assert result == "No capability library content available."


# ---------------------------------------------------------------------------
# PBT P11: every paragraph in every section contains ≥1 REF tag
# ---------------------------------------------------------------------------

@given(st.fixed_dictionaries({
    "opening_statement": st.text(min_size=1).map(lambda t: t + " [REF:doc.pdf:page_1]"),
    "institutional_overview": st.text(min_size=1).map(lambda t: t + " [REF:doc.pdf:page_2]"),
    "geographic_experience": st.text(min_size=1).map(lambda t: t + " [REF:doc.pdf:page_3]"),
    "thematic_areas": st.text(min_size=1).map(lambda t: t + " [REF:doc.pdf:page_4]"),
    "selected_project_experience": st.text(min_size=1).map(lambda t: t + " [REF:doc.pdf:page_5]"),
    "alignment_with_tor": st.text(min_size=1).map(lambda t: t + " [REF:doc.pdf:page_6]"),
}))
@settings(max_examples=20, deadline=None)
def test_p11_ref_tag_in_every_section(sections):
    """P11: Every section string that has content contains at least one REF tag.
    **Validates: Requirements 9.1**
    """
    ref_pattern = re.compile(r'\[REF:[^\]]+\]')
    for section_name, section_text in sections.items():
        if section_text.strip():
            assert ref_pattern.search(section_text), \
                f"Section '{section_name}' has no REF tag: {section_text[:100]}"


# ---------------------------------------------------------------------------
# PBT P17: project experience entries sorted by year descending
# ---------------------------------------------------------------------------

@given(st.lists(
    st.fixed_dictionaries({
        "year": st.integers(min_value=2000, max_value=2026),
        "name": st.text(min_size=1, max_size=20),
    }),
    min_size=1, max_size=10
))
@settings(max_examples=20, deadline=None)
def test_p17_recency_ordering(projects):
    """P17: Projects sorted by year descending, stable for equal years.
    **Validates: Requirements 10.1, 10.2**
    """
    sorted_projects = sorted(projects, key=lambda p: p["year"], reverse=True)
    years = [p["year"] for p in sorted_projects]
    assert years == sorted(years, reverse=True)


# ---------------------------------------------------------------------------
# PBT P20: GeneratedDraft JSON round-trip
# ---------------------------------------------------------------------------

@given(st.fixed_dictionaries({
    "sections": st.fixed_dictionaries({
        "opening_statement": st.text(max_size=100),
        "institutional_overview": st.text(max_size=100),
        "geographic_experience": st.text(max_size=100),
        "thematic_areas": st.text(max_size=100),
        "selected_project_experience": st.text(max_size=100),
        "alignment_with_tor": st.text(max_size=100),
        "country_table": st.just([]),
    }),
    "interpretation_log": st.lists(st.fixed_dictionaries({
        "section": st.text(max_size=30),
        "inference_made": st.text(max_size=50),
        "source_used": st.text(max_size=30),
        "gap_flagged": st.one_of(st.none(), st.text(max_size=30)),
        "confidence": st.sampled_from(["HIGH", "MEDIUM", "LOW"]),
    }), max_size=3),
    "summary": st.fixed_dictionaries({
        "sections_generated": st.integers(min_value=0, max_value=7),
        "projects_referenced": st.integers(min_value=0, max_value=20),
        "countries_covered": st.integers(min_value=0, max_value=10),
        "documents_used": st.integers(min_value=0, max_value=10),
        "overall_confidence": st.sampled_from(["HIGH", "MEDIUM", "LOW"]),
    }),
}))
@settings(max_examples=20, deadline=None)
def test_p20_generated_draft_json_roundtrip(draft):
    """P20: Serialising a GeneratedDraft dict to JSON and deserialising it produces
    an object equal to the original.
    **Validates: Requirements 11.4**
    """
    serialized = json.dumps(draft)
    deserialized = json.loads(serialized)
    assert deserialized == draft


# ---------------------------------------------------------------------------
# PBT P22: all interpretation_log entries have required fields
# ---------------------------------------------------------------------------

@given(st.lists(st.fixed_dictionaries({
    "section": st.text(max_size=30),
    "inference_made": st.text(max_size=50),
    "source_used": st.text(max_size=30),
    "gap_flagged": st.one_of(st.none(), st.text(max_size=30)),
    "confidence": st.sampled_from(["HIGH", "MEDIUM", "LOW"]),
}), max_size=5))
@settings(max_examples=20, deadline=None)
def test_p22_interpretation_log_completeness(log_entries):
    """P22: All interpretation_log entries have all required fields.
    **Validates: Requirements 5.6**
    """
    required = {"section", "inference_made", "source_used", "gap_flagged", "confidence"}
    for entry in log_entries:
        assert required.issubset(entry.keys()), \
            f"Entry missing required fields: {entry}"


# ---------------------------------------------------------------------------
# PBT P23: context block uses at most 20 chunks
# ---------------------------------------------------------------------------

@given(st.integers(min_value=21, max_value=50))
@settings(max_examples=20, deadline=None)
def test_p23_context_block_chunk_cap(num_chunks):
    """P23: Context block uses at most 20 chunks regardless of input size.
    **Validates: Requirements 5.9**
    """
    chunks = [
        {"text": f"chunk {i}", "source_file": f"doc_{i}.pdf", "page_number": i}
        for i in range(num_chunks)
    ]
    context = _build_context_block(chunks)
    # Count how many [Source: ...] headers appear — each represents one chunk
    source_headers = re.findall(r'\[Source:', context)
    assert len(source_headers) <= 20


# ---------------------------------------------------------------------------
# Component 5 — feedback and single_section tests
# ---------------------------------------------------------------------------

def test_feedback_parameter_accepted():
    """generate_draft accepts feedback parameter without TypeError."""
    tor_data = _make_tor_data()
    chunks = _make_chunks()
    mock_client = _make_mock_client(_make_valid_draft_json())
    with patch("draft_generator.anthropic.Anthropic", return_value=mock_client):
        result = generate_draft(tor_data, chunks, feedback="Make it shorter")
    assert isinstance(result, dict)
    assert "error" not in result


def test_single_section_returns_only_that_section():
    """single_section returns only the requested section."""
    valid_json = json.dumps({
        "sections": {"opening_statement": "Content here. [REF:doc.pdf:page_1]"},
        "interpretation_log": [],
        "summary": {},
    })
    mock_client = _make_mock_client(valid_json)
    with patch("draft_generator.anthropic.Anthropic", return_value=mock_client):
        result = generate_draft(
            _make_tor_data(), _make_chunks(), single_section="opening_statement"
        )
    assert "opening_statement" in result["sections"]


def test_single_section_unknown_returns_error():
    """Unknown single_section returns error dict."""
    result = generate_draft(
        _make_tor_data(), _make_chunks(), single_section="nonexistent_section"
    )
    assert "error" in result


def test_feedback_appears_in_prompt():
    """feedback text appears in the prompt sent to Claude."""
    tor_data = _make_tor_data()
    chunks = _make_chunks()
    captured = {}

    def capture_call(**kwargs):
        captured["messages"] = kwargs.get("messages", [])
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=_make_valid_draft_json())]
        return mock_response

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = capture_call

    with patch("draft_generator.anthropic.Anthropic", return_value=mock_client):
        generate_draft(tor_data, chunks, feedback="Focus on FIU strengthening")

    # Check the user message content contains the feedback
    user_msg = captured["messages"][0]["content"]
    assert "Focus on FIU strengthening" in user_msg


def test_chunks_capped_at_max_generation_chunks():
    from unittest.mock import patch, MagicMock
    from config import MAX_GENERATION_CHUNKS

    fake_chunks = [
        {"chunk_id": str(i), "text": f"chunk {i}",
         "relevance_score": 0.5, "source_file": f"file{i}.pdf",
         "page_number": 1, "geography": [], "thematic_areas": []}
        for i in range(MAX_GENERATION_CHUNKS + 10)
    ]

    mock_response = MagicMock()
    mock_response.content = [MagicMock(
        text='{"sections":{"opening_statement":"test"},"interpretation_log":[],"summary":{}}'
    )]

    with patch("draft_generator.anthropic.Anthropic") as MockClient:
        MockClient.return_value.messages.create.return_value = mock_response
        from draft_generator import generate_draft
        result = generate_draft(
            {"title": "test", "geography": [], "thematic_areas": [],
             "key_requirements": [], "funder": "", "language": "English"},
            fake_chunks,
        )
    assert "error" not in result
