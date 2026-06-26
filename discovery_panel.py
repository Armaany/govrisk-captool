"""
discovery_panel.py — Component 1, v1.3
Standalone Streamlit UI module inserted between retrieve_chunks() and generate_draft().

Lets the user review retrieved evidence, select which projects to include,
set geography priority and thematic emphasis, and export a self-contained
prompt .txt file for external use (e.g. ChatGPT).

No ChromaDB calls. No Claude API calls. Pure UI logic + data transformation.
"""
import streamlit as st
from datetime import datetime
from collections import Counter
from config import GEOGRAPHY_OPTIONS, THEMATIC_OPTIONS

# ASSUMPTION: source_file is the unique project identifier.
# ASSUMPTION: funder may be absent; fallback is "Unknown".
# ASSUMPTION: empty chunk list shows "No projects found", both buttons disabled.

__all__ = [
    "render_discovery_panel",
    "_clean_display_name",
    "_group_chunks_by_project",
    "_build_prompt_txt",
]


# ---------------------------------------------------------------------------
# 1. _clean_display_name
# ---------------------------------------------------------------------------

def _clean_display_name(source_file: str) -> str:
    """
    Strip file extension. Replace underscores and hyphens with spaces.
    Apply str.title(). Return result.

    Example: "PECEL_Mexico_Final_Report.pdf" -> "Pecel Mexico Final Report"
    """
    # Strip extension
    name = source_file
    if "." in name:
        name = name.rsplit(".", 1)[0]
    # Replace underscores and hyphens with spaces
    name = name.replace("_", " ").replace("-", " ")
    return name.title()


# ---------------------------------------------------------------------------
# 2. _group_chunks_by_project
# ---------------------------------------------------------------------------

def _group_chunks_by_project(chunks: list) -> list:
    """
    Group chunks by source_file. Build a ProjectGroup dict for each group.
    Sort returned list by top_score descending.
    """
    groups: dict = {}

    for chunk in chunks:
        source_file = chunk.get("source_file", "unknown")
        if source_file not in groups:
            groups[source_file] = {
                "project_id": source_file,
                "display_name": _clean_display_name(source_file),
                "chunks": [],
                "_funders": [],
                "_geography": [],
                "_thematic_areas": [],
            }
        groups[source_file]["chunks"].append(chunk)

        # Collect funder (stored in chunk as donor or funder field)
        funder_val = chunk.get("donor") or chunk.get("funder") or ""
        if funder_val:
            groups[source_file]["_funders"].append(funder_val)

        # Union geography
        for g in (chunk.get("geography") or []):
            if g and g not in groups[source_file]["_geography"]:
                groups[source_file]["_geography"].append(g)

        # Union thematic_areas
        for t in (chunk.get("thematic_areas") or []):
            if t and t not in groups[source_file]["_thematic_areas"]:
                groups[source_file]["_thematic_areas"].append(t)

    result = []
    for source_file, group in groups.items():
        # Most common non-empty funder, or "Unknown"
        if group["_funders"]:
            most_common_funder = Counter(group["_funders"]).most_common(1)[0][0]
        else:
            most_common_funder = "Unknown"

        top_score = max(
            (c.get("relevance_score", 0.0) for c in group["chunks"]),
            default=0.0,
        )

        result.append({
            "project_id": group["project_id"],
            "display_name": group["display_name"],
            "funder": most_common_funder,
            "geography": group["_geography"],
            "thematic_areas": group["_thematic_areas"],
            "chunks": group["chunks"],
            "top_score": top_score,
        })

    # Sort by top_score descending
    result.sort(key=lambda p: p["top_score"], reverse=True)
    return result


# ---------------------------------------------------------------------------
# 3. _build_prompt_txt
# ---------------------------------------------------------------------------

def _build_prompt_txt(
    selected_projects: list,
    tor_data: dict,
    geo_priority: str,
    thematic_emphasis: list,
) -> str:
    """
    Build and return the full prompt string for export / external LLM use.
    """
    total_chunks = sum(len(p["chunks"]) for p in selected_projects)
    project_count = len(selected_projects)

    # Numbered key requirements
    key_reqs = tor_data.get("key_requirements", [])
    if key_reqs:
        numbered_reqs = "\n".join(f"{i+1}. {req}" for i, req in enumerate(key_reqs))
    else:
        numbered_reqs = "(none listed)"

    # Projects approved for inclusion
    projects_list = "\n".join(
        f"- {p['display_name']} ({p['funder']})" for p in selected_projects
    )

    # Source evidence block
    evidence_parts = []
    for project in selected_projects:
        chunk_lines = []
        for i, chunk in enumerate(project["chunks"], start=1):
            page = chunk.get("page_number", "?")
            text = chunk.get("text", "")
            chunk_lines.append(f"Chunk {i} (p.{page}): {text}")
        evidence_parts.append(
            f"[Project: {project['display_name']}]\n" + "\n".join(chunk_lines)
        )
    evidence_block = "\n\n".join(evidence_parts)

    prompt = (
        "SYSTEM\n"
        "You are a proposal writer for GovRisk, a UK consulting firm specialising\n"
        "in AML/CFT, anti-corruption, justice reform, and illicit financial flows\n"
        "in Latin America and the Caribbean.\n"
        "Your task is to generate a professional capability statement in response\n"
        "to the Terms of Reference summarised below.\n"
        "\n"
        "Rules:\n"
        "- Only use evidence from the SOURCE EVIDENCE section below.\n"
        "- If no evidence supports a claim, write [EVIDENCE NEEDED: description].\n"
        "- Cite every factual claim using [Source: filename, p.N].\n"
        "- Do not invent project names, dates, outcomes, or statistics.\n"
        "--------------------------------------------------\n"
        "OPPORTUNITY\n"
        f"Title:    {tor_data.get('title', 'Unknown')}\n"
        f"Funder:   {tor_data.get('funder', 'Unknown')}\n"
        f"Geography:{', '.join(tor_data.get('geography', []))}\n"
        f"Themes:   {', '.join(tor_data.get('thematic_areas', []))}\n"
        "\n"
        "KEY REQUIREMENTS\n"
        f"{numbered_reqs}\n"
        "--------------------------------------------------\n"
        "MARK'S SELECTIONS\n"
        f"Geography priority: {geo_priority}\n"
        f"Thematic emphasis:  {', '.join(thematic_emphasis)}\n"
        "\n"
        "PROJECTS APPROVED FOR INCLUSION\n"
        f"{projects_list}\n"
        "--------------------------------------------------\n"
        "SOURCE EVIDENCE\n"
        f"({total_chunks} chunks from {project_count} projects)\n"
        "\n"
        f"{evidence_block}\n"
        "--------------------------------------------------\n"
        "GENERATE the capability statement now. Follow all rules above.\n"
    )
    return prompt


# ---------------------------------------------------------------------------
# 4. render_discovery_panel
# ---------------------------------------------------------------------------

def render_discovery_panel(
    retrieved_chunks: list,
    tor_data: dict,
    geo_options: list,
    thematic_options: list,
) -> "dict | None":
    """
    Main function. Renders the full discovery panel Streamlit UI.
    Returns the result dict when Generate is clicked, otherwise None.
    """
    # A. Header
    st.subheader("Step 2.5 — Review & Confirm Evidence")

    # Group chunks into projects
    projects = _group_chunks_by_project(retrieved_chunks)
    n_projects = len(projects)

    # B. Project checklist
    st.markdown(f"**Projects found: {n_projects}**")

    if n_projects == 0:
        st.info("No projects found. Please adjust your filters and retrieve again.")
        # Both buttons disabled — render them greyed out
        col1, col2 = st.columns(2)
        with col1:
            st.button("🚀 Generate Capability Statement", disabled=True)
        with col2:
            st.button("📥 Download Prompt .txt", disabled=True)
        return None

    # Initialise session state checkboxes (default True = all selected)
    for project in projects:
        key = f"dp_project_checked_{project['project_id']}"
        if key not in st.session_state:
            st.session_state[key] = True

    # [Select all] and [Clear all] buttons
    btn_col1, btn_col2 = st.columns([1, 1])
    with btn_col1:
        if st.button("☑ Select all", key="dp_select_all"):
            for project in projects:
                st.session_state[f"dp_project_checked_{project['project_id']}"] = True
    with btn_col2:
        if st.button("☐ Clear all", key="dp_clear_all"):
            for project in projects:
                st.session_state[f"dp_project_checked_{project['project_id']}"] = False

    # Render one checkbox row per project
    for project in projects:
        state_key = f"dp_project_checked_{project['project_id']}"
        geo_tags = " · ".join(project["geography"]) if project["geography"] else "—"
        thematic_tags = " · ".join(project["thematic_areas"]) if project["thematic_areas"] else "—"
        label = (
            f"**{project['display_name']}**  "
            f"| 📍 {geo_tags}  "
            f"| 🏷 {thematic_tags}  "
            f"| 🏦 {project['funder']}  "
            f"| score: {project['top_score']:.2f}"
        )
        st.session_state[state_key] = st.checkbox(
            label,
            value=st.session_state[state_key],
            key=f"dp_cb_{project['project_id']}",
        )

    # C. Priority controls in two columns
    st.markdown("---")
    left_col, right_col = st.columns(2)

    geo_radio_options = ["Mexico first", "Regional / LATAM", "All equally weighted"]
    geo_priority_map = {
        "Mexico first": "exact",
        "Regional / LATAM": "lac",
        "All equally weighted": "equal",
    }

    if "dp_geo_priority" not in st.session_state:
        st.session_state["dp_geo_priority"] = "Mexico first"

    with left_col:
        geo_radio_val = st.radio(
            "Geography priority",
            options=geo_radio_options,
            index=geo_radio_options.index(st.session_state["dp_geo_priority"]),
            key="dp_geo_radio",
        )
        st.session_state["dp_geo_priority"] = geo_radio_val

    if "dp_thematic_emphasis" not in st.session_state:
        st.session_state["dp_thematic_emphasis"] = list(thematic_options)

    with right_col:
        thematic_val = st.multiselect(
            "Thematic emphasis",
            options=thematic_options,
            default=st.session_state["dp_thematic_emphasis"],
            key="dp_thematic_ms",
        )
        st.session_state["dp_thematic_emphasis"] = thematic_val

    geo_priority = geo_priority_map.get(st.session_state["dp_geo_priority"], "equal")
    thematic_emphasis = st.session_state["dp_thematic_emphasis"]

    # D. Evidence summary (live)
    selected_projects = [
        p for p in projects
        if st.session_state.get(f"dp_project_checked_{p['project_id']}", False)
    ]
    selected_chunks = [c for p in selected_projects for c in p["chunks"]]
    n_selected = len(selected_projects)
    n_chunks = len(selected_chunks)
    n_themes = len(thematic_emphasis)

    st.markdown("---")
    st.markdown(
        f"**{n_selected} projects selected · {n_chunks} chunks included · "
        f"Priority: {st.session_state['dp_geo_priority']}**"
    )
    st.markdown(f"*{n_themes} themes emphasised*")

    # E. Action buttons
    st.markdown("---")
    buttons_disabled = n_selected == 0

    action_col1, action_col2 = st.columns(2)

    with action_col1:
        generate_clicked = st.button(
            "🚀 Generate Capability Statement",
            disabled=buttons_disabled,
            type="primary",
            key="dp_generate_btn",
        )

    with action_col2:
        download_clicked = st.button(
            "📥 Download Prompt .txt",
            disabled=buttons_disabled,
            key="dp_download_btn",
        )

    # Handle Generate
    if generate_clicked and not buttons_disabled:
        prompt_txt = _build_prompt_txt(
            selected_projects, tor_data, geo_priority, thematic_emphasis
        )
        st.session_state["dp_prompt_txt"] = prompt_txt
        st.session_state["dp_confirmed"] = True

        return {
            "selected_chunks": selected_chunks,
            "selected_projects": selected_projects,
            "geo_priority": geo_priority,
            "thematic_emphasis": thematic_emphasis,
            "prompt_txt_content": prompt_txt,
        }

    # Handle Download (does NOT trigger generation)
    if download_clicked and not buttons_disabled:
        prompt_txt = st.session_state.get("dp_prompt_txt")
        if not prompt_txt:
            prompt_txt = _build_prompt_txt(
                selected_projects, tor_data, geo_priority, thematic_emphasis
            )
            st.session_state["dp_prompt_txt"] = prompt_txt

        st.download_button(
            label="📄 Click to download",
            data=prompt_txt,
            file_name=f"GovRisk_Prompt_{datetime.now().strftime('%Y-%m-%d')}.txt",
            mime="text/plain",
            key="dp_download_actual",
        )

    return None
