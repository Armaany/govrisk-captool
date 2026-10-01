from unittest.mock import MagicMock

import evidence_search_panel
from evidence_search_panel import (
    BRIEF_REVIEW_NOTICE,
    DEFAULT_LIBRARY,
    SEARCH_UNAVAILABLE_MESSAGE,
    SESSION_UPLOADS,
    _safe_upload_failures,
    render_evidence_search_panel,
)


def _ui(request="India fraud", submit=True):
    ui = MagicMock()
    ui.session_state = {}
    ui.text_area.return_value = request
    ui.button.return_value = submit
    ui.selectbox.return_value = DEFAULT_LIBRARY
    ui.file_uploader.return_value = []
    ui.columns.return_value = (MagicMock(), MagicMock(), MagicMock())
    return ui


def test_panel_surfaces_infrastructure_failure_without_raw_exception(monkeypatch):
    ui = _ui()
    secret_error = "Bearer SENTINEL_SECRET"
    monkeypatch.setattr(
        evidence_search_panel,
        "search_evidence",
        lambda request, workspace=None: {
            "query": request,
            "library_unavailable": True,
            "library_error": secret_error,
        },
    )

    result = render_evidence_search_panel(ui)

    assert result["library_unavailable"] is True
    ui.warning.assert_called_once_with(SEARCH_UNAVAILABLE_MESSAGE)
    rendered = " ".join(str(call) for call in ui.method_calls)
    assert "SENTINEL_SECRET" not in rendered
    ui.download_button.assert_not_called()


def test_panel_renders_verified_results_and_download(monkeypatch):
    ui = _ui()
    result = {
        "query": "India fraud",
        "library_unavailable": False,
        "documents_found": 1,
        "verified_evidence": 1,
        "needs_review": 0,
        "groups": [
            {
                "source_name": "India.docx",
                "source_file": "India.docx",
                "evidence": [
                    {
                        "verification_status": "verified",
                        "locator_label": "DOCX extraction segment 1 (not a verified page)",
                        "quote": "Exact source evidence.",
                        "chunk_id": "chunk-1",
                        "relevance_score": 0.8,
                    }
                ],
            }
        ],
    }
    monkeypatch.setattr(
        evidence_search_panel, "search_evidence", lambda request, workspace=None: result
    )
    monkeypatch.setattr(evidence_search_panel, "build_evidence_catalogue_docx", lambda value: b"PKdocx")

    returned = render_evidence_search_panel(ui)

    assert returned is result
    ui.download_button.assert_called_once()
    kwargs = ui.download_button.call_args.kwargs
    assert kwargs["data"] == b"PKdocx"
    assert kwargs["file_name"] == "evidence_catalogue.docx"
    assert kwargs["mime"].endswith("wordprocessingml.document")


def test_panel_does_not_search_blank_request(monkeypatch):
    ui = _ui(request="   ")
    called = False

    def fake_search(_request):
        nonlocal called
        called = True

    monkeypatch.setattr(evidence_search_panel, "search_evidence", fake_search)
    assert render_evidence_search_panel(ui) is None
    assert called is False
    ui.warning.assert_called_once_with("Enter an evidence request before searching.")


def test_upload_source_requires_preparation_before_search(monkeypatch):
    ui = _ui()
    ui.selectbox.return_value = SESSION_UPLOADS
    # First button is Prepare, second is Search.
    ui.button.side_effect = [False, True]
    called = False

    def fake_search(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(evidence_search_panel, "search_evidence", fake_search)
    assert render_evidence_search_panel(ui) is None
    assert called is False
    assert any(
        "Prepare the uploaded evidence" in str(call)
        for call in ui.warning.call_args_list
    )


def test_prepared_upload_workspace_is_forwarded_to_search(monkeypatch):
    ui = _ui()
    ui.selectbox.return_value = SESSION_UPLOADS
    ui.button.side_effect = [False, True]
    workspace = object()
    ui.session_state["evidence_upload_workspace"] = workspace
    captured = {}

    def fake_search(request, workspace=None):
        captured.update(request=request, workspace=workspace)
        return {"library_unavailable": False, "groups": []}

    monkeypatch.setattr(evidence_search_panel, "search_evidence", fake_search)
    render_evidence_search_panel(ui)
    assert captured == {"request": "India fraud", "workspace": workspace}


def test_upload_failure_details_ignore_raw_paths_and_exception_text():
    details = _safe_upload_failures(
        {
            "failed_documents": [
                {
                    "filename": r"C:\private\Client Report.docx",
                    "category": "docx_extraction_error",
                    "reason": "Bearer SENTINEL_SECRET",
                    "traceback": "SENTINEL_TRACEBACK",
                },
                {
                    "filename": "/private/Unknown.pdf",
                    "category": "raw_internal_category",
                },
            ]
        }
    )
    assert details == [
        {
            "document": "Client Report.docx",
            "reason": "Word document extraction failed",
        },
        {"document": "Unknown.pdf", "reason": "Indexing failed"},
    ]
    rendered = str(details)
    assert "private" not in rendered
    assert "SENTINEL" not in rendered
    assert "raw_internal_category" not in rendered


def test_panel_generates_and_downloads_validated_brief_on_separate_click(monkeypatch):
    ui = _ui(submit=False)
    result = {
        "query": "India fraud",
        "library_unavailable": False,
        "documents_found": 1,
        "verified_evidence": 1,
        "needs_review": 0,
        "groups": [
            {
                "source_name": "India.docx",
                "evidence": [
                    {
                        "verification_status": "verified",
                        "chunk_id": "chunk-1",
                        "quote": "Verified quote.",
                    }
                ],
            }
        ],
    }
    brief = {
        "status": "ready",
        "title": "Structured brief",
        "executive_summary": "One supported project.",
        "evidence_groups": [],
        "cross_cutting_gaps": [],
        "validation": {
            "projects_retained": 1,
            "projects_removed": 0,
            "citations_removed": 0,
        },
    }
    ui.session_state.update(
        {
            "evidence_search_result": result,
            "evidence_search_result_source": DEFAULT_LIBRARY,
        }
    )
    # Search is not clicked; Generate brief is clicked.
    ui.button.side_effect = [False, True]
    monkeypatch.setattr(evidence_search_panel, "ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(evidence_search_panel, "generate_evidence_brief", lambda *a, **k: brief)
    monkeypatch.setattr(evidence_search_panel, "build_evidence_catalogue_docx", lambda value: b"PKcatalogue")
    monkeypatch.setattr(evidence_search_panel, "build_evidence_brief_docx", lambda value: b"PKbrief")

    returned = render_evidence_search_panel(ui)

    assert returned is result
    assert ui.session_state["evidence_brief_result"] is brief
    downloads = [call.kwargs for call in ui.download_button.call_args_list]
    assert [item["file_name"] for item in downloads] == [
        "evidence_catalogue.docx",
        "structured_evidence_brief.docx",
    ]
    rendered = " ".join(str(call) for call in ui.method_calls)
    assert BRIEF_REVIEW_NOTICE in rendered


def test_panel_hides_raw_generation_error(monkeypatch):
    ui = _ui(submit=False)
    result = {
        "query": "India fraud",
        "library_unavailable": False,
        "documents_found": 1,
        "verified_evidence": 1,
        "needs_review": 0,
        "groups": [{"source_name": "India.docx", "evidence": [{"chunk_id": "c1"}]}],
    }
    ui.session_state.update(
        {
            "evidence_search_result": result,
            "evidence_search_result_source": DEFAULT_LIBRARY,
        }
    )
    ui.button.side_effect = [False, True]
    monkeypatch.setattr(evidence_search_panel, "ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(
        evidence_search_panel,
        "generate_evidence_brief",
        lambda *a, **k: {
            "status": "error",
            "message": "The structured evidence brief could not be generated.",
        },
    )
    monkeypatch.setattr(evidence_search_panel, "build_evidence_catalogue_docx", lambda value: b"PKcatalogue")

    render_evidence_search_panel(ui)

    rendered = " ".join(str(call) for call in ui.method_calls)
    assert "SENTINEL_SECRET" not in rendered
    assert "could not be generated" in rendered
