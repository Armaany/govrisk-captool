"""Focused regression tests for demo-readiness fixes.

Covers:
- Relevance display: qualitative (low/medium/high), numeric, blank/malformed.
- Case-insensitive keyword deduplication preserving first readable spelling.
- Blank/malformed optional fields degrade without crashing.
- Selection instruction text is a single accurate string.
- Button label rename.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from opportunity_panel import (
    clear_selected_opportunity,
    deduplicate_keywords,
    format_relevance,
    get_selected_opportunity,
    parse_matched_keywords,
    parse_opportunities_csv,
    REQUIRED_HEADERS,
    select_opportunity,
)


# ---------------------------------------------------------------------------
# Relevance display
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("low", "Low"),
        ("medium", "Medium"),
        ("high", "High"),
        ("HIGH", "HIGH"),
        ("Medium", "Medium"),
    ],
)
def test_qualitative_relevance_displayed_accurately(raw, expected):
    assert format_relevance(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("0.82", "0.82"),
        ("1", "1"),
        ("0", "0"),
        ("  3.5 ", "3.5"),
    ],
)
def test_numeric_relevance_still_supported(raw, expected):
    assert format_relevance(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", None])
def test_blank_relevance_degrades_to_unavailable(raw):
    assert format_relevance(raw) == "Unavailable"


def test_malformed_relevance_shown_verbatim_not_crashing():
    # A malformed non-numeric string is shown as-is (title-cased first char),
    # never crashes, never silently hidden as "Unavailable".
    assert format_relevance("n/a") == "N/a"


# ---------------------------------------------------------------------------
# Keyword deduplication (case-insensitive, first spelling wins, accents kept)
# ---------------------------------------------------------------------------

def test_keyword_dedup_case_insensitive_preserves_first_spelling():
    result = deduplicate_keywords(["Corruption", "corruption", "CORRUPTION"])
    assert result == ["Corruption"]


def test_keyword_dedup_preserves_accented_spanish():
    result = deduplicate_keywords(["anticorrupción", "Anticorrupción", "asset recovery"])
    assert result == ["anticorrupción", "asset recovery"]


def test_keyword_dedup_drops_blank_and_none():
    result = deduplicate_keywords(["", "  ", None, "justice", "Justice"])
    assert result == ["justice"]


def test_keyword_dedup_empty_input():
    assert deduplicate_keywords([]) == []
    assert deduplicate_keywords(None) == []


def test_aggregate_keyword_dedup_case_insensitive():
    aggregate = [
        "Corruption",
        "corruption",
        "CORRUPTION",
        "anticorrupción",
    ]
    assert deduplicate_keywords(aggregate) == ["Corruption", "anticorrupción"]


# ---------------------------------------------------------------------------
# Blank / malformed optional fields must not crash the grid parser
# ---------------------------------------------------------------------------

def _csv_with(**overrides):
    import csv, io, json
    values = {h: "" for h in REQUIRED_HEADERS}
    values.update({
        "portal_source": "undp",
        "opportunity_title": "Test",
        "opportunity_link": "https://example.test/x",
    })
    values.update(overrides)
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(REQUIRED_HEADERS)
    w.writerow([values[h] for h in REQUIRED_HEADERS])
    return out.getvalue()


def test_blank_optional_fields_parse_without_crash():
    rows = parse_opportunities_csv(_csv_with(
        relevance_score="",
        matched_keywords="",
        scraped_at="",
        deadline="",
        contract_value="",
    ))
    row = rows[0]
    assert row["relevance_score_number"] is None
    assert row["matched_keywords_list"] == []
    assert row["scraped_at_datetime"] is None
    # And the display helpers degrade gracefully.
    assert format_relevance(row["relevance_score"]) == "Unavailable"
    assert deduplicate_keywords(row["matched_keywords_list"]) == []


def test_malformed_keyword_cell_does_not_crash_grid():
    rows = parse_opportunities_csv(_csv_with(matched_keywords="{not json"))
    assert rows[0]["matched_keywords_list"] == []


def test_qualitative_relevance_flows_through_parser():
    rows = parse_opportunities_csv(_csv_with(relevance_score="high"))
    # relevance_score_number is None (not numeric) but the display shows "High".
    assert rows[0]["relevance_score_number"] is None
    assert format_relevance(rows[0]["relevance_score"]) == "High"


# ---------------------------------------------------------------------------
# Selection UX: button rename, single accurate instruction, clear/change
# ---------------------------------------------------------------------------

import os as _os


def _panel_source():
    path = _os.path.join(_os.path.dirname(__file__), "..", "opportunity_panel.py")
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def _app_source():
    path = _os.path.join(_os.path.dirname(__file__), "..", "app.py")
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def test_button_renamed_to_select_for_capability_statement():
    src = _panel_source()
    assert "Select for capability statement" in src
    assert "Use this opportunity" not in src


def test_single_accurate_selection_instruction_present():
    src = _panel_source()
    assert "Opportunity selected:" in src
    assert (
        "Open the opportunity, download the " in src
        and "ToR, then upload it below to begin." in src
    )
    # No automatic-action implication.
    assert "downloads the ToR" not in src
    assert "automatically" not in src.lower()


def test_duplicate_confirmation_removed_from_app():
    src = _app_source()
    # The old blue st.info confirmation must be gone.
    assert "Preparing a capability statement for:" not in src


def test_clear_or_change_selection_control_present():
    src = _panel_source()
    assert "Change or clear selection" in src


# ---------------------------------------------------------------------------
# Selection and clear/change behaviour via session-state contract
# ---------------------------------------------------------------------------

def test_selection_helpers_drive_real_session_state_contract():
    """Exercise the helpers used by the real select and clear buttons."""
    session = {"selected_opportunity": None, "tor_data": None}

    opportunity = {"opportunity_title": "Justice reform", "opportunity_link": "https://x/1"}
    select_opportunity(session, opportunity)
    assert get_selected_opportunity(session) == opportunity

    # Selection intentionally does not populate or mutate the ToR upload state.
    assert session["tor_data"] is None

    clear_selected_opportunity(session)
    assert get_selected_opportunity(session) is None
    assert session["tor_data"] is None

    other = {"opportunity_title": "AML supervision", "opportunity_link": "https://x/2"}
    select_opportunity(session, other)
    assert get_selected_opportunity(session) == other
    assert session["tor_data"] is None


def test_selected_opportunity_is_a_session_default():
    src = _app_source()
    assert '"selected_opportunity"' in src or "'selected_opportunity'" in src
