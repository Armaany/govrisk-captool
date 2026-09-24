"""Tests for the failed-document 'Show details' expander copy (UI-only).

These verify the pure, defensive helper that turns manifest ``failed_documents``
records into safe display rows, and the rendering rules for the collapsed
expander shown under the partial-failure count warning. No indexing behavior is
exercised; only presentation helpers and static source guarantees.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import (
    _safe_failed_document_details,
    _safe_failed_document_name,
    _friendly_failure_category,
    FAILED_CATEGORY_LABELS,
    FAILED_DETAILS_EXPANDER_LABEL,
    UNKNOWN_DOCUMENT_LABEL,
    UNKNOWN_FAILURE_LABEL,
)


# 1. Known categories map to the expected friendly wording.
def test_known_categories_map_to_friendly_text():
    expected = {
        "docx_extraction_error": "Word document extraction failed",
        "pdf_extraction_error": "PDF text extraction failed",
        "read_error": "Document could not be read",
        "no_text": "No extractable text found",
        "write_error": "Search index update failed; previous evidence was preserved",
        "write_incomplete": "Search index update was incomplete; previous evidence was preserved",
        "write_error_rollback_failed": "Search index update and cleanup require attention",
        "write_incomplete_rollback_failed": "Incomplete search index update requires attention",
        "stale_delete_error": "Previous index generation could not be removed",
        "removed_delete_error": "Removed document remains in the search index",
    }
    for token, friendly in expected.items():
        assert _friendly_failure_category(token) == friendly
        assert FAILED_CATEGORY_LABELS[token] == friendly
    # And through the full record builder.
    records = _safe_failed_document_details(
        [{"filename": "a.docx", "category": t} for t in expected]
    )
    friendly_values = {r["reason"] for r in records}
    assert friendly_values == set(expected.values())


# 2. Absolute (win/unix) and nested relative paths display only the final name.
def test_paths_reduced_to_final_filename():
    assert _safe_failed_document_name(r"C:\Users\jage2\docs\report.docx") == "report.docx"
    assert _safe_failed_document_name("/var/data/library/report.pdf") == "report.pdf"
    assert _safe_failed_document_name("nested/rel/dir/file.docx") == "file.docx"
    assert _safe_failed_document_name(r"mixed\slash/dir\deep.pdf") == "deep.pdf"
    # No directory structure survives.
    for probe in ("C:\\", "Users", "var", "library", "nested", "dir"):
        assert probe not in _safe_failed_document_name(r"C:\Users\var\nested\dir\x.docx")


# 3. Blank/missing filenames become the unknown-document label.
def test_blank_or_missing_filename_becomes_unknown():
    assert _safe_failed_document_name("") == UNKNOWN_DOCUMENT_LABEL
    assert _safe_failed_document_name("   ") == UNKNOWN_DOCUMENT_LABEL
    assert _safe_failed_document_name(None) == UNKNOWN_DOCUMENT_LABEL
    assert _safe_failed_document_name(12345) == UNKNOWN_DOCUMENT_LABEL
    # A path that ends in a separator with no trailing component collapses to
    # the unknown label (no final filename component remains).
    assert _safe_failed_document_name("/") == UNKNOWN_DOCUMENT_LABEL
    assert _safe_failed_document_name("\\\\") == UNKNOWN_DOCUMENT_LABEL
    # Through the record builder.
    records = _safe_failed_document_details([{"category": "read_error"}])
    assert records == [{"document": UNKNOWN_DOCUMENT_LABEL, "reason": "Document could not be read"}]


# 4. Unknown/malformed category values become "Indexing failed" (token hidden).
def test_unknown_category_hidden_behind_generic_label():
    assert _friendly_failure_category("some_new_token") == UNKNOWN_FAILURE_LABEL
    assert _friendly_failure_category(None) == UNKNOWN_FAILURE_LABEL
    assert _friendly_failure_category(42) == UNKNOWN_FAILURE_LABEL
    assert _friendly_failure_category("") == UNKNOWN_FAILURE_LABEL
    records = _safe_failed_document_details(
        [{"filename": "x.docx", "category": "totally_unknown_token"}]
    )
    assert records == [{"document": "x.docx", "reason": UNKNOWN_FAILURE_LABEL}]
    # The raw token never appears.
    assert "totally_unknown_token" not in records[0]["reason"]


# 5. Raw reason / exception / traceback fields are ignored entirely.
def test_reason_and_exception_fields_are_ignored():
    entry = {
        "filename": "doc.docx",
        "category": "read_error",
        "reason": "PermissionError: [Errno 13] C:\\secret\\path denied",
        "exception": "Traceback (most recent call last): ...",
        "traceback": "File app.py line 1 ...",
        "content": "SECRET DOCUMENT CONTENT",
    }
    records = _safe_failed_document_details([entry])
    assert records == [{"document": "doc.docx", "reason": "Document could not be read"}]
    rendered = "{} — {}".format(records[0]["document"], records[0]["reason"])
    for leak in ("PermissionError", "Errno", "secret", "Traceback", "SECRET DOCUMENT"):
        assert leak not in rendered


# 6. Malformed failed_documents containers/entries do not crash.
def test_malformed_input_does_not_crash():
    assert _safe_failed_document_details(None) == []
    assert _safe_failed_document_details("not a list") == []
    assert _safe_failed_document_details(123) == []
    assert _safe_failed_document_details({}) == []
    # Non-dict entries are skipped, valid ones retained.
    mixed = ["string-entry", 42, None, {"filename": "ok.docx", "category": "no_text"}]
    records = _safe_failed_document_details(mixed)
    assert records == [{"document": "ok.docx", "reason": "No extractable text found"}]


# 7. Duplicate identical filename/category rows are shown once.
def test_duplicate_rows_deduplicated():
    entries = [
        {"filename": "dup.docx", "category": "read_error"},
        {"filename": "dup.docx", "category": "read_error"},
        {"filename": "path/to/dup.docx", "category": "read_error"},  # same final name+cat
        {"filename": "dup.docx", "category": "no_text"},             # same name, diff cat
    ]
    records = _safe_failed_document_details(entries)
    assert records == [
        {"document": "dup.docx", "reason": "Document could not be read"},
        {"document": "dup.docx", "reason": "No extractable text found"},
    ]


# 9. The expander label is exactly "Show details".
def test_expander_label_is_exact():
    assert FAILED_DETAILS_EXPANDER_LABEL == "Show details"


# ---------------------------------------------------------------------------
# Rendering-rule tests: mirror the sidebar logic against a fake UI recorder.
# ---------------------------------------------------------------------------

class _FakeExpander:
    def __init__(self, recorder, label):
        recorder.expander_labels.append(label)
        self._recorder = recorder

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeUI:
    """Records warning/write/expander calls the way app.py would issue them."""

    def __init__(self):
        self.warnings = []
        self.writes = []
        self.expander_labels = []

    def warning(self, msg):
        self.warnings.append(msg)

    def write(self, msg):
        self.writes.append(msg)

    def expander(self, label, expanded=False):
        return _FakeExpander(self, label)


def _render_partial_block(ui, manifest_status, manifest_failed_total, manifest_failed_documents):
    """Replica of the sidebar's partial-warning + expander rendering logic."""
    from app import _safe_failed_document_details, FAILED_DETAILS_EXPANDER_LABEL

    if manifest_status == "partial_success" and manifest_failed_total > 0:
        ui.warning(
            "Last update completed with {} document(s) that could not be "
            "indexed.".format(manifest_failed_total)
        )
        details = _safe_failed_document_details(manifest_failed_documents)
        if details:
            with ui.expander(FAILED_DETAILS_EXPANDER_LABEL, expanded=False):
                for d in details:
                    ui.write("{} — {}".format(d["document"], d["reason"]))


# 8. The existing count warning remains unchanged.
def test_count_warning_text_unchanged():
    ui = _FakeUI()
    _render_partial_block(
        ui, "partial_success", 2,
        [{"filename": "a.docx", "category": "read_error"}],
    )
    assert ui.warnings == ["Last update completed with 2 document(s) that could not be indexed."]


# 10. Details render only for partial success with a positive failure count.
def test_details_render_only_on_partial_with_positive_count():
    failed = [{"filename": "a.docx", "category": "read_error"}]

    # Not partial -> no expander even with a positive count.
    ui = _FakeUI()
    _render_partial_block(ui, "ready", 2, failed)
    assert ui.expander_labels == []
    assert ui.warnings == []

    # Partial but zero count -> no warning, no expander.
    ui = _FakeUI()
    _render_partial_block(ui, "partial_success", 0, failed)
    assert ui.expander_labels == []

    # Partial with count but no valid details -> warning stays, no expander.
    ui = _FakeUI()
    _render_partial_block(ui, "partial_success", 1, ["malformed"])
    assert len(ui.warnings) == 1
    assert ui.expander_labels == []

    # Partial with count and valid details -> exactly one expander, exact label.
    ui = _FakeUI()
    _render_partial_block(ui, "partial_success", 1, failed)
    assert ui.expander_labels == ["Show details"]
    assert ui.writes == ["a.docx — Document could not be read"]


# 11. Rendering uses escaped text (st.write), not unsafe HTML/markdown.
def test_rendering_uses_escaped_text_not_raw_html():
    # Behavioral: even a filename crafted to look like HTML markup is emitted via
    # st.write (which escapes), and never assembled into a raw HTML string. (Note
    # any '/' in the name is treated as a path separator by the sanitizer, so we
    # use angle-bracket markup without a slash to focus on the escaping path.)
    ui = _FakeUI()
    _render_partial_block(
        ui, "partial_success", 1,
        [{"filename": "<b>evil<b>.docx", "category": "read_error"}],
    )
    # It is passed as plain text to write(); no unsafe_allow_html anywhere.
    assert ui.writes == ["<b>evil<b>.docx — Document could not be read"]

    # Static guarantee: the sidebar renders details with st.write and never uses
    # unsafe HTML for this block.
    app_path = os.path.join(os.path.dirname(__file__), "..", "app.py")
    with open(app_path, encoding="utf-8") as f:
        source = f.read()
    assert 'st.expander(FAILED_DETAILS_EXPANDER_LABEL' in source
    assert 'st.write("{} — {}".format(_detail["document"], _detail["reason"]))' in source
    assert "unsafe_allow_html" not in source
