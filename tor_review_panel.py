"""
tor_review_panel.py — Component 3b, v1.3
Standalone Streamlit UI module for reviewing and confirming extracted ToR data.

Shows the full document text with color-coded paragraph highlights.
Mark can confirm, remove, or add any extracted entity.
Returns confirmed_tor_data dict.

No ChromaDB calls. No Claude API calls. Pure UI + data logic.
"""
import streamlit as st

# ASSUMPTION: tor_data always has "paragraphs" and "source_map"
# keys after the tor_extractor.py update. If missing (old data),
# the panel shows a fallback message: "Document text not available.
# Please re-upload the ToR."
# ASSUMPTION: Mark will interact with the right panel
# (confirm/remove/add) before clicking Confirm. The panel
# does not auto-confirm.
# ASSUMPTION: session state trp_initialised prevents
# re-initialisation of tags when Streamlit reruns on interaction.
# Without this, every button click resets Mark's edits.
# ASSUMPTION: Empty paragraphs from the extractor are already
# filtered before reaching this panel.

__all__ = [
    "render_tor_review",
    "_build_tor_at_a_glance",
    "_apply_review_state",
    "_build_paragraph_highlights",
    "_get_highlight_color",
    "_get_left_border_color",
]

# ---------------------------------------------------------------------------
# Color constants
# ---------------------------------------------------------------------------

_BG_COLORS = {
    "geo":    "#E6F1FB",
    "funder": "#E1F5EE",
    "theme":  "#EEEDFE",
    "req":    "#FAEEDA",
}

_BORDER_COLORS = {
    "geo":    "#185FA5",
    "funder": "#0F6E56",
    "theme":  "#534AB7",
    "req":    "#854F0B",
}

_TAG_STYLES = {
    "geo":    ("background:#E6F1FB; color:#0C447C;"),
    "funder": ("background:#E1F5EE; color:#0F6E56;"),
    "theme":  ("background:#EEEDFE; color:#3B31A1;"),
    "req":    ("background:#FAEEDA; color:#6B3E0A;"),
}

_PRIORITY = ["geo", "funder", "theme", "req"]


# ---------------------------------------------------------------------------
# 1. _build_tor_at_a_glance
# ---------------------------------------------------------------------------

def _build_tor_at_a_glance(tor_data: dict) -> dict:
    """Build a defensive, source-grounded summary of extracted ToR fields.

    This helper does not infer or generate new content. It only normalises the
    structured values already returned by ``tor_extractor.extract_tor`` so the
    user can review the inputs that will drive evidence retrieval and drafting.
    """

    def clean_text(value, fallback: str) -> str:
        if value is None:
            return fallback
        text = str(value).strip()
        return text or fallback

    def clean_items(value) -> list:
        if not isinstance(value, (list, tuple)):
            return []
        result = []
        seen = set()
        for item in value:
            text = str(item).strip() if item is not None else ""
            key = text.casefold()
            if text and key not in seen:
                seen.add(key)
                result.append(text)
        return result

    geography = clean_items(tor_data.get("geography"))
    thematic_areas = clean_items(tor_data.get("thematic_areas"))
    key_requirements = clean_items(tor_data.get("key_requirements"))
    evaluation_criteria = clean_items(tor_data.get("evaluation_criteria"))
    funder = clean_text(tor_data.get("funder"), "Not identified")

    confidence = clean_text(
        tor_data.get("extraction_confidence"), "UNKNOWN"
    ).upper()
    if confidence not in {"HIGH", "MEDIUM", "LOW"}:
        confidence = "UNKNOWN"

    missing_fields = []
    if funder == "Not identified":
        missing_fields.append("funder")
    if not geography:
        missing_fields.append("geography")
    if not thematic_areas:
        missing_fields.append("thematic areas")
    if not key_requirements:
        missing_fields.append("key requirements")

    return {
        "title": clean_text(tor_data.get("title"), "Title not identified"),
        "funder": funder,
        "geography": geography,
        "thematic_areas": thematic_areas,
        "key_requirements": key_requirements,
        "evaluation_criteria": evaluation_criteria,
        "language": clean_text(tor_data.get("language"), "Not identified"),
        "extraction_confidence": confidence,
        "missing_fields": missing_fields,
    }


def _apply_review_state(tor_data: dict, review_state) -> dict:
    """Return ToR data with the user's current review edits applied."""
    current = dict(tor_data)
    funders = review_state.get("trp_funder", [])
    current["funder"] = funders[0] if funders else ""
    current["geography"] = list(review_state.get("trp_geography", []))
    current["thematic_areas"] = list(
        review_state.get("trp_thematic_areas", [])
    )
    current["key_requirements"] = list(
        review_state.get("trp_key_requirements", [])
    )
    return current


# ---------------------------------------------------------------------------
# 2. _build_paragraph_highlights
# ---------------------------------------------------------------------------

def _build_paragraph_highlights(tor_data: dict) -> list:
    """
    Build the ParagraphHighlight list for all paragraphs.
    Returns one entry per paragraph, with highlight_types populated
    from source_map.
    """
    paragraphs = tor_data.get("paragraphs", [])
    source_map = tor_data.get("source_map", {})

    # Build a set of {(category_key, paragraph_index)} for fast lookup
    # category_key → highlight_type
    category_map = {
        "geography":      "geo",
        "thematic_areas": "theme",
        "funder":         "funder",
        "key_requirements": "req",
    }

    # Map paragraph_index → set of highlight types
    index_to_types: dict = {}
    for cat_key, hl_type in category_map.items():
        for entry in source_map.get(cat_key, []):
            idx = entry.get("paragraph_index", -1)
            if idx >= 0:
                index_to_types.setdefault(idx, set()).add(hl_type)

    result = []
    for i, text in enumerate(paragraphs):
        hl_types = sorted(
            index_to_types.get(i, set()),
            key=lambda t: _PRIORITY.index(t) if t in _PRIORITY else 99,
        )
        result.append({
            "paragraph_index": i,
            "text": text,
            "highlight_types": hl_types,
        })
    return result


# ---------------------------------------------------------------------------
# 3. _get_highlight_color
# ---------------------------------------------------------------------------

def _get_highlight_color(highlight_types: list) -> str:
    """
    Return CSS background color based on priority order:
    geo > funder > theme > req. Returns "" if no types.
    """
    for hl in _PRIORITY:
        if hl in highlight_types:
            return _BG_COLORS[hl]
    return ""


# ---------------------------------------------------------------------------
# 4. _get_left_border_color
# ---------------------------------------------------------------------------

def _get_left_border_color(highlight_types: list) -> str:
    """
    Return CSS border-left color based on priority order.
    Returns "transparent" if no types.
    """
    for hl in _PRIORITY:
        if hl in highlight_types:
            return _BORDER_COLORS[hl]
    return "transparent"


# ---------------------------------------------------------------------------
# 5. render_tor_review
# ---------------------------------------------------------------------------

def render_tor_review(tor_data: dict) -> "dict | None":
    """
    Main function. Renders the ToR review panel.
    Returns confirmed_tor_data dict when Mark confirms, else None.
    """
    # Fallback if paragraphs/source_map missing (old data)
    if not tor_data.get("paragraphs"):
        st.warning(
            "Document text not available. Please re-upload the ToR."
        )
        return None

    # A. Step header
    st.subheader("Step 1.5 — Review extracted information")
    st.caption(
        "The tool highlighted what it found in your document. "
        "Remove anything incorrect, add anything missed, then confirm to proceed."
    )

    # Initialise session state before rendering the summary so it always
    # reflects the user's current corrections after a Streamlit rerun.
    if not st.session_state.get("trp_initialised"):
        funder_val = tor_data.get("funder", "")
        st.session_state["trp_geography"] = list(tor_data.get("geography", []))
        st.session_state["trp_funder"] = [funder_val] if funder_val else []
        st.session_state["trp_thematic_areas"] = list(tor_data.get("thematic_areas", []))
        st.session_state["trp_key_requirements"] = list(tor_data.get("key_requirements", []))
        st.session_state["trp_confirmed"] = False
        st.session_state["trp_initialised"] = True

    # Source-grounded summary shown before the detailed paragraph review.
    summary = _build_tor_at_a_glance(
        _apply_review_state(tor_data, st.session_state)
    )
    st.markdown("### ToR at a glance")
    st.info(
        "Why this matters: the confirmed geography, themes and requirements "
        "control which GovRisk evidence is retrieved and how the capability "
        "statement is framed. Check this summary before continuing."
    )

    st.markdown("**Opportunity**")
    st.write(summary["title"])

    summary_col_1, summary_col_2 = st.columns(2)
    with summary_col_1:
        st.markdown("**Funder**")
        st.write(summary["funder"])
        st.markdown("**Geography**")
        st.write(", ".join(summary["geography"]) or "Not identified")
    with summary_col_2:
        st.markdown("**Language**")
        st.write(summary["language"])
        st.markdown("**Thematic areas**")
        st.write(", ".join(summary["thematic_areas"]) or "Not identified")

    st.markdown("**Key requirements**")
    if summary["key_requirements"]:
        for requirement in summary["key_requirements"]:
            st.write(f"- {requirement}")
    else:
        st.write("Not identified")

    if summary["evaluation_criteria"]:
        with st.expander("Evaluation criteria identified in the ToR"):
            for criterion in summary["evaluation_criteria"]:
                st.write(f"- {criterion}")

    confidence = summary["extraction_confidence"].title()
    st.caption(
        f"Extraction confidence: {confidence}. "
        "This is an automated extraction and must be confirmed against the ToR."
    )
    if summary["missing_fields"]:
        st.warning(
            "Please check the original ToR: the following information was not "
            f"identified automatically: {', '.join(summary['missing_fields'])}."
        )

    with st.expander("How the confirmed summary will be used"):
        st.markdown(
            "- **Funder** helps preserve the correct institutional context and terminology.\n"
            "- **Geography** prioritises GovRisk experience from relevant countries or regions.\n"
            "- **Thematic areas** guide the semantic search of the capability library.\n"
            "- **Key requirements** identify the capabilities and evidence the draft must address.\n"
            "- **Evaluation criteria**, when stated, show what evaluators are likely to score."
        )

    st.divider()
    st.markdown("### Verify against the source text")

    # B. Legend row
    legend_html = (
        '<span style="display:inline-block; background:#E6F1FB; color:#0C447C; '
        'font-size:12px; font-weight:500; padding:3px 10px; border-radius:4px; '
        'margin:2px 6px 2px 0;">Geography</span>'
        '<span style="display:inline-block; background:#EEEDFE; color:#3B31A1; '
        'font-size:12px; font-weight:500; padding:3px 10px; border-radius:4px; '
        'margin:2px 6px 2px 0;">Thematic area</span>'
        '<span style="display:inline-block; background:#E1F5EE; color:#0F6E56; '
        'font-size:12px; font-weight:500; padding:3px 10px; border-radius:4px; '
        'margin:2px 6px 2px 0;">Funder</span>'
        '<span style="display:inline-block; background:#FAEEDA; color:#6B3E0A; '
        'font-size:12px; font-weight:500; padding:3px 10px; border-radius:4px; '
        'margin:2px 6px 2px 0;">Requirement</span>'
    )
    st.markdown(legend_html, unsafe_allow_html=True)
    st.markdown("")

    # C. Two-column layout
    left_col, right_col = st.columns([2, 1])

    # LEFT COLUMN — Document text with highlights
    with left_col:
        st.markdown("**Document text**")
        highlights = _build_paragraph_highlights(tor_data)
        for para in highlights:
            text = para["text"].replace("<", "&lt;").replace(">", "&gt;")
            hl_types = para["highlight_types"]
            if hl_types:
                bg = _get_highlight_color(hl_types)
                border = _get_left_border_color(hl_types)
                st.markdown(
                    f'<div style="background: {bg}; border-left: 3px solid {border}; '
                    f'padding: 8px 12px; border-radius: 4px; margin-bottom: 8px; '
                    f'font-size: 13px; line-height: 1.65;">{text}</div>',
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    f'<div style="padding: 4px 12px; margin-bottom: 6px; '
                    f'font-size: 13px; line-height: 1.65; color: #888780;">{text}</div>',
                    unsafe_allow_html=True,
                )

    # RIGHT COLUMN — Confirmation panel
    with right_col:

        def _render_section(label: str, category: str, placeholder: str, tag_style: str):
            """Render a tag section with remove buttons and an add input."""
            st.markdown(f"<small style='color:#888;'>{label}</small>", unsafe_allow_html=True)
            items = st.session_state.get(category, [])

            # Render existing tags with remove buttons
            for i, item in enumerate(items):
                tag_col, btn_col = st.columns([4, 1])
                with tag_col:
                    st.markdown(
                        f'<span style="display:inline-block; {tag_style} '
                        f'font-size:12px; font-weight:500; padding:3px 10px; '
                        f'border-radius:4px; margin:2px 4px 2px 0;">{item}</span>',
                        unsafe_allow_html=True,
                    )
                with btn_col:
                    if st.button("×", key=f"trp_remove_{category}_{i}"):
                        st.session_state[category].pop(i)
                        st.rerun()

            # Add new item input
            new_val = st.text_input(
                label,
                placeholder=placeholder,
                label_visibility="collapsed",
                key=f"trp_add_{category}",
            )
            if new_val and new_val not in st.session_state[category]:
                st.session_state[category].append(new_val)
                st.rerun()

            st.markdown("")

        _render_section(
            "Geography",
            "trp_geography",
            "Add a country or region...",
            _TAG_STYLES["geo"],
        )
        _render_section(
            "Funder",
            "trp_funder",
            "Add funder name...",
            _TAG_STYLES["funder"],
        )
        _render_section(
            "Thematic areas",
            "trp_thematic_areas",
            "Add a thematic area...",
            _TAG_STYLES["theme"],
        )
        _render_section(
            "Key requirements",
            "trp_key_requirements",
            "Add a requirement...",
            _TAG_STYLES["req"],
        )

        # Evidence summary
        st.divider()
        n_geo = len(st.session_state.get("trp_geography", []))
        n_theme = len(st.session_state.get("trp_thematic_areas", []))
        n_req = len(st.session_state.get("trp_key_requirements", []))
        st.markdown(
            f"**{n_geo} countries · {n_theme} themes · {n_req} requirements**"
        )

        # Confirm button
        both_empty = (n_geo == 0 and n_theme == 0)
        if st.button(
            "✅ Confirm and search library",
            disabled=both_empty,
            type="primary",
            key="trp_confirm_btn",
        ):
            st.session_state["trp_confirmed"] = True

    # Return confirmed dict if confirmed
    if st.session_state.get("trp_confirmed"):
        trp_funder = st.session_state.get("trp_funder", [])
        return {
            "title":                tor_data.get("title", ""),
            "funder":               trp_funder[0] if trp_funder else "",
            "geography":            list(st.session_state.get("trp_geography", [])),
            "thematic_areas":       list(st.session_state.get("trp_thematic_areas", [])),
            "key_requirements":     list(st.session_state.get("trp_key_requirements", [])),
            "evaluation_criteria":  tor_data.get("evaluation_criteria", []),
            "language":             tor_data.get("language", "English"),
            "source_file":          tor_data.get("source_file", ""),
            "extraction_confidence": tor_data.get("extraction_confidence", "LOW"),
            "paragraphs":           tor_data.get("paragraphs", []),
            "source_map":           tor_data.get("source_map", {}),
        }

    return None
