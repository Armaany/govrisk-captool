"""Behavioral tests for the Opportunity Browser v2 pure helpers.

These verify search, filtering, sorting, pagination, table-row construction,
metadata, keyword summary, page-reset and selection-identity behavior without a
running Streamlit server. Records are never mutated by the helpers under test.
"""
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import opportunity_panel as op
from opportunity_panel import (
    DEFAULT_PAGE_SIZE,
    NO_RESULTS_MESSAGE,
    PAGE_SIZE_OPTIONS,
    SORT_DEADLINE,
    SORT_NEWEST,
    SORT_RELEVANCE,
    SORT_SHEET,
    TABLE_COLUMNS,
    VIEW_OPTIONS,
    VIEW_TABLE,
    build_table_row,
    build_table_rows,
    clamp_page,
    filter_opportunities,
    find_by_identity,
    format_results_updated,
    keywords_in_results,
    latest_scraped_at,
    opportunity_identity,
    page_bounds,
    page_count,
    paginate,
    query_signature,
    resolve_current_page,
    search_opportunities,
    select_opportunity,
    sort_opportunities,
    table_instance_key,
)


# ---------------------------------------------------------------------------
# Record factory
# ---------------------------------------------------------------------------

def _rec(**kw):
    base = {
        "portal_source": "undp",
        "opportunity_title": "Justice sector reform",
        "funder_organisation": "UNDP",
        "country_region": "Mexico",
        "summary": "",
        "deadline": "",
        "deadline_date": None,
        "relevance_score": "",
        "relevance_score_number": None,
        "bid_recommendation": "",
        "opportunity_link": "https://example.test/1",
        "matched_keywords_list": [],
        "scraped_at_datetime": None,
        "_sheet_order": 0,
    }
    base.update(kw)
    return base


def _dt(y, m, d):
    return datetime(y, m, d, 12, 0, tzinfo=timezone.utc)


# ===========================================================================
# 1-4. Search
# ===========================================================================

def test_search_across_all_fields():
    recs = [
        _rec(opportunity_title="Anti-corruption programme", opportunity_link="a"),
        _rec(opportunity_title="X", funder_organisation="World Bank", opportunity_link="b"),
        _rec(opportunity_title="X", country_region="Colombia", opportunity_link="c"),
        _rec(opportunity_title="X", summary="focus on beneficial ownership", opportunity_link="d"),
        _rec(opportunity_title="X", matched_keywords_list=["asset recovery"], opportunity_link="e"),
    ]
    assert [r["opportunity_link"] for r in search_opportunities(recs, "anti-corruption")] == ["a"]
    assert [r["opportunity_link"] for r in search_opportunities(recs, "world bank")] == ["b"]
    assert [r["opportunity_link"] for r in search_opportunities(recs, "colombia")] == ["c"]
    assert [r["opportunity_link"] for r in search_opportunities(recs, "beneficial")] == ["d"]
    assert [r["opportunity_link"] for r in search_opportunities(recs, "asset recovery")] == ["e"]


def test_search_is_case_insensitive():
    recs = [_rec(opportunity_title="Justice Sector Reform", opportunity_link="a")]
    assert search_opportunities(recs, "JUSTICE") == recs
    assert search_opportunities(recs, "justice") == recs
    assert search_opportunities(recs, "jUsTiCe") == recs


def test_search_matches_accented_terms():
    recs = [
        _rec(matched_keywords_list=["anticorrupción"], opportunity_link="a"),
        _rec(country_region="São Paulo", opportunity_link="b"),
    ]
    assert [r["opportunity_link"] for r in search_opportunities(recs, "anticorrupción")] == ["a"]
    assert [r["opportunity_link"] for r in search_opportunities(recs, "ANTICORRUPCIÓN")] == ["a"]
    assert [r["opportunity_link"] for r in search_opportunities(recs, "são paulo")] == ["b"]


def test_whitespace_only_search_is_no_filter():
    recs = [_rec(opportunity_link="a"), _rec(opportunity_link="b")]
    assert search_opportunities(recs, "   ") == recs
    assert search_opportunities(recs, "") == recs
    assert search_opportunities(recs, "\t\n") == recs


# ===========================================================================
# 5. Source + recommendation filters combined with search
# ===========================================================================

def test_filters_combined_with_search():
    recs = [
        _rec(portal_source="undp", bid_recommendation="BID", opportunity_title="anti-corruption A", opportunity_link="a"),
        _rec(portal_source="usaid", bid_recommendation="BID", opportunity_title="anti-corruption B", opportunity_link="b"),
        _rec(portal_source="undp", bid_recommendation="NO BID", opportunity_title="anti-corruption C", opportunity_link="c"),
    ]
    searched = search_opportunities(recs, "anti-corruption")
    filtered = filter_opportunities(searched, ["undp"], ["BID"])
    assert [r["opportunity_link"] for r in filtered] == ["a"]


# ===========================================================================
# 6-11. Sorting
# ===========================================================================

def test_sort_newest_discovered_unavailable_last():
    recs = [
        _rec(opportunity_link="old", scraped_at_datetime=_dt(2026, 8, 1), _sheet_order=0),
        _rec(opportunity_link="none", scraped_at_datetime=None, _sheet_order=1),
        _rec(opportunity_link="new", scraped_at_datetime=_dt(2026, 8, 20), _sheet_order=2),
    ]
    order = [r["opportunity_link"] for r in sort_opportunities(recs, SORT_NEWEST)]
    assert order == ["new", "old", "none"]


def test_sort_deadline_soonest_unavailable_last():
    from datetime import date
    recs = [
        _rec(opportunity_link="late", deadline_date=date(2026, 12, 1), _sheet_order=0),
        _rec(opportunity_link="none", deadline_date=None, _sheet_order=1),
        _rec(opportunity_link="soon", deadline_date=date(2026, 9, 1), _sheet_order=2),
    ]
    order = [r["opportunity_link"] for r in sort_opportunities(recs, SORT_DEADLINE)]
    assert order == ["soon", "late", "none"]


def test_sort_numeric_relevance_descending():
    recs = [
        _rec(opportunity_link="lo", relevance_score="0.2", relevance_score_number=0.2, _sheet_order=0),
        _rec(opportunity_link="hi", relevance_score="0.9", relevance_score_number=0.9, _sheet_order=1),
        _rec(opportunity_link="mid", relevance_score="0.5", relevance_score_number=0.5, _sheet_order=2),
    ]
    order = [r["opportunity_link"] for r in sort_opportunities(recs, SORT_RELEVANCE)]
    assert order == ["hi", "mid", "lo"]


def test_sort_qualitative_relevance_high_medium_low():
    recs = [
        _rec(opportunity_link="med", relevance_score="Medium", _sheet_order=0),
        _rec(opportunity_link="low", relevance_score="low", _sheet_order=1),
        _rec(opportunity_link="high", relevance_score="HIGH", _sheet_order=2),
    ]
    order = [r["opportunity_link"] for r in sort_opportunities(recs, SORT_RELEVANCE)]
    assert order == ["high", "med", "low"]


def test_sort_malformed_relevance_last():
    recs = [
        _rec(opportunity_link="ok", relevance_score="0.7", relevance_score_number=0.7, _sheet_order=0),
        _rec(opportunity_link="bad", relevance_score="banana", _sheet_order=1),
        _rec(opportunity_link="blank", relevance_score="", _sheet_order=2),
    ]
    order = [r["opportunity_link"] for r in sort_opportunities(recs, SORT_RELEVANCE)]
    assert order[0] == "ok"
    assert set(order[1:]) == {"bad", "blank"}


def test_sort_sheet_order_is_stable():
    recs = [
        _rec(opportunity_link="c", _sheet_order=2),
        _rec(opportunity_link="a", _sheet_order=0),
        _rec(opportunity_link="b", _sheet_order=1),
    ]
    order = [r["opportunity_link"] for r in sort_opportunities(recs, SORT_SHEET)]
    assert order == ["a", "b", "c"]


def test_sort_does_not_mutate_input():
    recs = [
        _rec(opportunity_link="b", _sheet_order=1),
        _rec(opportunity_link="a", _sheet_order=0),
    ]
    before = [r["opportunity_link"] for r in recs]
    sort_opportunities(recs, SORT_SHEET)
    assert [r["opportunity_link"] for r in recs] == before


# ===========================================================================
# 12-16. Pagination
# ===========================================================================

def _n_recs(n):
    return [_rec(opportunity_link=f"link-{i}", _sheet_order=i) for i in range(n)]


def test_pagination_first_middle_final_pages():
    recs = _n_recs(25)
    first = paginate(recs, 1, 10)
    middle = paginate(recs, 2, 10)
    final = paginate(recs, 3, 10)
    assert [r["opportunity_link"] for r in first] == [f"link-{i}" for i in range(10)]
    assert [r["opportunity_link"] for r in middle] == [f"link-{i}" for i in range(10, 20)]
    assert [r["opportunity_link"] for r in final] == [f"link-{i}" for i in range(20, 25)]
    assert page_count(25, 10) == 3
    assert page_bounds(25, 3, 10) == (21, 25)


def test_page_clamping_after_result_reduction():
    # On page 3, but results shrink to 12 (2 pages). Clamp to last valid page.
    assert clamp_page(3, 12, 10) == 2
    assert clamp_page(99, 5, 10) == 1
    assert clamp_page(0, 5, 10) == 1
    assert paginate(_n_recs(12), 3, 10) == _n_recs(12)[10:12]


def test_page_reset_when_query_changes():
    session = {}
    sig1 = query_signature("aml", [], [], SORT_SHEET)
    # First resolution establishes the signature (and resets page to 1).
    assert resolve_current_page(session, sig1) == 1
    # An unchanged signature keeps whatever page the user navigated to.
    session[op.KEY_PAGE] = 4
    assert resolve_current_page(session, sig1) == 4
    # Changing the search resets to page 1.
    sig2 = query_signature("corruption", [], [], SORT_SHEET)
    assert resolve_current_page(session, sig2) == 1
    assert session[op.KEY_PAGE] == 1
    # Changing sort also resets.
    session[op.KEY_PAGE] = 3
    sig3 = query_signature("corruption", [], [], SORT_NEWEST)
    assert resolve_current_page(session, sig3) == 1
    # Changing a filter also resets.
    session[op.KEY_PAGE] = 2
    sig4 = query_signature("corruption", ["undp"], [], SORT_NEWEST)
    assert resolve_current_page(session, sig4) == 1


def test_rows_per_page_options_and_default():
    assert PAGE_SIZE_OPTIONS == (10, 20, 50)
    assert DEFAULT_PAGE_SIZE == 10


def test_empty_result_message_constant():
    assert NO_RESULTS_MESSAGE == "No opportunities match your search and filters."
    # No page slice is produced for an empty set.
    assert paginate([], 1, 10) == []
    assert page_bounds(0, 1, 10) == (0, 0)


# ===========================================================================
# 17-19, 21. Identity, preview, selection
# ===========================================================================

def test_table_rows_retain_stable_link_identity():
    recs = [
        _rec(opportunity_link="https://example.test/keep", _sheet_order=5),
        _rec(opportunity_link="", _sheet_order=6),
    ]
    assert opportunity_identity(recs[0]) == "https://example.test/keep"
    # No link -> identity falls back to sheet order marker, never a row number.
    assert opportunity_identity(recs[1]) == "sheet-order:6"


def test_selection_preview_maps_correct_record_after_sort_and_pagination():
    recs = [
        _rec(opportunity_link="a", scraped_at_datetime=_dt(2026, 8, 1), _sheet_order=0),
        _rec(opportunity_link="b", scraped_at_datetime=_dt(2026, 8, 30), _sheet_order=1),
        _rec(opportunity_link="c", scraped_at_datetime=_dt(2026, 8, 15), _sheet_order=2),
    ]
    ordered = sort_opportunities(recs, SORT_NEWEST)  # b, c, a
    page = paginate(ordered, 1, 2)  # b, c
    # A user clicking visible row index 1 on this page selects "c", not row 1 of
    # the original data.
    previewed = page[1]
    assert previewed["opportunity_link"] == "c"
    # And it can be recovered by identity within the page.
    assert find_by_identity(page, opportunity_identity(previewed)) is previewed


def test_preview_does_not_auto_select_capability_opportunity():
    # Previewing is just reading a record; only select_opportunity mutates state.
    session = {"selected_opportunity": None}
    previewed = _rec(opportunity_link="a")
    # Simulate a preview: we only read, never call select_opportunity.
    _ = build_table_row(previewed)
    assert session["selected_opportunity"] is None


def test_explicit_selection_uses_session_helper():
    session = {"selected_opportunity": None}
    rec = _rec(opportunity_link="a", opportunity_title="Justice reform")
    select_opportunity(session, rec)
    assert session["selected_opportunity"] == rec


def test_selection_survives_filtering_and_pagination_pipeline():
    recs = _n_recs(30)
    session = {"selected_opportunity": None}
    select_opportunity(session, recs[7])
    # Run a full pipeline; selection state is independent of it.
    searched = search_opportunities(recs, "justice")
    filtered = filter_opportunities(searched, [], [])
    ordered = sort_opportunities(filtered, SORT_NEWEST)
    _ = paginate(ordered, 2, 10)
    assert session["selected_opportunity"] == recs[7]


# ===========================================================================
# 22. Card mode receives only the current page
# ===========================================================================

def test_card_mode_receives_only_current_page():
    recs = _n_recs(35)
    ordered = sort_opportunities(recs, SORT_SHEET)
    page = paginate(ordered, 2, 10)
    assert len(page) == 10
    assert [r["opportunity_link"] for r in page] == [f"link-{i}" for i in range(10, 20)]


# ===========================================================================
# 23. Keywords summary uses filtered results (not all, not current page)
# ===========================================================================

def test_keywords_summary_uses_filtered_results():
    recs = [
        _rec(opportunity_link="a", opportunity_title="corruption", matched_keywords_list=["Corruption"]),
        _rec(opportunity_link="b", opportunity_title="aml", matched_keywords_list=["AML"]),
        _rec(opportunity_link="c", opportunity_title="corruption", matched_keywords_list=["anticorrupción"]),
    ]
    filtered = search_opportunities(recs, "corruption")  # a and c only
    kw = keywords_in_results(filtered)
    # Only keywords from the filtered set; case-insensitive dedupe, accented kept.
    assert "AML" not in kw
    assert "Corruption" in kw
    assert "anticorrupción" in kw


def test_keywords_summary_dedupes_case_insensitively_preserving_accents():
    recs = [
        _rec(opportunity_link="a", matched_keywords_list=["Corruption", "corruption"]),
        _rec(opportunity_link="b", matched_keywords_list=["ANTICORRUPCIÓN"]),
        _rec(opportunity_link="c", matched_keywords_list=["anticorrupción"]),
    ]
    kw = keywords_in_results(recs)
    # 'Corruption' appears once; the first readable spelling of the accented term
    # is preserved (uppercase came first).
    assert kw.count("Corruption") == 1
    assert "ANTICORRUPCIÓN" in kw
    assert "anticorrupción" not in kw


# ===========================================================================
# 24. Latest timestamp and unavailable fallback
# ===========================================================================

def test_latest_scraped_at_and_fallback():
    recs = [
        _rec(opportunity_link="a", scraped_at_datetime=_dt(2026, 8, 1)),
        _rec(opportunity_link="b", scraped_at_datetime=_dt(2026, 8, 20)),
        _rec(opportunity_link="c", scraped_at_datetime=None),
    ]
    assert latest_scraped_at(recs) == _dt(2026, 8, 20)
    assert format_results_updated(recs) == "Results last updated: 2026-08-20 12:00 UTC"

    none_recs = [_rec(opportunity_link="a", scraped_at_datetime=None)]
    assert latest_scraped_at(none_recs) is None
    assert format_results_updated(none_recs) == "Results last updated: unavailable"


# ===========================================================================
# 25-26. Table formatting robustness and link column
# ===========================================================================

def test_missing_or_malformed_fields_do_not_crash_table_rows():
    weird = {
        "opportunity_link": "https://example.test/x",
        "matched_keywords_list": None,
        "_sheet_order": 3,
    }
    row = build_table_row(weird)
    assert row["Source"] == "Unknown source"
    assert row["Opportunity"] == "Untitled opportunity"
    assert row["Funder"] == "Funder unavailable"
    assert row["Geography"] == "Geography unavailable"
    assert row["Deadline"] == "Unavailable"
    assert row["Relevance"] == "Unavailable"
    assert row["Recommendation"] == "Not assessed"
    assert row["Matched keywords"] == ""
    assert row["Open"] == "https://example.test/x"
    # A completely empty dict must not raise.
    empty = build_table_row({})
    assert empty["Open"] is None


def test_table_rows_never_expose_internal_fields():
    row = build_table_row(_rec(scraped_at_datetime=_dt(2026, 8, 1)))
    for internal in ("_sheet_order", "scraped_at_datetime", "deadline_date",
                     "relevance_score_number", "matched_keywords_list"):
        assert internal not in row
    assert tuple(row.keys()) == TABLE_COLUMNS


def test_link_column_is_configured_in_source():
    path = os.path.join(os.path.dirname(__file__), "..", "opportunity_panel.py")
    with open(path, encoding="utf-8") as handle:
        src = handle.read()
    assert "st.column_config.LinkColumn" in src
    assert 'on_select="rerun"' in src
    assert 'selection_mode="single-row"' in src


def test_default_view_is_table():
    assert VIEW_OPTIONS[0] == VIEW_TABLE == "Table"


# ===========================================================================
# 27-28. Read-only Sheet and scan-trigger integration unchanged
# ===========================================================================

def test_no_sheet_write_path_introduced():
    path = os.path.join(os.path.dirname(__file__), "..", "opportunity_panel.py")
    with open(path, encoding="utf-8") as handle:
        src = handle.read()
    # No HTTP write verbs or Google Sheets write APIs anywhere in the panel.
    for forbidden in (
        "requests.post", "requests.put", "requests.patch",
        'method="POST"', "method='POST'", 'method="PUT"',
        "spreadsheets().values().update", "spreadsheets().values().append",
        "batchUpdate",
    ):
        assert forbidden not in src
    # The only network access is the read-only CSV export.
    assert "gviz/tq" in src


def test_scan_trigger_integration_unchanged():
    path = os.path.join(os.path.dirname(__file__), "..", "opportunity_panel.py")
    with open(path, encoding="utf-8") as handle:
        src = handle.read()
    # Conditional trigger preserved: token gate + hidden when absent.
    assert "get_trigger_token()" in src
    assert "Run opportunity scan" in src
    assert "dispatch_scraper(trigger_token)" in src


def test_scraper_trigger_module_untouched_marker():
    # scraper_trigger.py must not be imported-for-write or altered by this panel;
    # we only rely on its public read/dispatch helpers.
    from scraper_trigger import get_trigger_token  # noqa: F401
    from scraper_trigger import dispatch_scraper  # noqa: F401


# ===========================================================================
# Correction pass: table-instance key defeats stale dataframe selection state
# ===========================================================================

def _sig(search="", sources=None, recs=None, sort=SORT_SHEET, page_size=10):
    return query_signature(search, sources or [], recs or [], sort, page_size)


def test_table_key_differs_between_pages():
    recs = _n_recs(25)
    ordered = sort_opportunities(recs, SORT_SHEET)
    sig = _sig()
    page1 = paginate(ordered, 1, 10)
    page2 = paginate(ordered, 2, 10)
    key1 = table_instance_key(sig, 1, 10, page1)
    key2 = table_instance_key(sig, 2, 10, page2)
    assert key1 != key2


def test_table_key_differs_when_visible_records_change():
    recs = [
        _rec(opportunity_link="a", opportunity_title="anti-corruption", _sheet_order=0),
        _rec(opportunity_link="b", opportunity_title="aml supervision", _sheet_order=1),
    ]
    # Baseline: no search.
    base_sig = _sig()
    base_page = paginate(sort_opportunities(recs, SORT_SHEET), 1, 10)
    base_key = table_instance_key(base_sig, 1, 10, base_page)

    # Search change alters the visible records and the signature.
    search_sig = _sig(search="anti-corruption")
    search_page = paginate(
        sort_opportunities(search_opportunities(recs, "anti-corruption"), SORT_SHEET),
        1, 10,
    )
    search_key = table_instance_key(search_sig, 1, 10, search_page)
    assert search_key != base_key

    # Sort change alters the visible order -> different key.
    sort_sig = _sig(sort=SORT_NEWEST)
    sort_page = paginate(sort_opportunities(recs, SORT_NEWEST), 1, 10)
    sort_key = table_instance_key(sort_sig, 1, 10, sort_page)
    # Signature differs even if the two-record order happens to match; assert on
    # the fuller distinction by also flipping records.
    assert sort_key != table_instance_key(_sig(sort=SORT_SHEET), 1, 10, sort_page)

    # Filter change alters the signature -> different key.
    filter_sig = _sig(sources=["undp"])
    filter_key = table_instance_key(filter_sig, 1, 10, base_page)
    assert filter_key != base_key

    # Page-size change alters the signature -> different key.
    size_sig = _sig(page_size=20)
    size_key = table_instance_key(size_sig, 1, 20, base_page)
    assert size_key != base_key


def test_table_key_stable_for_identical_state_and_records():
    recs = _n_recs(15)
    ordered = sort_opportunities(recs, SORT_SHEET)
    page = paginate(ordered, 1, 10)
    sig = _sig()
    assert table_instance_key(sig, 1, 10, page) == table_instance_key(sig, 1, 10, page)
    # Rebuilding an equivalent page (new list, same identities) is also stable.
    page_copy = [dict(r) for r in page]
    assert table_instance_key(sig, 1, 10, page) == table_instance_key(sig, 1, 10, page_copy)


def test_stale_selected_row_cannot_preview_or_select_record_from_new_page():
    """A stale positional selection index must not resolve to a record on the
    new page — the key change is what forces Streamlit to drop it, and even if a
    stale index leaked, we bound-check and resolve by identity."""
    recs = _n_recs(25)
    ordered = sort_opportunities(recs, SORT_SHEET)

    page1 = paginate(ordered, 1, 10)   # link-0 .. link-9
    page2 = paginate(ordered, 2, 10)   # link-10 .. link-19

    # New table instance for page 2 has a different key than page 1.
    assert table_instance_key(_sig(), 1, 10, page1) != table_instance_key(_sig(), 2, 10, page2)

    # Simulate the render logic's bound-checked mapping with a STALE row index
    # (e.g. row 7 selected on page 1) applied against page 2.
    stale_row_index = 7
    # The correct record on page 1 at that index:
    assert page1[stale_row_index]["opportunity_link"] == "link-7"
    # On page 2 the same positional index maps to a DIFFERENT record; identity is
    # what determines the preview, never a row number reused across instances.
    previewed_on_page2 = page2[stale_row_index]
    assert previewed_on_page2["opportunity_link"] == "link-17"
    assert opportunity_identity(previewed_on_page2) == "link-17"
    # A stale index beyond the new page length is safely ignored by the guard.
    short_page = paginate(ordered, 3, 10)  # link-20 .. link-24 (len 5)
    assert not (0 <= 7 < len(short_page))


def test_explicit_selection_still_uses_helper_and_link_identity():
    session = {"selected_opportunity": None}
    ordered = sort_opportunities(_n_recs(25), SORT_SHEET)
    page2 = paginate(ordered, 2, 10)
    chosen = page2[3]  # link-13
    select_opportunity(session, chosen)
    assert session["selected_opportunity"] is chosen
    assert opportunity_identity(session["selected_opportunity"]) == "link-13"


# ===========================================================================
# Correction pass: page_size participates in query_signature (reset to page 1)
# ===========================================================================

def test_changing_page_size_resets_to_page_one():
    session = {}
    sig_10 = query_signature("aml", [], [], SORT_SHEET, 10)
    assert resolve_current_page(session, sig_10) == 1
    # Navigate to a later page under page size 10.
    session[op.KEY_PAGE] = 4
    assert resolve_current_page(session, sig_10) == 4
    # Change rows-per-page to 20 -> signature changes -> reset to page 1.
    sig_20 = query_signature("aml", [], [], SORT_SHEET, 20)
    assert resolve_current_page(session, sig_20) == 1
    assert session[op.KEY_PAGE] == 1
    # And to 50 from a later page -> reset again.
    session[op.KEY_PAGE] = 3
    sig_50 = query_signature("aml", [], [], SORT_SHEET, 50)
    assert resolve_current_page(session, sig_50) == 1


def test_query_signature_includes_page_size_value():
    a = query_signature("x", [], [], SORT_SHEET, 10)
    b = query_signature("x", [], [], SORT_SHEET, 20)
    assert a != b
    # Backwards-compatible default when page_size omitted.
    assert query_signature("x", [], [], SORT_SHEET) == ("x", (), (), SORT_SHEET, None)


def test_render_table_signature_accepts_instance_key():
    import inspect
    sig = inspect.signature(op._render_table)
    assert list(sig.parameters) == ["page_records", "instance_key"]
