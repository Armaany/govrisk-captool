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


# ---------------------------------------------------------------------------
# Session state initialisation (8.2)
# ---------------------------------------------------------------------------

DEFAULTS = {
    "tor_data": None,
    "retrieved_chunks": None,
    "generated_draft": None,
    "output_file_path": None,
    "filters": {"geography": [], "thematic_areas": [], "funder": []},
    "sections": None,   # None = all sections
    "progress_steps": [
        {"label": "ToR uploaded and read",       "status": "pending"},
        {"label": "Requirements extracted",       "status": "pending"},
        {"label": "Capability library searched",  "status": "pending"},
        {"label": "Generating draft",             "status": "pending"},
        {"label": "Formatting document",          "status": "pending"},
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

# ---------------------------------------------------------------------------
# Filter normalization helpers
# ---------------------------------------------------------------------------

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
        with open(st.session_state.output_file_path, "rb") as f:
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
