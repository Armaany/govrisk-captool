"""Streamlit presentation for the additive Evidence Search workflow."""

from __future__ import annotations

import uuid

from config import ANTHROPIC_API_KEY
from document_source import DocumentSourceError, SessionUploadDocumentSource
from evidence_brief import build_evidence_brief_docx, generate_evidence_brief
from evidence_search import build_evidence_catalogue_docx, search_evidence
from evidence_workspace import sync_workspace


REQUEST_PLACEHOLDER = (
    "Find all projects demonstrating experience in India and wider Asia, "
    "serious organised crime, fraud, narcotics, and institutional or "
    "community-facing resilience. Include all relevant projects rather than "
    "a shortlist."
)

SEARCH_UNAVAILABLE_MESSAGE = (
    "Evidence search is temporarily unavailable because the selected source "
    "could not be searched. This is an infrastructure issue, not evidence that "
    "no relevant projects exist."
)

DEFAULT_LIBRARY = "GovRisk capability library"
SESSION_UPLOADS = "Upload documents for this session"
SESSION_NOTICE = (
    "Uploaded documents are copied into an isolated, temporary workspace for this "
    "app session. They are not added to the GovRisk library and may be removed "
    "when the app restarts."
)
UPLOAD_PREPARE_FAILED = (
    "The uploaded evidence workspace could not be prepared. The existing "
    "GovRisk library and capability-statement workflow were not changed."
)
BRIEF_REVIEW_NOTICE = (
    "This is AI-assisted synthesis of the verified excerpts returned by this search. "
    "Every retained project has a checked source/chunk citation, but quote verification "
    "does not prove the interpretation or exhaustive coverage. Review it before external use."
)
UPLOAD_FAILURE_LABELS = {
    "docx_extraction_error": "Word document extraction failed",
    "pdf_extraction_error": "PDF text extraction failed",
    "read_error": "Document could not be read",
    "no_text": "No extractable text found",
    "write_error": "Search index update failed",
    "write_incomplete": "Search index update was incomplete",
}


def _safe_upload_failures(summary: dict) -> list[dict]:
    """Return filename-only, allow-listed failure detail for upload feedback."""
    details = []
    seen = set()
    records = summary.get("failed_documents", []) if isinstance(summary, dict) else []
    if not isinstance(records, (list, tuple)):
        return []
    for record in records:
        if not isinstance(record, dict):
            continue
        filename = str(record.get("filename") or "").replace("\\", "/").split("/")[-1]
        filename = filename.strip() or "Unknown document"
        reason = UPLOAD_FAILURE_LABELS.get(
            str(record.get("category") or "").strip(),
            "Indexing failed",
        )
        key = (filename, reason)
        if key not in seen:
            seen.add(key)
            details.append({"document": filename, "reason": reason})
    return details


def _initialise_state(state) -> None:
    if "evidence_search_request" not in state:
        state["evidence_search_request"] = ""
    if "evidence_search_result" not in state:
        state["evidence_search_result"] = None
    if "evidence_search_result_source" not in state:
        state["evidence_search_result_source"] = None
    if "evidence_session_token" not in state:
        state["evidence_session_token"] = uuid.uuid4().hex
    if "evidence_upload_workspace" not in state:
        state["evidence_upload_workspace"] = None
    if "evidence_brief_result" not in state:
        state["evidence_brief_result"] = None
    if "evidence_brief_fingerprint" not in state:
        state["evidence_brief_fingerprint"] = None


def _result_fingerprint(result: dict, source_key: str) -> tuple:
    """Identify the exact retrieval result used to generate a brief."""
    chunk_ids = []
    for group in result.get("groups", []) if isinstance(result, dict) else []:
        if not isinstance(group, dict):
            continue
        for packet in group.get("evidence", []) or []:
            if isinstance(packet, dict):
                chunk_id = str(packet.get("chunk_id") or "").strip()
                if chunk_id:
                    chunk_ids.append(chunk_id)
    return (source_key, str(result.get("query") or "").strip(), tuple(chunk_ids))


def _clear_brief_state(state) -> None:
    state["evidence_brief_result"] = None
    state["evidence_brief_fingerprint"] = None


def _render_structured_brief(ui, brief: dict) -> None:
    ui.subheader(str(brief.get("title") or "Structured evidence brief"))
    ui.warning(BRIEF_REVIEW_NOTICE)
    if brief.get("executive_summary"):
        ui.write(brief["executive_summary"])

    for group in brief.get("evidence_groups", []) or []:
        ui.write(str(group.get("heading") or "Evidence"))
        for project in group.get("projects", []) or []:
            label = "{} · {} · {}".format(
                project.get("project_name") or "Unnamed project",
                project.get("country_or_region") or "Not stated",
                project.get("confidence") or "LOW",
            )
            with ui.expander(label, expanded=False):
                ui.write(project.get("capability_evidence") or "No capability summary returned.")
                if project.get("themes"):
                    ui.caption("Themes: " + " · ".join(project["themes"]))
                for reported_result in project.get("reported_results", []) or []:
                    ui.write("- " + reported_result)
                if project.get("gaps"):
                    ui.info("Evidence gaps: " + "; ".join(project["gaps"]))
                ui.caption("Verified source support")
                for citation in project.get("citations", []) or []:
                    ui.write(
                        "{} — {} — chunk {}".format(
                            citation.get("source_name") or citation.get("source_id") or "Unknown source",
                            citation.get("locator_label") or "Document chunk",
                            citation.get("chunk_id") or "",
                        )
                    )
                    ui.write('"' + str(citation.get("supporting_quote") or "") + '"')

    gaps = brief.get("cross_cutting_gaps", []) or []
    if gaps:
        with ui.expander("Gaps and limitations", expanded=True):
            for gap in gaps:
                ui.write("- " + gap)

    validation = brief.get("validation", {}) or {}
    ui.caption(
        "Retained {} source-supported project(s). Removed {} unsupported project(s) "
        "and {} invalid citation(s) during deterministic validation.".format(
            validation.get("projects_retained", 0),
            validation.get("projects_removed", 0),
            validation.get("citations_removed", 0),
        )
    )
    ui.download_button(
        "Download structured evidence brief (.docx)",
        data=build_evidence_brief_docx(brief),
        file_name="structured_evidence_brief.docx",
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        key="evidence_brief_download",
    )


def _render_source_selector(ui):
    source_choice = ui.selectbox(
        "Evidence source",
        (DEFAULT_LIBRARY, SESSION_UPLOADS),
        key="evidence_source_choice",
    )
    if source_choice != SESSION_UPLOADS:
        return DEFAULT_LIBRARY, None

    ui.info(SESSION_NOTICE)
    uploads = ui.file_uploader(
        "Upload evidence documents",
        type=["pdf", "docx"],
        accept_multiple_files=True,
        key="evidence_session_uploads",
    )
    if ui.button("Prepare uploaded evidence", key="evidence_prepare_uploads"):
        try:
            source = SessionUploadDocumentSource(
                session_token=ui.session_state["evidence_session_token"],
                uploads=tuple(uploads or ()),
            )
            with ui.spinner("Preparing and indexing uploaded evidence..."):
                workspace = source.materialize()
                summary = sync_workspace(workspace)
            if summary.get("status") not in {"ready", "partial_success"}:
                ui.warning(UPLOAD_PREPARE_FAILED)
            else:
                ui.session_state["evidence_upload_workspace"] = workspace
                ui.session_state["evidence_search_result"] = None
                _clear_brief_state(ui.session_state)
                ui.success(
                    "Uploaded evidence is ready: {} source document(s), {} search chunk(s).".format(
                        summary.get("source_documents_total", 0),
                        summary.get("chunks_total", 0),
                    )
                )
                failed_total = int(summary.get("failed_documents_total", 0) or 0)
                if failed_total:
                    ui.warning(
                        f"{failed_total} uploaded document(s) could not be indexed."
                    )
                    details = _safe_upload_failures(summary)
                    if details:
                        with ui.expander("Show indexing details", expanded=False):
                            for detail in details:
                                ui.write(f"{detail['document']} — {detail['reason']}")
        except DocumentSourceError as error:
            ui.warning(str(error))
        except Exception:
            ui.warning(UPLOAD_PREPARE_FAILED)

    workspace = ui.session_state.get("evidence_upload_workspace")
    if workspace is None:
        ui.caption("Prepare the uploaded evidence before searching it.")
    else:
        ui.caption("Searching the prepared temporary upload workspace.")
    return SESSION_UPLOADS, workspace


def render_evidence_search_panel(ui) -> dict | None:
    """Render free-form Evidence Search without changing the ToR workflow."""
    _initialise_state(ui.session_state)
    searched_this_render = False

    ui.write(
        "Search the selected evidence source for source-grounded project "
        "evidence. Results are exact excerpts, not a generated bid narrative."
    )
    source_key, active_workspace = _render_source_selector(ui)

    request = ui.text_area(
        "What evidence do you need?",
        value=ui.session_state.get("evidence_search_request", ""),
        placeholder=REQUEST_PLACEHOLDER,
        height=120,
        key="evidence_search_request_input",
    )

    if ui.button("Search evidence", type="primary", key="evidence_search_submit"):
        searched_this_render = True
        ui.session_state["evidence_search_request"] = request
        _clear_brief_state(ui.session_state)
        if not str(request or "").strip():
            ui.warning("Enter an evidence request before searching.")
            ui.session_state["evidence_search_result"] = None
        else:
            if source_key == SESSION_UPLOADS and active_workspace is None:
                ui.warning("Prepare the uploaded evidence before searching it.")
                ui.session_state["evidence_search_result"] = None
            else:
                with ui.spinner("Searching the selected evidence source..."):
                    ui.session_state["evidence_search_result"] = search_evidence(
                        request,
                        workspace=active_workspace,
                    )
                ui.session_state["evidence_search_result_source"] = source_key

    result = ui.session_state.get("evidence_search_result")
    if not result or ui.session_state.get("evidence_search_result_source") != source_key:
        return None

    if result.get("library_unavailable"):
        ui.warning(SEARCH_UNAVAILABLE_MESSAGE)
        return result
    if result.get("validation_error"):
        ui.warning(result["validation_error"])
        return result

    col_a, col_b, col_c = ui.columns(3)
    col_a.metric("Source documents", result.get("documents_found", 0))
    col_b.metric("Verified excerpts", result.get("verified_evidence", 0))
    col_c.metric("Needs review", result.get("needs_review", 0))

    groups = result.get("groups", []) or []
    if not groups:
        ui.info(
            "No evidence was returned for this request. Try broader wording or "
            "confirm that the relevant documents are indexed."
        )
        return result

    ui.caption(
        "Results are grouped by source document. DOCX locations are extraction "
        "segments, not verified page numbers."
    )
    for group in groups:
        label = "{} · {} excerpt(s)".format(
            group.get("source_name", "Unknown source"),
            len(group.get("evidence", []) or []),
        )
        with ui.expander(label, expanded=False):
            for packet in group.get("evidence", []) or []:
                status = "Verified" if packet.get("verification_status") == "verified" else "Needs review"
                ui.markdown("**{} · {}**".format(status, packet.get("locator_label", "Document chunk")))
                ui.write(packet.get("quote", ""))
                ui.caption(
                    "Chunk {} · relevance {:.0%}".format(
                        packet.get("chunk_id", ""),
                        packet.get("relevance_score", 0.0),
                    )
                )

    catalogue_bytes = build_evidence_catalogue_docx(result)
    ui.download_button(
        "Download evidence catalogue (.docx)",
        data=catalogue_bytes,
        file_name="evidence_catalogue.docx",
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        key="evidence_search_download",
    )

    ui.divider()
    ui.write("Create a structured, qualified brief from the verified excerpts above.")
    ui.caption(
        "The brief presents the best-supported evidence returned by this search; "
        "it does not claim that every relevant project in the library was found."
    )
    fingerprint = _result_fingerprint(result, source_key)
    if not str(ANTHROPIC_API_KEY or "").strip():
        ui.info("Add the Anthropic API key to enable structured evidence brief generation.")
    elif not searched_this_render and ui.button(
        "Generate structured evidence brief",
        key="evidence_brief_generate",
    ):
        with ui.spinner("Organising verified evidence into a structured brief..."):
            brief = generate_evidence_brief(result, api_key=ANTHROPIC_API_KEY)
        ui.session_state["evidence_brief_result"] = brief
        ui.session_state["evidence_brief_fingerprint"] = fingerprint

    brief = ui.session_state.get("evidence_brief_result")
    if brief and ui.session_state.get("evidence_brief_fingerprint") == fingerprint:
        if brief.get("status") == "ready":
            _render_structured_brief(ui, brief)
        else:
            ui.warning(
                brief.get("message")
                or "The structured evidence brief could not be generated."
            )
    return result
