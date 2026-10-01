from unittest.mock import MagicMock

import evidence_search_panel
from evidence_search_panel import SEARCH_UNAVAILABLE_MESSAGE, render_evidence_search_panel


def _ui(request="India fraud", submit=True):
    ui = MagicMock()
    ui.session_state = {}
    ui.text_area.return_value = request
    ui.button.return_value = submit
    ui.columns.return_value = (MagicMock(), MagicMock(), MagicMock())
    return ui


def test_panel_surfaces_infrastructure_failure_without_raw_exception(monkeypatch):
    ui = _ui()
    secret_error = "Bearer SENTINEL_SECRET"
    monkeypatch.setattr(
        evidence_search_panel,
        "search_evidence",
        lambda request: {
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
    monkeypatch.setattr(evidence_search_panel, "search_evidence", lambda request: result)
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

