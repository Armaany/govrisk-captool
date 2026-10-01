"""Streamlit presentation for the additive Evidence Search workflow."""

from __future__ import annotations

from evidence_search import build_evidence_catalogue_docx, search_evidence


REQUEST_PLACEHOLDER = (
    "Find all projects demonstrating experience in India and wider Asia, "
    "serious organised crime, fraud, narcotics, and institutional or "
    "community-facing resilience. Include all relevant projects rather than "
    "a shortlist."
)

SEARCH_UNAVAILABLE_MESSAGE = (
    "Evidence search is temporarily unavailable because the capability library "
    "could not be searched. This is an infrastructure issue, not evidence that "
    "no relevant projects exist."
)


def _initialise_state(state) -> None:
    if "evidence_search_request" not in state:
        state["evidence_search_request"] = ""
    if "evidence_search_result" not in state:
        state["evidence_search_result"] = None


def render_evidence_search_panel(ui) -> dict | None:
    """Render free-form Evidence Search without changing the ToR workflow."""
    _initialise_state(ui.session_state)

    ui.write(
        "Search the indexed capability library for source-grounded project "
        "evidence. Results are exact excerpts, not a generated bid narrative."
    )
    request = ui.text_area(
        "What evidence do you need?",
        value=ui.session_state.get("evidence_search_request", ""),
        placeholder=REQUEST_PLACEHOLDER,
        height=120,
        key="evidence_search_request_input",
    )

    if ui.button("Search evidence", type="primary", key="evidence_search_submit"):
        ui.session_state["evidence_search_request"] = request
        if not str(request or "").strip():
            ui.warning("Enter an evidence request before searching.")
            ui.session_state["evidence_search_result"] = None
        else:
            with ui.spinner("Searching the capability library..."):
                ui.session_state["evidence_search_result"] = search_evidence(request)

    result = ui.session_state.get("evidence_search_result")
    if not result:
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
    return result

