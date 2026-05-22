"""
app.py — Task 8
Single-page Streamlit application for the GovRisk Capability Statement Generator.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import streamlit as st

# ---------------------------------------------------------------------------
# Module-level helper functions (used by tests)
# ---------------------------------------------------------------------------

def _api_key_is_missing(key):
    """Return True if the API key is missing or empty."""
    return not key or key.strip() == ""


def _can_generate(api_key_missing, tor_data, doc_count):
    """Return True only when all preconditions for generation are met."""
    if api_key_missing:
        return False
    if tor_data is None:
        return False
    if doc_count == 0:
        return False
    return True


# ---------------------------------------------------------------------------
# Filter normalization helpers
# ---------------------------------------------------------------------------

from config import GEOGRAPHY_OPTIONS, THEMATIC_OPTIONS, FUNDER_OPTIONS

_GEO_NORMALIZE = {
    "Western Hemisphere": "Regional / LATAM",
    "Latin America": "Regional / LATAM",
    "LATAM": "Regional / LATAM",
    "Caribbean": "Caribbean",
    "Central America": "Central America",
    "Mexico": "Mexico",
    "Colombia": "Colombia",
    "Peru": "Peru",
    "Brazil": "Brazil",
    "Argentina": "Argentina",
    "Chile": "Chile",
}

_THEMATIC_NORMALIZE = {
    "Counterterrorism": "CTF/Terrorist Financing",
    "Terrorist Financing": "CTF/Terrorist Financing",
    "Financial Disruption": "AML/CFT",
    "AML": "AML/CFT",
    "CFT": "AML/CFT",
    "Anti-money laundering": "AML/CFT",
    "Illicit Finance": "Illicit Financial Flows",
    "Illicit Financial Flows": "Illicit Financial Flows",
    "Asset Recovery": "Asset Recovery",
    "Anti-corruption": "Anti-corruption",
    "Justice Reform": "Justice Reform",
    "Law Enforcement": "Justice Reform",
    "Criminal Justice": "Justice Reform",
    "Prosecutorial Capacity Building": "Justice Reform",
    "Counter-Narcotics": "AML/CFT",
    "Organized Crime": "Illicit Financial Flows",
    "Transnational Criminal Organizations": "CTF/Terrorist Financing",
    "Cross-border Cooperation": "Justice Reform",
    "Evidence Handling": "Justice Reform",
}

_FUNDER_NORMALIZE = {
    "Bureau of International Narcotics": "US State Dept",
    "INL": "US State Dept",
    "U.S. Department of State": "US State Dept",
    "US Department of State": "US State Dept",
}


def _normalize_filter_values(values: list, normalize_map: dict, valid_options: list) -> list:
    """
    Map extracted values to the closest matching option using normalize_map,
    then keep only values that exist in valid_options. Preserves order, no duplicates.
    """
    result = []
    seen = set()
    for v in values:
        mapped = normalize_map.get(v, v)  # map if known, else keep as-is
        if mapped in valid_options and mapped not in seen:
            result.append(mapped)
            seen.add(mapped)
    return result


def _normalize_funder(funder_str: str) -> list:
    """
    Match a funder string against _FUNDER_NORMALIZE using substring matching.
    Returns a list with the normalized value if a match is found, else empty list.
    """
    funder_lower = funder_str.lower()
    for key, value in _FUNDER_NORMALIZE.items():
        if key.lower() in funder_lower:
            return [value]
    return []


# ---------------------------------------------------------------------------
# Session state initialisation (8.2)
# ---------------------------------------------------------------------------

DEFAULTS = {
    "tor_data": None,
    "retrieved_chunks": None,
    "generated_draft": None,
    "output_file_path": None,
    "condensed_file_path": None,
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

    # Query ChromaDB for document count
    try:
        import chromadb
        from config import CHROMA_DB_PATH
        chroma_path = os.path.abspath(CHROMA_DB_PATH)
        client = chromadb.PersistentClient(path=chroma_path)
        collection = client.get_or_create_collection("govrisk_capabilities")
        doc_count = collection.count()
        st.metric("Documents indexed", doc_count)
    except Exception:
        doc_count = 0
        st.metric("Documents indexed", 0)

    # Last indexed date from index_manifest.json
    try:
        import json
        manifest_path = os.path.join(os.path.abspath(CHROMA_DB_PATH), "index_manifest.json")
        if os.path.exists(manifest_path):
            with open(manifest_path) as f:
                manifest = json.load(f)
            st.caption(f"Last indexed: {manifest.get('last_indexed', 'Unknown')}")
        else:
            st.caption("Last indexed: Never")
    except Exception:
        st.caption("Last indexed: Unknown")

    # Update Library button
    if st.button("🔄 Update Library"):
        with st.spinner("Indexing capability library..."):
            try:
                from capability_indexer import index_library
                summary = index_library(force_reindex=False)
                # Update manifest
                import json
                from datetime import datetime
                manifest_path = os.path.join(os.path.abspath(CHROMA_DB_PATH), "index_manifest.json")
                with open(manifest_path, "w") as f:
                    json.dump({"last_indexed": datetime.now().strftime("%Y-%m-%d %H:%M")}, f)
                st.success(
                    f"Indexed {summary['documents_processed']} docs, "
                    f"{summary['chunks_created']} chunks. "
                    f"Skipped: {summary['documents_skipped']}."
                )
                st.rerun()
            except Exception as e:
                st.error(f"Failed to update library: {e}")

    st.divider()
    st.caption(f"Library: {CAPABILITY_LIBRARY_PATH}")
    st.caption(f"Output: {OUTPUT_PATH}")
    st.caption(f"Model: {MODEL_NAME}")

# ---------------------------------------------------------------------------
# Main content area
# ---------------------------------------------------------------------------

st.title("GovRisk Capability Statement Generator")
st.markdown("Generate professional capability statements from your ToR and capability library.")

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
                st.session_state.generated_draft = None
                st.session_state.output_file_path = None
                # Auto-populate filters from tor_data
                if "error" not in tor_data:
                    st.session_state.filters["geography"] = _normalize_filter_values(
                        tor_data.get("geography", []), _GEO_NORMALIZE, GEOGRAPHY_OPTIONS
                    )
                    st.session_state.filters["thematic_areas"] = _normalize_filter_values(
                        tor_data.get("thematic_areas", []), _THEMATIC_NORMALIZE, THEMATIC_OPTIONS
                    )
                    st.session_state.filters["funder"] = _normalize_funder(
                        tor_data.get("funder", "")
                    )
                    # Update progress
                    st.session_state.progress_steps[0]["status"] = "done"
                    st.session_state.progress_steps[1]["status"] = "done"
                else:
                    st.error(f"Could not extract requirements: {tor_data.get('error', 'Unknown error')}")
            except Exception as e:
                raise

if st.session_state.tor_data and "error" not in st.session_state.tor_data:
    tor = st.session_state.tor_data
    with st.expander("📋 Extracted ToR Summary", expanded=False):
        st.write(f"**Title:** {tor.get('title', 'N/A')}")
        st.write(f"**Funder:** {tor.get('funder', 'N/A')}")
        st.write(f"**Geography:** {', '.join(tor.get('geography', []))}")
        st.write(f"**Thematic Areas:** {', '.join(tor.get('thematic_areas', []))}")
        st.write(f"**Confidence:** {tor.get('extraction_confidence', 'N/A')}")

# ---------------------------------------------------------------------------
# STEP 2 — Filters (8.6)
# ---------------------------------------------------------------------------

st.subheader("Step 2: Select Filters and Options")

from config import GEOGRAPHY_OPTIONS, THEMATIC_OPTIONS, FUNDER_OPTIONS

col1, col2, col3 = st.columns(3)

with col1:
    selected_geo = st.multiselect(
        "Geography",
        options=GEOGRAPHY_OPTIONS,
        default=st.session_state.filters.get("geography", []),
        key="filter_geography",
    )
    st.session_state.filters["geography"] = selected_geo

with col2:
    selected_thematic = st.multiselect(
        "Thematic Areas",
        options=THEMATIC_OPTIONS,
        default=st.session_state.filters.get("thematic_areas", []),
        key="filter_thematic",
    )
    st.session_state.filters["thematic_areas"] = selected_thematic

with col3:
    selected_funder = st.multiselect(
        "Funder",
        options=FUNDER_OPTIONS,
        default=st.session_state.filters.get("funder", []),
        key="filter_funder",
    )
    st.session_state.filters["funder"] = selected_funder

output_language = st.radio(
    "Output Language",
    options=["English", "Spanish", "Match ToR"],
    index=0,
    horizontal=True,
    key="output_language",
)

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

# ---------------------------------------------------------------------------
# STEP 3 — Generate (8.7 / 8.8 / 8.9)
# ---------------------------------------------------------------------------

st.subheader("Step 3: Generate Capability Statement")

# Guard conditions
can_generate = _can_generate(
    api_key_missing=api_key_missing,
    tor_data=st.session_state.tor_data,
    doc_count=doc_count,
)

if api_key_missing:
    st.warning("Cannot generate: API key is missing.")
if st.session_state.tor_data is None:
    st.info("Please upload a ToR document first.")
if doc_count == 0:
    st.warning(
        "⚠️ The capability library is empty. "
        "Click 'Update Library' in the sidebar to index your documents."
    )

generate_button = st.button(
    "🚀 Generate Capability Statement",
    disabled=not can_generate,
    type="primary",
)

if generate_button and can_generate:
    # Reset progress
    for step in st.session_state.progress_steps:
        step["status"] = "pending"
    st.session_state.condensed_file_path = None

    try:
        # Progress display container
        progress_container = st.empty()

        def update_progress(step_index, status):
            st.session_state.progress_steps[step_index]["status"] = status

        # Step: Retrieve chunks
        update_progress(2, "active")
        with st.spinner("Searching capability library..."):
            from capability_retriever import retrieve_chunks
            # TODO: re-enable after keyword detection fix
            retrieval_filters = {"geography": [], "thematic_areas": [], "funder": []}
            retrieval_result = retrieve_chunks(
                st.session_state.tor_data,
                retrieval_filters,
            )
            st.session_state.retrieved_chunks = retrieval_result.get("retrieved_chunks", [])
            print('CHUNKS_DEBUG: retrieved', len(st.session_state.retrieved_chunks), 'chunks')
        update_progress(2, "done")

        # Step: Generate draft
        update_progress(3, "active")
        with st.spinner("Generating capability statement draft..."):
            from draft_generator import generate_draft
            generated_draft = generate_draft(
                st.session_state.tor_data,
                st.session_state.retrieved_chunks,
                sections_to_include=st.session_state.sections,
                output_language=output_language,
            )
            if "error" in generated_draft:
                st.error(f"Generation failed: {generated_draft['error']}")
                st.stop()
            st.session_state.generated_draft = generated_draft
            print('COUNTRY_TABLE_SAMPLE:', st.session_state.generated_draft.get('sections', {}).get('country_table', [])[:2])
        update_progress(3, "done")

        # Step: Format document
        update_progress(4, "active")
        with st.spinner("Formatting Word document..."):
            from citation_tagger import tag_citations
            from output_formatter import write_output

            citation_result = tag_citations(
                st.session_state.generated_draft.get("sections", {})
            )

            output_path = write_output(
                st.session_state.generated_draft,
                citation_result,
                output_language=output_language,
                sections_to_include=st.session_state.sections,
            )

            if output_path.startswith("ERROR:"):
                st.error(f"Failed to create document: {output_path}")
                st.stop()

            st.session_state.output_file_path = output_path
        update_progress(4, "done")

        # Step: Condensed version (optional)
        if condensed_mode:
            update_progress(5, "active")
            with st.spinner("Generating condensed version..."):
                try:
                    import anthropic as _anthropic
                    import json as _json
                    from datetime import datetime as _dt
                    from draft_generator import _strip_markdown_fences as _strip_fences

                    # Step 1 — Extract original country_table (never condense it)
                    draft_sections = st.session_state.generated_draft.get("sections", {})
                    original_country_table = draft_sections.get("country_table", [])

                    # Build input text from all string sections
                    section_order = [
                        "opening_statement",
                        "institutional_overview",
                        "geographic_experience",
                        "thematic_areas",
                        "selected_project_experience",
                        "alignment_with_tor",
                    ]
                    section_texts = []
                    for key in section_order:
                        val = draft_sections.get(key, "")
                        if isinstance(val, str) and val.strip():
                            section_texts.append(f"[SECTION:{key}]\n{val}")
                    full_draft_text = "\n\n".join(section_texts)

                    # Step 2 — Call Claude API
                    _condensed_system = (
                        "You are a professional document editor. "
                        "Condense this capability statement to 8-10 pages. "
                        "Rules: shorten geographic experience to two sentences per country; "
                        "compress thematic areas to three bullet points per theme; "
                        "keep the three strongest project cards with full detail; "
                        "keep all citation tags in format REF:filename:page_N; "
                        "never invent content; "
                        "preserve past tense for completed and present tense with ongoing marker for active projects. "
                        "Return a JSON object with these exact keys: opening_statement, institutional_overview, "
                        "geographic_experience, thematic_areas, selected_project_experience, alignment_with_tor. "
                        "Each value is the condensed text for that section."
                    )

                    _condensed_user = (
                        "Condense the following capability statement sections. "
                        "Each section is marked with [SECTION:key]. "
                        "Return a JSON object with the same keys and condensed text values. "
                        "Preserve all [REF:filename:page_N] citation tags.\n\n"
                        f"{full_draft_text}"
                    )

                    _condensed_client = _anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
                    _condensed_response = _condensed_client.messages.create(
                        model="claude-sonnet-4-5",
                        max_tokens=8000,
                        system=_condensed_system,
                        messages=[{"role": "user", "content": _condensed_user}],
                    )
                    condensed_raw = _condensed_response.content[0].text

                    # Step 3 — Parse response using _strip_markdown_fences
                    try:
                        cleaned = _strip_fences(condensed_raw)
                        condensed_sections = _json.loads(cleaned)
                    except Exception:
                        # Fallback: put entire response in opening_statement
                        condensed_sections = {k: "" for k in section_order}
                        condensed_sections["opening_statement"] = condensed_raw

                    # Ensure all section keys exist
                    for _k in section_order:
                        if _k not in condensed_sections:
                            condensed_sections[_k] = ""

                    # Step 4 — Restore original country_table
                    condensed_sections["country_table"] = original_country_table

                    condensed_draft = {
                        "sections": condensed_sections,
                        "interpretation_log": [],
                        "summary": st.session_state.generated_draft.get("summary", {}),
                    }

                    # Step 5 — Tag citations and write output
                    from citation_tagger import tag_citations as _tag_citations
                    from output_formatter import write_output as _write_output

                    _condensed_citations = _tag_citations(condensed_sections)

                    condensed_filename_ts = _dt.now().strftime("%Y-%m-%d_%H-%M")
                    _condensed_out_dir = os.path.abspath(OUTPUT_PATH)
                    os.makedirs(_condensed_out_dir, exist_ok=True)

                    _condensed_result = _write_output(
                        condensed_draft,
                        _condensed_citations,
                        output_language=output_language,
                        sections_to_include=None,
                        output_path=_condensed_out_dir,
                    )

                    # Rename to condensed filename
                    if not _condensed_result.startswith("ERROR:"):
                        condensed_out_path = os.path.join(
                            _condensed_out_dir,
                            f"GovRisk_CapabilityStatement_Condensed_{condensed_filename_ts}.docx",
                        )
                        import shutil as _shutil
                        _shutil.move(_condensed_result, condensed_out_path)
                        # Step 6 — Store absolute path
                        st.session_state.condensed_file_path = os.path.abspath(condensed_out_path)
                    else:
                        st.error(f"Condensed formatting failed: {_condensed_result}")

                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    st.error(f"Condensed generation failed: {e}")
            update_progress(5, "done")

        st.success("✅ Capability statement generated successfully!")

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
# STEP 4 — Results and Download (8.10 / 8.11)
# ---------------------------------------------------------------------------

if st.session_state.generated_draft and st.session_state.output_file_path:
    st.subheader("Step 4: Review and Download")

    # Summary panel (8.10)
    summary = st.session_state.generated_draft.get("summary", {})
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Sections", summary.get("sections_generated", 0))
    col2.metric("Projects", summary.get("projects_referenced", 0))
    col3.metric("Countries", summary.get("countries_covered", 0))
    col4.metric("Documents", summary.get("documents_used", 0))
    col5.metric("Confidence", summary.get("overall_confidence", "N/A"))

    # Interpretation log (8.10)
    interp_log = st.session_state.generated_draft.get("interpretation_log", [])
    if interp_log:
        with st.expander("📊 Interpretation Log", expanded=False):
            for entry in interp_log:
                confidence = entry.get("confidence", "LOW")
                color = {"HIGH": "🟢", "MEDIUM": "🟡", "LOW": "🔴"}.get(confidence, "⚪")
                st.markdown(f"{color} **{entry.get('section', '')}**")
                st.markdown(f"- Inference: {entry.get('inference_made', '')}")
                st.markdown(f"- Source: {entry.get('source_used', '')}")
                if entry.get("gap_flagged"):
                    st.markdown(f"- ⚠️ Gap: {entry.get('gap_flagged')}")
                st.markdown(f"- Confidence: {confidence}")
                st.divider()

    # Download button (8.11)
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

    # Condensed download button (shown only if condensed version was generated)
    if st.session_state.get("condensed_file_path"):
        try:
            with open(st.session_state.condensed_file_path, "rb") as f:
                condensed_bytes = f.read()
            condensed_filename = os.path.basename(st.session_state.condensed_file_path)
            st.download_button(
                label="📄 Download Condensed Version (.docx)",
                data=condensed_bytes,
                file_name=condensed_filename,
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        except Exception as e:
            st.error(f"Could not prepare condensed download: {e}")
