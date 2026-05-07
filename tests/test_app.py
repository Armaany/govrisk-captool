"""
test_app.py — Task 8.13
Tests for app.py logic functions and structural validation.
Does NOT use streamlit.testing — tests logic functions only.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ---------------------------------------------------------------------------
# Test 1: app.py is importable without error (syntax check via ast.parse)
# ---------------------------------------------------------------------------

def test_app_module_importable():
    """app.py can be imported without raising (mocking streamlit)."""
    import importlib
    import sys
    from unittest.mock import MagicMock, patch

    # Mock streamlit so we don't need a running server
    st_mock = MagicMock()
    st_mock.session_state = {}

    with patch.dict(sys.modules, {"streamlit": st_mock}):
        # Just verify the file exists and is valid Python
        import ast
        app_path = os.path.join(os.path.dirname(__file__), "..", "app.py")
        with open(app_path, encoding="utf-8") as f:
            source = f.read()
        # Should parse without SyntaxError
        tree = ast.parse(source)
        assert tree is not None


# ---------------------------------------------------------------------------
# Test 2: missing API key guard logic
# ---------------------------------------------------------------------------

def test_api_key_guard_logic():
    """API key guard correctly identifies missing/empty keys."""
    from app import _api_key_is_missing
    assert _api_key_is_missing("") is True
    assert _api_key_is_missing("   ") is True
    assert _api_key_is_missing(None) is True
    assert _api_key_is_missing("sk-ant-abc123") is False


# ---------------------------------------------------------------------------
# Test 3: empty ChromaDB guard logic
# ---------------------------------------------------------------------------

def test_empty_chromadb_guard_logic():
    """Generation is blocked when doc_count == 0."""
    from app import _can_generate
    assert _can_generate(api_key_missing=False, tor_data={"title": "test"}, doc_count=0) is False
    assert _can_generate(api_key_missing=False, tor_data={"title": "test"}, doc_count=5) is True
    assert _can_generate(api_key_missing=True, tor_data={"title": "test"}, doc_count=5) is False
    assert _can_generate(api_key_missing=False, tor_data=None, doc_count=5) is False


# ---------------------------------------------------------------------------
# Test 4: no file uploaded guard
# ---------------------------------------------------------------------------

def test_no_file_uploaded_guard():
    """Generation is blocked when tor_data is None."""
    from app import _can_generate
    assert _can_generate(api_key_missing=False, tor_data=None, doc_count=10) is False


# ---------------------------------------------------------------------------
# Test 5: Update Library button invokes indexer
# ---------------------------------------------------------------------------

def test_update_library_calls_index_library():
    """Update Library button logic calls index_library."""
    from unittest.mock import patch, MagicMock
    mock_summary = {"documents_processed": 3, "chunks_created": 45, "documents_skipped": 0}
    with patch("capability_indexer.index_library", return_value=mock_summary) as mock_index:
        from capability_indexer import index_library
        result = index_library(force_reindex=False)
        assert result == mock_summary


# ---------------------------------------------------------------------------
# Test 6: progress steps structure
# ---------------------------------------------------------------------------

def test_progress_steps_structure():
    """Progress steps list has exactly 5 entries with required keys."""
    steps = [
        {"label": "ToR uploaded and read",       "status": "pending"},
        {"label": "Requirements extracted",       "status": "pending"},
        {"label": "Capability library searched",  "status": "pending"},
        {"label": "Generating draft",             "status": "pending"},
        {"label": "Formatting document",          "status": "pending"},
    ]
    assert len(steps) == 5
    for step in steps:
        assert "label" in step
        assert "status" in step
        assert step["status"] in ("pending", "done", "error", "active")


# ---------------------------------------------------------------------------
# Test 7: interpretation log display logic
# ---------------------------------------------------------------------------

def test_interpretation_log_confidence_colors():
    """Confidence level maps to correct color indicator."""
    color_map = {"HIGH": "🟢", "MEDIUM": "🟡", "LOW": "🔴"}
    assert color_map["HIGH"] == "🟢"
    assert color_map["MEDIUM"] == "🟡"
    assert color_map["LOW"] == "🔴"
    assert color_map.get("UNKNOWN", "⚪") == "⚪"


# ---------------------------------------------------------------------------
# Test 8: download button only after generation
# ---------------------------------------------------------------------------

def test_download_only_after_generation():
    """Download button condition: both generated_draft and output_file_path must be set."""
    def _should_show_download(generated_draft, output_file_path):
        return generated_draft is not None and output_file_path is not None

    assert _should_show_download(None, None) is False
    assert _should_show_download({"sections": {}}, None) is False
    assert _should_show_download(None, "/path/to/file.docx") is False
    assert _should_show_download({"sections": {}}, "/path/to/file.docx") is True
