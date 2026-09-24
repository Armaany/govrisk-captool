"""
app.py — Task 8
Single-page Streamlit application for the GovRisk Capability Statement Generator.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import streamlit as st

LIBRARY_UNAVAILABLE_MESSAGE = (
    "Capability-library search is temporarily unavailable. "
    "Generation is paused until the library connection is restored."
)

# Approved exact wording for the temporary/recovery index warning. The process
# keeps a resolved-directory cache, so clicking "Update Library" does not
# necessarily migrate back to configured storage during this process; the
# wording must not promise that it will.
RECOVERY_WARNING_MESSAGE = (
    "Using a temporary search index. "
    "It may need to be rebuilt when the app restarts."
)

MISSING_LIBRARY_MESSAGE = (
    "Capability source library is missing or unreadable. "
    "The existing search index has been preserved; document generation is "
    "paused until the library is restored."
)

# Shown when the source library is missing/empty but a non-empty index remains.
# Generation continues on the preserved index, so the copy must NOT claim
# generation is paused; it only warns that updates are unavailable and the
# index may be stale (blocker 7).
STALE_INDEX_MESSAGE = (
    "Source library is unavailable, so library updates are paused and the "
    "search index may be stale. Document generation continues using the "
    "existing index."
)

# ---------------------------------------------------------------------------
# Module-level helper functions (used by tests)
# ---------------------------------------------------------------------------

def _api_key_is_missing(key):
    """Return True if the API key is missing or empty."""
    return not key or key.strip() == ""


def _can_generate(
    api_key_missing,
    tor_data,
    doc_count,
    retrieval_unavailable=False,
):
    """Return True only when all preconditions for generation are met."""
    if api_key_missing:
        return False
    if tor_data is None:
        return False
    if doc_count == 0:
        return False
    if retrieval_unavailable:
        return False
    return True


def _index_created_content(summary):
    """Return True only when an indexing attempt created usable chunks."""
    if not isinstance(summary, dict):
        return False
    try:
        return int(summary.get("chunks_created", 0)) > 0
    except (TypeError, ValueError):
        return False


# Supported source-document extensions for counting present source files. Kept
# in sync with the indexer's SUPPORTED_EXTENSIONS.
SOURCE_DOC_EXTENSIONS = (".docx", ".pdf")


def _count_source_documents(library_path):
    """Return the number of supported source documents present, or None.

    None means the library directory is missing or unreadable — which the UI
    must distinguish from a genuinely empty library (zero supported files).
    """
    import os as _os
    try:
        entries = _os.listdir(library_path)
    except OSError:
        return None
    count = 0
    for name in entries:
        full = _os.path.join(library_path, name)
        if not _os.path.isfile(full):
            continue
        if _os.path.splitext(name)[1].lower() in SOURCE_DOC_EXTENSIONS:
            count += 1
    return count


def _should_auto_index(chunk_count, source_document_count, already_attempted):
    """Decide whether an automatic index run is safe to start.

    Auto-index only when ALL hold:
      * the searchable index is genuinely empty (chunk_count == 0),
      * the library directory is readable (source_document_count is not None),
      * at least one supported source document exists, and
      * this process/session has not already attempted and failed auto-indexing.

    This prevents an endless Streamlit rerun loop when the library is missing or
    empty, or after a prior failed attempt.
    """
    if already_attempted:
        return False
    if chunk_count is None or chunk_count > 0:
        return False
    if source_document_count is None:
        return False
    if source_document_count < 1:
        return False
    return True


def _derive_library_state(chunk_count, source_document_count, status, is_temporary):
    """Map raw signals to a single user-visible library state string.

    Returns one of:
      "index_unavailable", "empty_index", "missing_library", "indexing",
      "partial", "recovery", "ready".

    Precedence favors the most actionable/honest state. Crucially, an
    unavailable or empty *index* outranks a missing/empty *source library*: if
    the index itself has no usable evidence, generation must be blocked
    regardless of whether the source folder is present. But when the index is
    non-empty and only the source library is missing/empty, the state is
    ``missing_library`` — updates are unavailable and the index may be stale,
    yet generation can still proceed on the preserved index (blocker 7).
    """
    if status == "indexing_in_progress":
        return "indexing"
    if status == "index_unavailable" or chunk_count is None:
        return "index_unavailable"
    if chunk_count == 0:
        # No usable evidence in the index — this outranks source availability.
        return "empty_index"
    if status in ("library_unavailable", "source_library_empty") or source_document_count in (None, 0):
        # Non-empty index but the source library is missing/empty.
        return "missing_library"
    if status == "partial_success":
        return "partial"
    if is_temporary:
        return "recovery"
    return "ready"


def _document_generation_enabled(library_state, chunk_count):
    """Return True when document generation may proceed.

    Generation depends on searchable evidence (a non-empty index), NOT on the
    presence of the source library. It is disabled only when the index is empty,
    unavailable, or a sync is in progress. A missing/empty source library with a
    preserved non-empty index still allows generation (the index may be stale,
    which the UI warns about separately). An infrastructure failure is never
    surfaced downstream as "no relevant evidence found".
    """
    if library_state in ("index_unavailable", "empty_index", "indexing"):
        return False
    return bool(chunk_count and chunk_count > 0)


def _show_library_unavailable_warning(ui, unavailable):
    """Show the infrastructure warning only when library search failed."""
    if not unavailable:
        return False
    ui.warning(LIBRARY_UNAVAILABLE_MESSAGE)
    return True


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------

from config import GEOGRAPHY_OPTIONS, THEMATIC_OPTIONS, FUNDER_OPTIONS
from discovery_panel import render_discovery_panel
from tor_review_panel import render_tor_review
from draft_review_panel import render_draft_review
from opportunity_panel import render_opportunity_panel

# ---------------------------------------------------------------------------
# Session state initialisation (8.2)
# ---------------------------------------------------------------------------

DEFAULTS = {
    "tor_data": None,
    "confirmed_tor_data": None,
    "retrieved_chunks": None,
    "retrieval_unavailable": False,
    "generated_draft": None,
    "approved_draft": None,
    "output_file_path": None,
    "condensed_file_path": None,
    "discovery_result": None,
    "drp_regen_request": None,
    "drp_trigger_generate": False,
    "last_chunks_used": [],
    "selected_opportunity": None,
    "filters": {"geography": [], "thematic_areas": [], "funder": []},
    "sections": None,   # None = all sections
    "progress_steps": [
        {"label": "ToR uploaded and read",       "status": "pending"},
        {"label": "Requirements extracted",       "status": "pending"},
        {"label": "Capability library searched",  "status": "pending"},
        {"label": "Generating draft",             "status": "pending"},
        {"label": "Formatting document",          "status": "pending"},
        {"label": "Generating condensed version", "status": "pending"},
    ],
}
for key, default in DEFAULTS.items():
    if key not in st.session_state:
        st.session_state[key] = default

# ---------------------------------------------------------------------------
# Config imports
# ---------------------------------------------------------------------------

from config import ANTHROPIC_API_KEY, CAPABILITY_LIBRARY_PATH, OUTPUT_PATH, MODEL_NAME

# ---------------------------------------------------------------------------
# API key guard (8.3)
# ---------------------------------------------------------------------------

api_key_missing = _api_key_is_missing(ANTHROPIC_API_KEY)
if api_key_missing:
    st.error(
        "⚠️ ANTHROPIC_API_KEY is not set. "
        "Please add it to your .env file and restart the app."
    )

# ---------------------------------------------------------------------------
# Sidebar (8.3 / 8.4)
# ---------------------------------------------------------------------------

with st.sidebar:
    st.header("Library Status")

    from config import CHROMA_DB_PATH

    # --- Read-only signals. app.py is presentation-only and never writes the
    # index or the manifest; the indexer owns all index state. ---

    # Chunk count (search chunks) via the defensive shared factory. This is the
    # number of stored chunks, NOT a document count.
    chunk_count = None
    try:
        from chroma_client import get_collection
        collection = get_collection(CHROMA_DB_PATH)
        chunk_count = collection.count()
    except Exception as e:
        chunk_count = None
        _index_error_name = type(e).__name__

    # Storage mode (configured vs temporary recovery).
    is_temporary = False
    try:
        from chroma_client import get_persist_status
        _persist_status = get_persist_status(CHROMA_DB_PATH)
        is_temporary = _persist_status.is_temporary
    except Exception:
        _persist_status = None

    # Present source documents (supported files currently on disk). None means
    # the library directory is missing/unreadable.
    source_document_count = _count_source_documents(os.path.abspath(CAPABILITY_LIBRARY_PATH))

    # Read the manifest that sits BESIDE the active index. We only READ it here:
    # indexed-document count, last successful timestamp, the recorded run status,
    # and the failed-document count so the UI reflects what actually happened.
    indexed_document_count = None
    last_indexed_display = "Never"
    manifest_status = None
    manifest_failed_total = 0
    try:
        import json
        from chroma_client import manifest_path as _manifest_path
        _mpath = _manifest_path(CHROMA_DB_PATH)
        if os.path.exists(_mpath):
            with open(_mpath, encoding="utf-8") as f:
                manifest = json.load(f)
            indexed_document_count = manifest.get("indexed_documents_total")
            last_indexed_display = manifest.get("last_successful_index_at") or "Unknown"
            manifest_status = manifest.get("status")
            manifest_failed_total = manifest.get("failed_documents_total", 0) or 0
    except Exception:
        last_indexed_display = "Unknown"

    # --- Safe auto-index: only when genuinely empty, library readable, at least
    # one source doc, and not already attempted this session. Never loops. ---
    if _should_auto_index(
        chunk_count,
        source_document_count,
        st.session_state.get("auto_index_attempted", False),
    ):
        st.session_state["auto_index_attempted"] = True
        try:
            from capability_indexer import index_library
            with st.spinner("Building library index for first run..."):
                auto_index_summary = index_library(force_reindex=False)
            if _index_created_content(auto_index_summary):
                st.rerun()
        except Exception as e:
            st.warning(f"Auto-index failed: {type(e).__name__}")

    # --- Three honest counts. Never label a chunk count as a document count. ---
    col_a, col_b, col_c = st.columns(3)
    with col_a:
        st.metric(
            "Source documents",
            source_document_count if source_document_count is not None else "—",
        )
    with col_b:
        st.metric(
            "Indexed documents",
            indexed_document_count if indexed_document_count is not None else "—",
        )
    with col_c:
        # collection.count() is ONLY ever displayed as chunks.
        st.metric("Search chunks", chunk_count if chunk_count is not None else "—")

    # --- User-visible state. ---
    library_state = _derive_library_state(
        chunk_count, source_document_count, manifest_status, is_temporary
    )
    if library_state == "index_unavailable":
        st.error("Search index is unavailable. Document generation is disabled.")
    elif library_state == "empty_index":
        st.warning(
            "Search index is empty. Document generation is disabled until the "
            "library is indexed."
        )
    elif library_state == "missing_library":
        # Source library is missing/empty but a non-empty index remains: updates
        # are unavailable and the index may be stale, but generation continues on
        # the preserved index (blocker 7 — copy must match actual behavior).
        st.warning(STALE_INDEX_MESSAGE)
    elif library_state == "recovery":
        # Approved exact wording; no filesystem paths exposed.
        st.warning(RECOVERY_WARNING_MESSAGE)

    # Partial-success signal read from the manifest (blocker 6): show a concise
    # count of failed documents without raw exception text or filesystem paths.
    if manifest_status == "partial_success" and manifest_failed_total > 0:
        st.warning(
            "Last update completed with {} document(s) that could not be "
            "indexed.".format(manifest_failed_total)
        )

    st.caption(f"Last indexed: {last_indexed_display}")

    # --- Manual incremental synchronization. Presentation only: it calls the
    # indexer (which owns the manifest) and renders the structured summary. ---
    if st.button("🔄 Update Library"):
        with st.spinner("Synchronizing capability library..."):
            try:
                from capability_indexer import index_library
                summary = index_library(force_reindex=False)
                status = summary.get("status")
                if status == "indexing_in_progress":
                    st.info("Indexing is already in progress. Please wait for it to finish.")
                elif status in ("library_unavailable", "index_unavailable"):
                    st.error(
                        "Update could not run: {}".format(
                            summary.get("error") or "index or library unavailable"
                        )
                    )
                elif status == "source_library_empty":
                    st.warning(
                        "No source documents are present. The existing search "
                        "index was preserved and left unchanged."
                    )
                elif status == "manifest_write_failed":
                    # Indexing may have changed Chroma but status could not be
                    # published; surface an explicit infrastructure error rather
                    # than reporting a normal success.
                    st.error(
                        "Indexing ran but the index status could not be saved. "
                        "Please retry; the reported status may be stale."
                    )
                else:
                    msg = (
                        "Indexed {indexed} of {source} source documents · "
                        "{chunks} search chunks. "
                        "Processed: {processed} · Unchanged: {unchanged} · "
                        "Removed: {removed} · Failed: {failed}."
                    ).format(
                        indexed=summary.get("indexed_documents_total", 0),
                        source=summary.get("source_documents_total", 0),
                        chunks=summary.get("chunks_total", 0),
                        processed=summary.get("documents_processed", 0),
                        unchanged=summary.get("documents_unchanged", 0),
                        removed=summary.get("documents_removed", 0),
                        failed=summary.get("documents_failed", 0),
                    )
                    if status == "partial_success":
                        st.warning(msg)
                    else:
                        st.success(msg)
                    st.session_state.retrieved_chunks = None
                    st.session_state.retrieval_unavailable = False
                    st.rerun()
            except Exception as e:
                st.error(f"Failed to update library: {type(e).__name__}")

    st.divider()
    st.caption(f"Output: {OUTPUT_PATH}")
    st.caption(f"Model: {MODEL_NAME}")

    st.markdown("---")
    st.markdown("**🔍 Opportunity Monitor**")
    st.link_button(
        "View latest opportunities ↗",
        "https://docs.google.com/spreadsheets/d/1vXqBDRHiHdyf8U4O_ZuIR5nOLQa-jgEphjuRCoctx14",
    )
    st.caption("Updated daily · UNDP · World Bank · Grants.gov")

    

# ---------------------------------------------------------------------------
# Main content area
# ---------------------------------------------------------------------------

st.title("GovRisk Capability Statement Generator")
st.markdown("Generate professional capability statements from your ToR and capability library.")

with st.expander("Find an opportunity", expanded=True):
    selected_opportunity = render_opportunity_panel()

# ---------------------------------------------------------------------------
# STEP 1 — Upload ToR (8.5)
# ---------------------------------------------------------------------------

st.subheader("Step 1: Upload Terms of Reference")
uploaded_file = st.file_uploader(
    "Upload a ToR document (.docx or .pdf)",
    type=["docx", "pdf"],
    key="tor_uploader",
)

if uploaded_file is not None:
    # Only re-extract if a new file is uploaded
    if (st.session_state.tor_data is None or
            st.session_state.tor_data.get("source_file") != uploaded_file.name):
        with st.spinner("Extracting requirements from ToR..."):
            try:
                from tor_extractor import extract_tor
                file_bytes = uploaded_file.read()
                tor_data = extract_tor(file_bytes, uploaded_file.name)
                st.session_state.tor_data = tor_data
                # Reset downstream state
                st.session_state.retrieved_chunks = None
                st.session_state.retrieval_unavailable = False
                st.session_state.generated_draft = None
                st.session_state.output_file_path = None
                st.session_state.confirmed_tor_data = None
                st.session_state["trp_initialised"] = False
                st.session_state["drp_initialised"] = False
                st.session_state.approved_draft = None
                st.session_state.drp_regen_request = None
                if "error" not in tor_data:
                    # Update progress
                    st.session_state.progress_steps[0]["status"] = "done"
                    st.session_state.progress_steps[1]["status"] = "done"
                    st.rerun()
                else:
                    st.error(f"Could not extract requirements: {tor_data.get('error', 'Unknown error')}")
            except Exception as e:
                raise

# ---------------------------------------------------------------------------
# STEP 1.5 — ToR Review Panel
# ---------------------------------------------------------------------------

confirmed_tor_data = None
if st.session_state.tor_data and "error" not in st.session_state.tor_data:
    confirmed_tor_data = render_tor_review(st.session_state.tor_data)
    if confirmed_tor_data:
        st.session_state.confirmed_tor_data = confirmed_tor_data

if st.session_state.get("confirmed_tor_data"):
    confirmed_tor_data = st.session_state.confirmed_tor_data

try:
    from draft_generator import ALL_SECTIONS
except Exception:
    ALL_SECTIONS = [
        "opening_statement",
        "institutional_overview",
        "country_table",
        "geographic_experience",
        "thematic_areas",
        "selected_project_experience",
        "alignment_with_tor",
    ]

if confirmed_tor_data:
    st.subheader("Step 2: Output Options")

    output_language = st.radio(
        "Output Language",
        options=["English", "Spanish", "Match ToR"],
        index=0,
        horizontal=True,
        key="output_language",
    )

    sections_to_include = st.multiselect(
        "Sections to Include",
        options=ALL_SECTIONS,
        default=ALL_SECTIONS,
        key="sections_to_include",
    )
    st.session_state.sections = sections_to_include if sections_to_include else ALL_SECTIONS

    condensed_mode = st.checkbox(
        "Generate condensed version (8-10 pages)",
        value=False,
        key="condensed_mode",
    )
else:
    # Provide defaults so downstream code doesn't fail with NameError
    output_language = "English"
    sections_to_include = ALL_SECTIONS if 'ALL_SECTIONS' in dir() else []
    condensed_mode = False

# ---------------------------------------------------------------------------
# STEP 2.5 — Discovery Panel
# ---------------------------------------------------------------------------

discovery_result = None
if confirmed_tor_data:
    if st.session_state.get("retrieved_chunks") is None:
        with st.spinner("Searching capability library..."):
            from capability_retriever import retrieve_chunks
            retrieval_filters = {"geography": [], "thematic_areas": [], "funder": []}
            retrieval_result = retrieve_chunks(
                confirmed_tor_data,
                retrieval_filters,
            )
            st.session_state.retrieved_chunks = retrieval_result.get("retrieved_chunks", [])
            st.session_state.retrieval_unavailable = bool(
                retrieval_result.get("library_unavailable", False)
            )
    if st.session_state.get("retrieval_unavailable"):
        _show_library_unavailable_warning(
            st,
            st.session_state.get("retrieval_unavailable", False),
        )
    if st.session_state.retrieved_chunks:
        discovery_result = render_discovery_panel(
            st.session_state.retrieved_chunks,
            confirmed_tor_data,
            GEOGRAPHY_OPTIONS,
            THEMATIC_OPTIONS,
        )
        # Auto-trigger generation when discovery confirms
        if discovery_result is not None and not st.session_state.get("generated_draft"):
            st.session_state["drp_trigger_generate"] = True

# ---------------------------------------------------------------------------
# STEP 3 — Generate (8.7 / 8.8 / 8.9)
# ---------------------------------------------------------------------------

st.subheader("Step 3: Generate Capability Statement")

# Guard conditions. Generation depends on searchable evidence (a non-empty
# index), not on the source-document count. We route the index decision through
# _document_generation_enabled(library_state, chunk_count) so the UI copy below
# and the button's enabled state cannot disagree (blocker 7).
searchable_chunks = chunk_count if isinstance(chunk_count, int) else 0
index_allows_generation = _document_generation_enabled(library_state, chunk_count)
can_generate = _can_generate(
    api_key_missing=api_key_missing,
    tor_data=confirmed_tor_data,
    doc_count=searchable_chunks if index_allows_generation else 0,
    retrieval_unavailable=st.session_state.get("retrieval_unavailable", False),
)

if api_key_missing:
    st.warning("Cannot generate: API key is missing.")
if confirmed_tor_data is None:
    st.info("Please upload a ToR document and confirm your selections first.")
if library_state == "index_unavailable":
    st.warning(
        "⚠️ The search index is unavailable, so document generation is disabled. "
        "This is an infrastructure issue, not an absence of relevant evidence."
    )
elif library_state == "empty_index":
    st.warning(
        "⚠️ The search index is empty. "
        "Click 'Update Library' in the sidebar to index your documents."
    )

generate_button = st.button(
    "🚀 Generate Capability Statement",
    disabled=not can_generate,
    type="primary",
)

if (generate_button and can_generate) or (
    st.session_state.get("drp_trigger_generate") and not st.session_state.get("generated_draft")
):
    st.session_state["drp_trigger_generate"] = False
    # Reset progress
    for step in st.session_state.progress_steps:
        step["status"] = "pending"
    st.session_state.condensed_file_path = None

    try:
        # Progress display container
        progress_container = st.empty()

        def update_progress(step_index, status):
            st.session_state.progress_steps[step_index]["status"] = status

        # Step: Use chunks from Discovery Panel
        update_progress(2, "active")
        if discovery_result is not None:
            chunks_to_use = discovery_result["selected_chunks"]
            geo_priority = discovery_result["geo_priority"]
            thematic_emphasis = discovery_result["thematic_emphasis"]
        else:
            chunks_to_use = st.session_state.retrieved_chunks or []
            geo_priority = "equal"
            thematic_emphasis = []
        st.session_state.retrieved_chunks = chunks_to_use
        st.session_state["last_chunks_used"] = chunks_to_use
        update_progress(2, "done")

        # Step: Generate draft
        update_progress(3, "active")
        with st.spinner("Generating capability statement draft..."):
            from draft_generator import generate_draft
            generated_draft = generate_draft(
                confirmed_tor_data,
                chunks_to_use,
                sections_to_include=st.session_state.sections,
                output_language=output_language,
            )
            if "error" in generated_draft:
                st.error(f"Generation failed: {generated_draft['error']}")
                st.stop()
            st.session_state.generated_draft = generated_draft
            print('COUNTRY_TABLE_SAMPLE:', st.session_state.generated_draft.get('sections', {}).get('country_table', [])[:2])
        update_progress(3, "done")

        # Draft generated — hand off to review panel
        st.session_state.approved_draft = None
        st.rerun()

    except Exception as e:
        st.error(f"An unexpected error occurred: {e}")

# ---------------------------------------------------------------------------
# Progress indicator display (8.8)
# ---------------------------------------------------------------------------

# Show progress steps
if any(s["status"] != "pending" for s in st.session_state.progress_steps):
    st.markdown("**Pipeline Progress:**")
    for step in st.session_state.progress_steps:
        if step["status"] == "done":
            st.markdown(f"✅ {step['label']}")
        elif step["status"] == "active":
            st.markdown(f"⏳ {step['label']}...")
        else:
            st.markdown(f"⬜ {step['label']}")

# ---------------------------------------------------------------------------
# STEP 3.5 — Draft Review Panel
# ---------------------------------------------------------------------------

if st.session_state.generated_draft and "error" not in st.session_state.generated_draft:
    # Handle pending regeneration request from panel
    if st.session_state.get("drp_regen_request"):
        regen = st.session_state.drp_regen_request
        with st.spinner(f"Regenerating {regen['section_id']}..."):
            from draft_generator import generate_draft as _regen_draft
            section_draft = _regen_draft(
                confirmed_tor_data or st.session_state.get("confirmed_tor_data", {}),
                st.session_state.get("last_chunks_used", []),
                output_language=output_language if 'output_language' in dir() else "English",
                feedback=regen.get("feedback", ""),
                single_section=regen["section_id"],
            )
            if "error" not in section_draft:
                new_content = section_draft.get("sections", {}).get(
                    regen["section_id"], regen.get("current_content", "")
                )
                st.session_state[f"drp_section_content_{regen['section_id']}"] = new_content
                st.session_state[f"drp_section_approved_{regen['section_id']}"] = False
            st.session_state.drp_regen_request = None
            st.rerun()

    # Render the draft review panel
    panel_result = render_draft_review(
        st.session_state.generated_draft,
        confirmed_tor_data or st.session_state.get("confirmed_tor_data", {}),
    )

    if panel_result is None:
        pass  # Panel still open — waiting for Mark
    elif panel_result.get("action") == "regenerate_section":
        st.session_state.drp_regen_request = panel_result
        st.rerun()
    else:
        # Mark confirmed — approved_draft received
        st.session_state.approved_draft = panel_result

# ---------------------------------------------------------------------------
# STEP 4 — Format and download (runs after approval)
# ---------------------------------------------------------------------------

if st.session_state.get("approved_draft"):
    approved = st.session_state.approved_draft

    with st.spinner("Formatting Word document..."):
        from citation_tagger import tag_citations
        from output_formatter import write_output

        approved_sections = approved["sections"]
        section_order = approved.get("section_order", list(approved_sections.keys()))

        ordered_draft = {
            "sections": {k: approved_sections[k] for k in section_order if k in approved_sections},
            "interpretation_log": approved.get("interpretation_log", []),
            "summary": approved.get("summary", {}),
        }

        citation_result = tag_citations(ordered_draft.get("sections", {}))

        # Restore country_table from original list if available
        original_ct = st.session_state.get("drp_country_table_original")
        if original_ct is not None and isinstance(original_ct, list):
            ordered_draft["sections"]["country_table"] = original_ct
        elif "country_table" in ordered_draft["sections"]:
            if isinstance(ordered_draft["sections"]["country_table"], str):
                del ordered_draft["sections"]["country_table"]
                section_order = [s for s in section_order
                                 if s != "country_table"]

        output_path = write_output(
            ordered_draft,
            citation_result,
            output_language=output_language if 'output_language' in dir() else "English",
            sections_to_include=section_order,
            section_formats=approved.get("section_formats", {}),
            output_path=os.path.abspath(OUTPUT_PATH),
        )

        if output_path.startswith("ERROR:"):
            st.error(f"Failed to create document: {output_path}")
        else:
            st.session_state.output_file_path = output_path
            st.success("✅ Capability statement ready for download.")

            try:
                with open(os.path.abspath(st.session_state.output_file_path), "rb") as f:
                    docx_bytes = f.read()
                filename = os.path.basename(st.session_state.output_file_path)
                st.download_button(
                    label="📥 Download Capability Statement (.docx)",
                    data=docx_bytes,
                    file_name=filename,
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    type="primary",
                )
            except Exception as e:
                st.error(f"Could not prepare download: {e}")
