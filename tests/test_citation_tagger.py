"""Tests for citation_tagger.py — Task 6.6"""
import sys
import os
import re

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from citation_tagger import tag_citations, format_citation, REF_PATTERN, CLEAN_PATTERN


# ---------------------------------------------------------------------------
# Unit tests (example-based)
# ---------------------------------------------------------------------------

def test_ref_tags_removed_from_text():
    """REF tags are stripped from the output text."""
    result = tag_citations({"section": "Some text [REF:doc.pdf:page_3] here."})
    assert result["paragraphs"]
    para = result["paragraphs"][0]
    assert "[REF:" not in para["text"]
    assert "Some text" in para["text"]
    assert "here." in para["text"]


def test_citations_extracted_correctly():
    """Filename and page number are extracted correctly from a REF tag."""
    result = tag_citations({"section": "Evidence [REF:report_2023.pdf:page_7]."})
    assert result["paragraphs"]
    para = result["paragraphs"][0]
    assert len(para["citations"]) == 1
    assert para["citations"][0]["filename"] == "report_2023.pdf"
    assert para["citations"][0]["page"] == 7


def test_duplicate_citations_deduplicated():
    """Same REF tag appearing twice in one paragraph yields one citation."""
    text = "Claim [REF:doc.pdf:page_2] and again [REF:doc.pdf:page_2]."
    result = tag_citations({"section": text})
    assert result["paragraphs"]
    para = result["paragraphs"][0]
    matching = [c for c in para["citations"] if c["filename"] == "doc.pdf" and c["page"] == 2]
    assert len(matching) == 1


def test_citation_format_string():
    """format_citation returns the expected display string."""
    assert format_citation("doc.pdf", 3) == "Source: doc.pdf, p.3"


def test_no_ref_tags_returns_empty_citations():
    """A paragraph with no REF tags produces an empty citations list."""
    result = tag_citations({"section": "Plain text with no references."})
    assert result["paragraphs"]
    para = result["paragraphs"][0]
    assert para["citations"] == []


def test_empty_paragraphs_skipped():
    """Paragraphs that are empty after cleaning REF tags are not included."""
    # A section that is only a REF tag — clean text will be empty
    result = tag_citations({"section": "[REF:doc.pdf:page_1]"})
    assert result["paragraphs"] == []


def test_non_string_sections_skipped():
    """country_table list value is not processed and does not appear in paragraphs."""
    sections = {
        "country_table": [{"country": "Mexico", "project_count": 3}],
        "opening_statement": "GovRisk overview [REF:doc.pdf:page_1].",
    }
    result = tag_citations(sections)
    # Only the string section should produce paragraphs
    assert len(result["paragraphs"]) == 1
    assert "GovRisk overview" in result["paragraphs"][0]["text"]


def test_multiple_paragraphs_split_correctly():
    """Text separated by double newline produces multiple paragraph entries."""
    text = "First paragraph [REF:a.pdf:page_1].\n\nSecond paragraph [REF:b.pdf:page_2]."
    result = tag_citations({"section": text})
    assert len(result["paragraphs"]) == 2
    texts = [p["text"] for p in result["paragraphs"]]
    assert any("First paragraph" in t for t in texts)
    assert any("Second paragraph" in t for t in texts)


def test_tag_citations_never_raises():
    """tag_citations must not raise for None, empty dict, or malformed input."""
    # None input
    try:
        result = tag_citations(None)
        assert isinstance(result, dict)
    except Exception as exc:
        pytest.fail(f"tag_citations(None) raised: {exc}")

    # Empty dict
    try:
        result = tag_citations({})
        assert result == {"paragraphs": []}
    except Exception as exc:
        pytest.fail(f"tag_citations({{}}) raised: {exc}")

    # Malformed / unexpected types
    for bad_input in [42, "string", [], {"k": None}, {"k": 123}]:
        try:
            result = tag_citations(bad_input)
            assert isinstance(result, dict)
        except Exception as exc:
            pytest.fail(f"tag_citations({bad_input!r}) raised: {exc}")


# ---------------------------------------------------------------------------
# PBT P12: output text contains no REF tag patterns
# ---------------------------------------------------------------------------

@given(
    st.text(max_size=200).map(lambda t: t + " [REF:doc.pdf:page_1]")
)
@settings(max_examples=20, deadline=None)
def test_p12_no_ref_tags_in_output(text_with_ref):
    """P12: After tag_citations, no [REF:...] patterns remain in any paragraph text.
    **Validates: Requirements 6.2**
    """
    result = tag_citations({"section": text_with_ref})
    clean_pattern = re.compile(r'\[REF:[^\]]+\]')
    for para in result["paragraphs"]:
        assert not clean_pattern.search(para["text"]), \
            f"REF tag found in output: {para['text'][:100]}"


# ---------------------------------------------------------------------------
# PBT P13: duplicate citations deduplicated
# ---------------------------------------------------------------------------

@given(
    st.text(min_size=1, max_size=50, alphabet=st.characters(
        whitelist_categories=("Lu", "Ll", "Nd"),
        whitelist_characters=" "
    )),
    st.integers(min_value=1, max_value=100)
)
@settings(max_examples=20, deadline=None)
def test_p13_duplicate_citations_deduplicated(filename, page):
    """P13: Duplicate [REF:filename:page_N] tags in same paragraph → one citation.
    **Validates: Requirements 6.3**
    """
    safe_filename = filename.strip() or "doc.pdf"
    text = (
        f"Some text [REF:{safe_filename}:page_{page}] "
        f"more text [REF:{safe_filename}:page_{page}]"
    )
    result = tag_citations({"section": text})
    if result["paragraphs"]:
        para = result["paragraphs"][0]
        matching = [
            c for c in para["citations"]
            if c["filename"] == safe_filename and c["page"] == page
        ]
        assert len(matching) == 1, \
            f"Expected 1 citation, got {len(matching)}: {para['citations']}"


# ---------------------------------------------------------------------------
# PBT P14: citation format matches pattern
# ---------------------------------------------------------------------------

@given(
    st.text(min_size=1, max_size=50, alphabet=st.characters(
        whitelist_categories=("Lu", "Ll", "Nd"),
        whitelist_characters="._- "
    )),
    st.integers(min_value=1, max_value=999)
)
@settings(max_examples=20, deadline=None)
def test_p14_citation_format(filename, page):
    """P14: format_citation produces exactly 'Source: filename, p.N'.
    **Validates: Requirements 6.4**
    """
    result = format_citation(filename, page)
    assert result == f"Source: {filename}, p.{page}"
    assert result.startswith("Source: ")
    assert f", p.{page}" in result


# ---------------------------------------------------------------------------
# PBT P11 complement: paragraphs with no REF tags have empty citations list
# ---------------------------------------------------------------------------

@given(
    st.text(min_size=1, max_size=200, alphabet=st.characters(
        whitelist_categories=("Lu", "Ll", "Nd", "Zs"),
        whitelist_characters=".,!? "
    ))
)
@settings(max_examples=20, deadline=None)
def test_p11_complement_no_ref_tags_empty_citations(text_without_refs):
    """P11 complement: paragraphs with no REF tags have empty citations list.
    **Validates: Requirements 9.1**
    """
    assume('[REF:' not in text_without_refs)
    result = tag_citations({"section": text_without_refs})
    for para in result["paragraphs"]:
        assert para["citations"] == [], \
            f"Expected empty citations for text without REF tags, got: {para['citations']}"
