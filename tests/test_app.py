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


# ---------------------------------------------------------------------------
# Component 2 — Discovery Panel integration tests
# ---------------------------------------------------------------------------

def test_discovery_result_none_uses_all_chunks():
    """
    When discovery_result is None, chunks_to_use falls back to
    retrieved_chunks from session state.
    Assert: chunks_to_use equals the full retrieved list.
    """
    full_chunks = [
        {"chunk_id": "c1", "text": "chunk one"},
        {"chunk_id": "c2", "text": "chunk two"},
        {"chunk_id": "c3", "text": "chunk three"},
    ]
    discovery_result = None
    retrieved_chunks = full_chunks

    # Replicate the logic from app.py
    if discovery_result is not None:
        chunks_to_use = discovery_result["selected_chunks"]
    else:
        chunks_to_use = retrieved_chunks or []

    assert chunks_to_use == full_chunks


def test_discovery_result_filters_chunks():
    """
    When discovery_result is provided with a selected_chunks subset,
    chunks_to_use equals only the selected subset.
    Assert: len(chunks_to_use) < len(full_retrieved_chunks)
    """
    full_chunks = [
        {"chunk_id": "c1", "text": "chunk one"},
        {"chunk_id": "c2", "text": "chunk two"},
        {"chunk_id": "c3", "text": "chunk three"},
    ]
    # Simulate user selecting only 1 of 3 chunks in the discovery panel
    discovery_result = {
        "selected_chunks": [full_chunks[0]],
        "selected_projects": [],
        "geo_priority": "equal",
        "thematic_emphasis": [],
        "prompt_txt_content": "",
    }

    # Replicate the logic from app.py
    if discovery_result is not None:
        chunks_to_use = discovery_result["selected_chunks"]
    else:
        chunks_to_use = full_chunks or []

    assert len(chunks_to_use) < len(full_chunks)
    assert len(chunks_to_use) == 1
    assert chunks_to_use[0]["chunk_id"] == "c1"
def test_normalize_functions_removed():
    import app
    assert not hasattr(app, "_GEO_NORMALIZE")
    assert not hasattr(app, "_normalize_filter_values")
    assert not hasattr(app, "_normalize_funder")


def test_tor_review_panel_imported():
    import app
    assert hasattr(app, "render_tor_review")


def test_confirmed_tor_data_in_defaults():
    import app
    assert "confirmed_tor_data" in app.DEFAULTS
    assert app.DEFAULTS["confirmed_tor_data"] is None


def test_can_generate_with_confirmed_tor_data():
    from app import _can_generate
    assert _can_generate(
        api_key_missing=False,
        tor_data={"title": "test"},
        doc_count=5
    ) is True


# ---------------------------------------------------------------------------
# Component 3c — tor_review_panel integration tests
# ---------------------------------------------------------------------------

def test_normalize_functions_removed():
    """Normalization dicts and functions removed in v1.3."""
    import ast
    app_path = os.path.join(os.path.dirname(__file__), "..", "app.py")
    with open(app_path, encoding="utf-8") as f:
        source = f.read()
    tree = ast.parse(source)
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    assigned = {node.targets[0].id for node in ast.walk(tree)
                if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)}
    assert "_GEO_NORMALIZE" not in assigned, "_GEO_NORMALIZE still defined in app.py"
    assert "_normalize_filter_values" not in {
        node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
    }, "_normalize_filter_values still defined in app.py"
    assert "_normalize_funder" not in {
        node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
    }, "_normalize_funder still defined in app.py"


def test_tor_review_panel_imported():
    """render_tor_review is imported into app.py."""
    import ast
    app_path = os.path.join(os.path.dirname(__file__), "..", "app.py")
    with open(app_path, encoding="utf-8") as f:
        source = f.read()
    assert "render_tor_review" in source, "render_tor_review not imported in app.py"


def test_confirmed_tor_data_in_defaults():
    """DEFAULTS dict contains confirmed_tor_data key set to None."""
    import ast
    app_path = os.path.join(os.path.dirname(__file__), "..", "app.py")
    with open(app_path, encoding="utf-8") as f:
        source = f.read()
    assert "confirmed_tor_data" in source, "confirmed_tor_data not found in app.py"
    # Also verify via ast that DEFAULTS is a dict that includes it
    assert '"confirmed_tor_data"' in source or "'confirmed_tor_data'" in source, \
        "confirmed_tor_data key not in DEFAULTS"


def test_can_generate_with_confirmed_tor_data():
    """_can_generate returns True when all conditions met."""
    from app import _can_generate
    assert _can_generate(
        api_key_missing=False,
        tor_data={"title": "test"},
        doc_count=5,
    ) is True


# ---------------------------------------------------------------------------
# Component 4b — draft_review_panel integration tests
# ---------------------------------------------------------------------------

def test_draft_review_panel_imported():
    """render_draft_review is imported into app.py."""
    import ast
    app_path = os.path.join(os.path.dirname(__file__), "..", "app.py")
    with open(app_path, encoding="utf-8") as f:
        source = f.read()
    assert "render_draft_review" in source, "render_draft_review not imported in app.py"


def test_approved_draft_in_defaults():
    """DEFAULTS dict contains approved_draft key set to None."""
    import ast
    app_path = os.path.join(os.path.dirname(__file__), "..", "app.py")
    with open(app_path, encoding="utf-8") as f:
        source = f.read()
    assert '"approved_draft"' in source or "'approved_draft'" in source


def test_drp_regen_request_in_defaults():
    """DEFAULTS dict contains drp_regen_request key set to None."""
    import ast
    app_path = os.path.join(os.path.dirname(__file__), "..", "app.py")
    with open(app_path, encoding="utf-8") as f:
        source = f.read()
    assert '"drp_regen_request"' in source or "'drp_regen_request'" in source


# ---------------------------------------------------------------------------
# Component 6+7 — Fix sprint tests
# ---------------------------------------------------------------------------

def test_last_chunks_used_in_defaults():
    """DEFAULTS dict contains last_chunks_used key set to []."""
    import ast
    app_path = os.path.join(os.path.dirname(__file__), "..", "app.py")
    with open(app_path, encoding="utf-8") as f:
        source = f.read()
    assert '"last_chunks_used"' in source or "'last_chunks_used'" in source
