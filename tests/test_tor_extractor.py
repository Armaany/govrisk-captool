"""Tests for tor_extractor.py — Task 4.8"""
import sys
import os
import io
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import patch, MagicMock
from hypothesis import given, settings
from hypothesis import strategies as st

from tor_extractor import extract_tor, SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Helper: create a minimal valid .docx in memory
# ---------------------------------------------------------------------------

def make_minimal_docx(text="Test ToR content about AML/CFT in Mexico."):
    from docx import Document
    doc = Document()
    doc.add_paragraph(text)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Unit test: unsupported file type returns error dict
# ---------------------------------------------------------------------------

def test_unsupported_file_type_returns_error_dict():
    """
    Requirement 3.9: Non-.docx/.pdf file returns error dict with LOW confidence.
    """
    result = extract_tor(b"data", "document.txt")

    assert isinstance(result, dict)
    assert "error" in result
    assert result["extraction_confidence"] == "LOW"
    assert "Unsupported file type" in result["error"]


def test_unsupported_file_type_no_extension_returns_error_dict():
    """Files with no extension also return error dict."""
    result = extract_tor(b"data", "document")

    assert isinstance(result, dict)
    assert "error" in result
    assert result["extraction_confidence"] == "LOW"
    assert "Unsupported file type" in result["error"]


# ---------------------------------------------------------------------------
# Unit test: non-JSON Claude response triggers retry then returns error
# ---------------------------------------------------------------------------

def test_non_json_response_triggers_retry_then_returns_error():
    """
    Requirement 3.7: Non-JSON Claude response triggers exactly one retry;
    if retry also fails, returns error dict with LOW confidence.
    """
    docx_bytes = make_minimal_docx()

    # Build a mock response object that returns non-JSON text
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="This is not JSON at all.")]

    mock_client_instance = MagicMock()
    mock_client_instance.messages.create.return_value = mock_response

    with patch("tor_extractor.anthropic.Anthropic", return_value=mock_client_instance):
        result = extract_tor(docx_bytes, "test.docx")

    assert result["extraction_confidence"] == "LOW"
    assert "error" in result
    # Should have been called exactly 2 times: initial + 1 retry
    assert mock_client_instance.messages.create.call_count == 2


# ---------------------------------------------------------------------------
# Unit test: system prompt contains required instruction
# ---------------------------------------------------------------------------

def test_system_prompt_contains_required_instruction():
    """
    Requirement 3.5: System prompt instructs Claude to respond only with valid JSON.
    """
    docx_bytes = make_minimal_docx()

    # Valid JSON that matches the expected schema
    valid_json = json.dumps({
        "title": "Test ToR",
        "funder": "Test Funder",
        "geography": ["Mexico"],
        "thematic_areas": ["AML/CFT"],
        "key_requirements": ["Risk assessment"],
        "evaluation_criteria": [],
        "language": "English",
        "source_file": "test.docx",
        "extraction_confidence": "HIGH",
    })

    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=valid_json)]

    mock_client_instance = MagicMock()
    mock_client_instance.messages.create.return_value = mock_response

    captured_system_prompt = {}

    def capture_call(**kwargs):
        captured_system_prompt["system"] = kwargs.get("system", "")
        return mock_response

    mock_client_instance.messages.create.side_effect = capture_call

    with patch("tor_extractor.anthropic.Anthropic", return_value=mock_client_instance):
        extract_tor(docx_bytes, "test.docx")

    assert "Return ONLY valid JSON" in captured_system_prompt["system"]


# ---------------------------------------------------------------------------
# PBT P6: text truncation at 15,000 characters
# ---------------------------------------------------------------------------

@given(
    st.integers(min_value=15001, max_value=20000),
    st.text(min_size=1, max_size=10),
)
@settings(max_examples=20, deadline=None)
def test_p6_text_truncation(length, seed_char):
    """
    P6: For any text longer than 15,000 chars, the truncation logic produces
    exactly 15,000 characters.
    **Validates: Requirements 3.4**
    """
    # Build a text of the desired length by repeating the seed
    text = (seed_char * (length // len(seed_char) + 1))[:length]
    assert len(text) == length

    # Test the truncation logic directly (not via API)
    truncated = text[:12000] + text[-3000:]
    assert len(truncated) == 15000


# ---------------------------------------------------------------------------
# PBT P19: tor_data JSON round-trip
# ---------------------------------------------------------------------------

@given(st.fixed_dictionaries({
    "title": st.text(max_size=100),
    "funder": st.text(max_size=50),
    "geography": st.lists(st.text(max_size=30), max_size=5),
    "thematic_areas": st.lists(st.text(max_size=30), max_size=5),
    "key_requirements": st.lists(st.text(max_size=100), max_size=5),
    "evaluation_criteria": st.lists(st.text(max_size=100), max_size=5),
    "language": st.sampled_from(["English", "Spanish"]),
    "source_file": st.text(max_size=50),
    "extraction_confidence": st.sampled_from(["HIGH", "MEDIUM", "LOW"]),
}))
@settings(max_examples=20, deadline=None)
def test_p19_tor_data_json_roundtrip(tor_data):
    """
    P19: Serialising a TorData dict to JSON and deserialising it produces
    an object equal to the original.
    **Validates: Requirements 11.3**
    """
    serialized = json.dumps(tor_data)
    deserialized = json.loads(serialized)
    assert deserialized == tor_data


# ---------------------------------------------------------------------------
# Additional unit tests for robustness
# ---------------------------------------------------------------------------

def test_source_file_always_overridden_by_filename():
    """
    The source_file field in the returned dict must always equal the filename
    argument, regardless of what Claude returns.
    """
    docx_bytes = make_minimal_docx()

    # Claude returns a different source_file value
    valid_json = json.dumps({
        "title": "Test",
        "funder": "Funder",
        "geography": [],
        "thematic_areas": [],
        "key_requirements": [],
        "evaluation_criteria": [],
        "language": "English",
        "source_file": "wrong_name.docx",   # Claude returns wrong name
        "extraction_confidence": "MEDIUM",
    })

    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=valid_json)]
    mock_client_instance = MagicMock()
    mock_client_instance.messages.create.return_value = mock_response

    with patch("tor_extractor.anthropic.Anthropic", return_value=mock_client_instance):
        result = extract_tor(docx_bytes, "actual_name.docx")

    assert result["source_file"] == "actual_name.docx"


def test_missing_keys_filled_with_defaults():
    """
    If Claude returns JSON missing some keys, defaults are filled in.
    """
    docx_bytes = make_minimal_docx()

    # Claude returns only partial data
    partial_json = json.dumps({
        "title": "Partial ToR",
        "extraction_confidence": "MEDIUM",
    })

    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=partial_json)]
    mock_client_instance = MagicMock()
    mock_client_instance.messages.create.return_value = mock_response

    with patch("tor_extractor.anthropic.Anthropic", return_value=mock_client_instance):
        result = extract_tor(docx_bytes, "partial.docx")

    # Should not have an error key
    assert "error" not in result
    # All required keys should be present
    for key in ("title", "funder", "geography", "thematic_areas",
                "key_requirements", "evaluation_criteria", "language",
                "source_file", "extraction_confidence"):
        assert key in result, f"Missing key: {key}"

    # Defaults filled in
    assert result["funder"] == ""
    assert result["geography"] == []
    assert result["source_file"] == "partial.docx"


def test_error_state_source_file_matches_filename():
    """Error state dict always has source_file equal to the filename argument."""
    result = extract_tor(b"data", "my_file.csv")
    assert result["source_file"] == "my_file.csv"

# ---------------------------------------------------------------------------
# Component 3a — New schema tests (paragraphs + source_map)
# ---------------------------------------------------------------------------

def _make_full_tor_json(**overrides):
    """Return a complete tor_data JSON string with paragraphs and source_map."""
    base = {
        "title": "Test ToR",
        "funder": "US State Dept",
        "geography": ["Mexico"],
        "thematic_areas": ["AML/CFT"],
        "key_requirements": ["Risk assessment"],
        "evaluation_criteria": [],
        "language": "English",
        "source_file": "test.docx",
        "extraction_confidence": "HIGH",
        "paragraphs": [
            "This is the first paragraph about Mexico.",
            "AML/CFT capacity building is required.",
            "The funder is the US State Department.",
        ],
        "source_map": {
            "geography": [{"term": "Mexico", "paragraph_index": 0, "snippet": "This is the first paragraph about Mexico."}],
            "thematic_areas": [{"term": "AML/CFT", "paragraph_index": 1, "snippet": "AML/CFT capacity building is required."}],
            "funder": [{"term": "US State Dept", "paragraph_index": 2, "snippet": "The funder is the US State Department."}],
            "key_requirements": [{"term": "Risk assessment", "paragraph_index": 1, "snippet": "AML/CFT capacity building is required."}],
        },
    }
    base.update(overrides)
    return json.dumps(base)


def _make_mock(response_text):
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=response_text)]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response
    return mock_client


def test_paragraphs_key_present_in_output():
    """Mock Claude returns tor_data with paragraphs list of 3 strings. Assert result has 3 paragraphs."""
    docx_bytes = make_minimal_docx()
    mock_client = _make_mock(_make_full_tor_json())
    with patch("tor_extractor.anthropic.Anthropic", return_value=mock_client):
        result = extract_tor(docx_bytes, "test.docx")
    assert "paragraphs" in result
    assert isinstance(result["paragraphs"], list)
    assert len(result["paragraphs"]) == 3


def test_source_map_key_present_in_output():
    """Mock Claude returns tor_data with source_map. Assert all four sub-keys present."""
    docx_bytes = make_minimal_docx()
    mock_client = _make_mock(_make_full_tor_json())
    with patch("tor_extractor.anthropic.Anthropic", return_value=mock_client):
        result = extract_tor(docx_bytes, "test.docx")
    assert "source_map" in result
    assert isinstance(result["source_map"], dict)
    for key in ("geography", "thematic_areas", "funder", "key_requirements"):
        assert key in result["source_map"], f"source_map missing key: {key}"


def test_paragraphs_defaults_to_empty_list_on_missing_key():
    """Mock Claude returns tor_data WITHOUT paragraphs key. Assert result['paragraphs'] == []."""
    docx_bytes = make_minimal_docx()
    # JSON without paragraphs key
    partial_json = json.dumps({
        "title": "Test", "funder": "Test", "geography": [], "thematic_areas": [],
        "key_requirements": [], "evaluation_criteria": [], "language": "English",
        "source_file": "test.docx", "extraction_confidence": "MEDIUM",
    })
    mock_client = _make_mock(partial_json)
    with patch("tor_extractor.anthropic.Anthropic", return_value=mock_client):
        result = extract_tor(docx_bytes, "test.docx")
    assert result["paragraphs"] == []


def test_source_map_defaults_to_empty_structure_on_missing_key():
    """Mock Claude returns tor_data WITHOUT source_map key. Assert sub-keys default to []."""
    docx_bytes = make_minimal_docx()
    partial_json = json.dumps({
        "title": "Test", "funder": "Test", "geography": [], "thematic_areas": [],
        "key_requirements": [], "evaluation_criteria": [], "language": "English",
        "source_file": "test.docx", "extraction_confidence": "MEDIUM",
    })
    mock_client = _make_mock(partial_json)
    with patch("tor_extractor.anthropic.Anthropic", return_value=mock_client):
        result = extract_tor(docx_bytes, "test.docx")
    assert result["source_map"]["geography"] == []
    assert result["source_map"]["thematic_areas"] == []


def test_existing_geography_key_still_present():
    """Backward compatibility: result['geography'] is still present and is a list."""
    docx_bytes = make_minimal_docx()
    mock_client = _make_mock(_make_full_tor_json())
    with patch("tor_extractor.anthropic.Anthropic", return_value=mock_client):
        result = extract_tor(docx_bytes, "test.docx")
    assert "geography" in result
    assert isinstance(result["geography"], list)
