"""
draft_review_panel.py — Component 4, v1.3
Standalone Streamlit UI module inserted between generate_draft() and write_output().

Gives Mark full control over the generated draft:
- Reorder sections (drag-and-drop via streamlit-sortables)
- Choose format per section (Narrative, Bullet list, Table, Project cards)
- Edit content inline
- Regenerate individual sections with feedback (returned to app.py)
- Approve sections
- Preview clean document before downloading

No write_output() call inside this module.
No Claude API calls inside this module.
Pure UI logic + data transformation.
"""
import re
import streamlit as st
from datetime import datetime

# ASSUMPTION: streamlit-sortables is installed before this module is used.
# If not installed, sort_items will raise ImportError — fall back to up/down buttons.
try:
    from streamlit_sortables import sort_items
    _SORTABLES_AVAILABLE = True
except ImportError:
    _SORTABLES_AVAILABLE = False

# ASSUMPTION: generated_draft["sections"] always contains at least one key.
# ASSUMPTION: Mark may leave sections unapproved and still confirm.
# ASSUMPTION: Country table section may contain a list of dicts — convert to string.
# ASSUMPTION: drp_initialised is reset when a new generated_draft arrives,
#             detected by storing a hash of generated_draft["summary"] in drp_draft_hash.

__all__ = [
    "render_draft_review",
    "_strip_citations",
    "_format_section_preview",
    "_build_preview_html",
]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_SECTION_ORDER = [
    "opening_statement",
    "institutional_overview",
    "geographic_experience",
    "thematic_areas",
    "selected_project_experience",
    "alignment_with_tor",
]

DISPLAY_NAMES = {
    "opening_statement":           "Opening statement",
    "institutional_overview":      "Institutional overview",
    "geographic_experience":       "Geographic experience",
    "thematic_areas":              "Thematic areas",
    "selected_project_experience": "Selected project experience",
    "alignment_with_tor":          "Alignment with ToR",
    "country_table":               "Country table",
}

SECTION_FORMAT_OPTIONS = {
    "opening_statement":           ["Narrative"],
    "institutional_overview":      ["Narrative", "Bullet list"],
    "geographic_experience":       ["Narrative", "Project cards", "Table"],
    "thematic_areas":              ["Narrative", "Bullet list"],
    "selected_project_experience": ["Project cards", "Narrative", "Table"],
    "alignment_with_tor":          ["Bullet list", "Narrative", "Table"],
    "country_table":               ["Table"],
}

_DEFAULT_FORMAT_OPTIONS = ["Narrative", "Bullet list", "Table"]

_GOVRISK_GREEN = "#0F6E56"


# ---------------------------------------------------------------------------
# 1. _strip_citations
# ---------------------------------------------------------------------------

def _strip_citations(text) -> str:
    """
    Remove all citation and evidence tags from text.
    Patterns removed:
      [Source: anything]
      [REF:anything:page_N]
      [EVIDENCE NEEDED: anything]
    Returns "" for non-string input.
    """
    if not isinstance(text, str):
        return ""
    # Remove [Source: ...] tags
    text = re.sub(r'\[Source:[^\]]*\]', '', text)
    # Remove [REF:...:page_N] tags
    text = re.sub(r'\[REF:[^\]]*\]', '', text)
    # Remove [EVIDENCE NEEDED: ...] tags
    text = re.sub(r'\[EVIDENCE NEEDED:[^\]]*\]', '', text)
    return text.strip()


# ---------------------------------------------------------------------------
# 2. _format_section_preview
# ---------------------------------------------------------------------------

def _format_section_preview(section_id: str, content: str, format_choice: str) -> str:
    """
    Return an HTML string rendering the section content in the chosen format.
    Used in preview only. Content should already be citation-stripped.
    """
    if not content:
        return "<p style='color:#888;font-style:italic;'>No content.</p>"

    if format_choice == "Narrative":
        # Wrap in <p>, preserving line breaks as <br>
        escaped = content.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        paragraphs = escaped.split("\n\n")
        parts = []
        for para in paragraphs:
            if para.strip():
                parts.append(f"<p style='margin:0 0 10px 0;line-height:1.65;'>{para.replace(chr(10), '<br>')}</p>")
        return "\n".join(parts) if parts else f"<p>{escaped}</p>"

    elif format_choice == "Bullet list":
        lines = content.split("\n")
        html_parts = []
        li_items = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("•") or stripped.startswith("-"):
                # Remove the bullet marker
                item_text = stripped.lstrip("•-").strip()
                li_items.append(f"<li style='margin-bottom:4px;'>{item_text}</li>")
            else:
                if li_items:
                    html_parts.append(
                        f"<ul style='margin:0 0 10px 0;padding-left:20px;"
                        f"color:#222;line-height:1.65;'>{''.join(li_items)}</ul>"
                    )
                    li_items = []
                if stripped:
                    html_parts.append(
                        f"<p style='margin:0 0 8px 0;line-height:1.65;'>{stripped}</p>"
                    )
        if li_items:
            html_parts.append(
                f"<ul style='margin:0 0 10px 0;padding-left:20px;"
                f"color:#222;line-height:1.65;'>{''.join(li_items)}</ul>"
            )
        return "\n".join(html_parts) if html_parts else f"<p>{content}</p>"

    elif format_choice == "Table":
        lines = [l for l in content.split("\n") if l.strip()]
        table_lines = [l for l in lines if "|" in l]
        if table_lines:
            rows_html = []
            for i, line in enumerate(table_lines):
                if all(c in "-|+ " for c in line):
                    continue  # separator row
                cells = [c.strip() for c in line.strip().strip("|").split("|")]
                if i == 0:
                    cell_tag = "th"
                    cell_style = (
                        "padding:6px 10px;text-align:left;"
                        f"background:{_GOVRISK_GREEN};color:white;font-weight:600;"
                    )
                else:
                    cell_tag = "td"
                    cell_style = (
                        "padding:6px 10px;text-align:left;"
                        "border-bottom:1px solid #e0e0e0;"
                    )
                row_cells = "".join(
                    f"<{cell_tag} style='{cell_style}'>{c}</{cell_tag}>" for c in cells
                )
                rows_html.append(f"<tr>{row_cells}</tr>")
            return (
                "<table style='border-collapse:collapse;width:100%;font-size:13px;"
                "margin-bottom:12px;'>"
                + "".join(rows_html)
                + "</table>"
            )
        # Fallback to narrative if no pipe-separated table
        return _format_section_preview(section_id, content, "Narrative")

    elif format_choice == "Project cards":
        blocks = content.split("\n\n")
        cards = []
        for block in blocks:
            if block.strip():
                escaped = block.strip().replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                cards.append(
                    f"<div style='border:1px solid #ddd;border-left:4px solid {_GOVRISK_GREEN};"
                    f"border-radius:4px;padding:12px 14px;margin-bottom:10px;"
                    f"font-size:13px;line-height:1.65;'>"
                    f"{escaped.replace(chr(10), '<br>')}</div>"
                )
        return "\n".join(cards) if cards else f"<p>{content}</p>"

    return f"<p>{content}</p>"


# ---------------------------------------------------------------------------
# 3. _build_preview_html
# ---------------------------------------------------------------------------

def _build_preview_html(sections: list, tor_data: dict) -> str:
    """
    Build and return a full HTML document string for preview.
    No citations. No [EVIDENCE NEEDED] tags. GovRisk-branded styling.
    """
    title = tor_data.get("title", "Capability Statement")
    funder = tor_data.get("funder", "")
    date_str = datetime.now().strftime("%B %Y")

    funder_line = f"{funder} · " if funder else ""

    sections_html = ""
    for section in sections:
        display_name = section.get("display_name", "")
        content = _strip_citations(section.get("content", ""))
        fmt = section.get("format", "Narrative")
        section_id = section.get("section_id", "")
        content_html = _format_section_preview(section_id, content, fmt)
        sections_html += f"""
        <div style="margin-bottom:28px;">
            <h2 style="font-family:Calibri,sans-serif;font-size:11px;font-weight:700;
                letter-spacing:0.12em;text-transform:uppercase;color:{_GOVRISK_GREEN};
                margin:0 0 10px 0;border-bottom:1px solid #e8f4f0;padding-bottom:6px;">
                {display_name}
            </h2>
            <div style="font-family:Calibri,sans-serif;font-size:13px;
                color:#222;line-height:1.7;">
                {content_html}
            </div>
        </div>
        """

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
  body {{
    font-family: Calibri, 'Segoe UI', Arial, sans-serif;
    background: white;
    margin: 0;
    padding: 24px 16px;
    color: #222;
  }}
  .container {{
    max-width: 700px;
    margin: 0 auto;
    background: white;
  }}
  ul {{ padding-left: 20px; }}
  li {{ margin-bottom: 4px; }}
  p {{ margin: 0 0 10px 0; }}
</style>
</head>
<body>
<div class="container">
  <!-- Header -->
  <div style="margin-bottom:20px;">
    <div style="font-family:Calibri,sans-serif;font-size:10px;font-weight:700;
        letter-spacing:0.18em;text-transform:uppercase;color:{_GOVRISK_GREEN};
        margin-bottom:6px;">GovRisk</div>
    <h1 style="font-family:Calibri,sans-serif;font-size:20px;font-weight:700;
        color:#1a1a1a;margin:0 0 4px 0;">{title}</h1>
    <div style="font-size:12px;color:#666;">{funder_line}{date_str}</div>
  </div>
  <hr style="border:none;border-top:2px solid {_GOVRISK_GREEN};margin-bottom:24px;">

  <!-- Sections -->
  {sections_html}

  <!-- Footer -->
  <hr style="border:none;border-top:1px solid #ddd;margin-top:32px;">
  <div style="font-size:10px;color:#aaa;text-align:center;padding:10px 0;">
    GovRisk &middot; govrisk.org &middot; Confidential
  </div>
</div>
</body>
</html>"""
    return html


# ---------------------------------------------------------------------------
# Helper: content to string
# ---------------------------------------------------------------------------

def _content_to_str(content) -> str:
    """Convert section content to string (handles list type for country_table)."""
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                parts.append(" | ".join(str(v) for v in item.values()))
            else:
                parts.append(str(item))
        return "\n".join(parts)
    if not isinstance(content, str):
        return ""
    return content


# ---------------------------------------------------------------------------
# 4. render_draft_review
# ---------------------------------------------------------------------------

def render_draft_review(generated_draft: dict, tor_data: dict) -> "dict | None":
    """
    Main function. Renders the draft review panel.
    Returns:
      - approved_draft dict when Mark confirms
      - regeneration dict when Mark requests a section regeneration
      - None otherwise
    """
    sections_dict = generated_draft.get("sections", {})

    if not sections_dict:
        st.warning("No sections generated. Please try generating again.")
        return None

    # Detect new draft (reset initialisation)
    import hashlib, json
    summary_hash = hashlib.md5(
        json.dumps(generated_draft.get("summary", {}), sort_keys=True).encode()
    ).hexdigest()
    if st.session_state.get("drp_draft_hash") != summary_hash:
        st.session_state["drp_draft_hash"] = summary_hash
        st.session_state["drp_initialised"] = False

    # A. Initialisation guard
    if not st.session_state.get("drp_initialised"):
        # Build section order
        order = [s for s in DEFAULT_SECTION_ORDER if s in sections_dict]
        for key in sections_dict:
            if key not in order:
                order.append(key)
        st.session_state["drp_section_order"] = order

        # Initialise per-section state (setdefault — do not overwrite existing content)
        for section_id in sections_dict:
            content = _content_to_str(sections_dict.get(section_id, ""))
            if f"drp_section_content_{section_id}" not in st.session_state:
                st.session_state[f"drp_section_content_{section_id}"] = content
            opts = SECTION_FORMAT_OPTIONS.get(section_id, _DEFAULT_FORMAT_OPTIONS)
            if f"drp_section_format_{section_id}" not in st.session_state:
                st.session_state[f"drp_section_format_{section_id}"] = opts[0]
            if f"drp_section_approved_{section_id}" not in st.session_state:
                st.session_state[f"drp_section_approved_{section_id}"] = False

        # Store country_table original for later restore
        original_ct = generated_draft.get("sections", {}).get("country_table")
        if original_ct is not None:
            st.session_state["drp_country_table_original"] = original_ct
            if isinstance(original_ct, list):
                ct_display = "\n".join([
                    f"{e.get('country','')}: {e.get('year_range','')} "
                    f"— {', '.join(e.get('named_identifiers', []))}"
                    for e in original_ct
                ])
                if "drp_section_content_country_table" not in st.session_state:
                    st.session_state["drp_section_content_country_table"] = ct_display
            else:
                if "drp_section_content_country_table" not in st.session_state:
                    st.session_state["drp_section_content_country_table"] = str(original_ct or "")

        st.session_state["drp_active_tab"] = "editor"
        st.session_state["drp_citations_visible"] = True
        st.session_state["drp_confirmed"] = False
        st.session_state["drp_regen_request"] = None
        st.session_state["drp_initialised"] = True

    section_order = st.session_state["drp_section_order"]

    # B. Tab bar
    _tab_editor_style = (
        "display:inline-block;padding:8px 18px;cursor:pointer;"
        "font-size:13px;font-weight:600;"
        "border-bottom:3px solid " + _GOVRISK_GREEN + ";color:" + _GOVRISK_GREEN + ";"
    )
    _tab_inactive_style = (
        "display:inline-block;padding:8px 18px;cursor:pointer;"
        "font-size:13px;color:#888;border-bottom:3px solid transparent;"
    )
    active_tab = st.session_state.get("drp_active_tab", "editor")

    tab_col1, tab_col2, _ = st.columns([1, 1, 4])
    with tab_col1:
        editor_style = _tab_editor_style if active_tab == "editor" else _tab_inactive_style
        st.markdown(
            f'<span style="{editor_style}">📋 Edit sections</span>',
            unsafe_allow_html=True,
        )
        if st.button("Edit sections", key="drp_tab_editor_btn"):
            st.session_state["drp_active_tab"] = "editor"
            st.rerun()
    with tab_col2:
        preview_style = _tab_editor_style if active_tab == "preview" else _tab_inactive_style
        st.markdown(
            f'<span style="{preview_style}">👁 Preview document</span>',
            unsafe_allow_html=True,
        )
        if st.button("Preview document", key="drp_tab_preview_btn"):
            st.session_state["drp_active_tab"] = "preview"
            st.rerun()

    # -----------------------------------------------------------------------
    # C. EDITOR TAB
    # -----------------------------------------------------------------------
    if active_tab == "editor":

        # C1. Top bar
        total = len(section_order)
        approved_count = sum(
            1 for sid in section_order
            if st.session_state.get(f"drp_section_approved_{sid}", False)
        )
        top_left, top_right = st.columns([3, 2])
        with top_left:
            st.markdown("### Step 3.5 — Review and edit draft")
        with top_right:
            cit_val = st.toggle(
                "Show citations",
                value=st.session_state.get("drp_citations_visible", True),
                key="drp_cit_toggle",
            )
            st.session_state["drp_citations_visible"] = cit_val
            st.caption(f"{approved_count} / {total} approved")

        # C2. Drag-and-drop ordering
        display_names_in_order = [
            DISPLAY_NAMES.get(sid, sid) for sid in section_order
        ]
        name_to_id = {DISPLAY_NAMES.get(sid, sid): sid for sid in section_order}

        if _SORTABLES_AVAILABLE:
            new_order_names = sort_items(
                display_names_in_order,
                direction="vertical",
                key="drp_sorter",
            )
            new_order = [name_to_id.get(name, name) for name in new_order_names]
            if new_order != section_order:
                st.session_state["drp_section_order"] = new_order
                section_order = new_order
        else:
            # Fallback: up/down buttons
            for i, sid in enumerate(section_order):
                up_col, dn_col, lbl_col = st.columns([1, 1, 8])
                with lbl_col:
                    st.markdown(DISPLAY_NAMES.get(sid, sid))
                with up_col:
                    if i > 0 and st.button("↑", key=f"drp_up_{sid}", help="Move up"):
                        section_order[i], section_order[i - 1] = section_order[i - 1], section_order[i]
                        st.session_state["drp_section_order"] = section_order
                        st.rerun()
                with dn_col:
                    if i < len(section_order) - 1 and st.button("↓", key=f"drp_dn_{sid}", help="Move down"):
                        section_order[i], section_order[i + 1] = section_order[i + 1], section_order[i]
                        st.session_state["drp_section_order"] = section_order
                        st.rerun()

        # C3. Section blocks
        for section_id in section_order:
            content_key = f"drp_section_content_{section_id}"
            format_key = f"drp_section_format_{section_id}"
            approved_key = f"drp_section_approved_{section_id}"

            current_content = st.session_state.get(content_key, "")
            current_format = st.session_state.get(format_key, "Narrative")
            is_approved = st.session_state.get(approved_key, False)

            display_name = DISPLAY_NAMES.get(section_id, section_id)
            format_options = SECTION_FORMAT_OPTIONS.get(section_id, _DEFAULT_FORMAT_OPTIONS)
            fmt_index = format_options.index(current_format) if current_format in format_options else 0

            # Section header row
            h1, h2, h3, h4 = st.columns([4, 2, 2, 1])
            with h1:
                st.markdown(f"**{display_name}**")
            with h2:
                new_fmt = st.selectbox(
                    label="",
                    options=format_options,
                    index=fmt_index,
                    key=f"drp_fmt_{section_id}",
                    label_visibility="collapsed",
                )
                st.session_state[format_key] = new_fmt
            with h3:
                if is_approved:
                    st.markdown(
                        f'<span style="color:{_GOVRISK_GREEN};font-weight:600;'
                        f'font-size:12px;">✓ Approved</span>',
                        unsafe_allow_html=True,
                    )
                else:
                    if st.button("Approve", key=f"drp_approve_{section_id}"):
                        st.session_state[approved_key] = True
                        st.rerun()
            with h4:
                if st.button("Remove section", key=f"drp_remove_{section_id}"):
                    st.session_state["drp_section_order"].remove(section_id)
                    st.rerun()

            # Expandable content area
            with st.expander(f"Content — {display_name}", expanded=False):
                show_citations = st.session_state.get("drp_citations_visible", True)
                display_content = current_content if show_citations else _strip_citations(current_content)
                st.markdown(display_content, unsafe_allow_html=True)

                # Edit text area
                edited = st.text_area(
                    "Edit content",
                    value=current_content,
                    key=f"drp_edit_{section_id}",
                    height=150,
                    label_visibility="collapsed",
                )

                # Save + regenerate row
                save_col, fb_col, regen_col = st.columns([2, 4, 2])
                with save_col:
                    if st.button("Save edits", key=f"drp_save_{section_id}"):
                        st.session_state[content_key] = edited
                        st.session_state[approved_key] = False
                        st.rerun()
                with fb_col:
                    fb_text = st.text_input(
                        "Feedback",
                        placeholder="Tell Claude how to adjust...",
                        key=f"drp_fb_{section_id}",
                        label_visibility="collapsed",
                    )
                with regen_col:
                    if st.button("Regenerate", key=f"drp_regen_{section_id}", type="secondary"):
                        regen_request = {
                            "action": "regenerate_section",
                            "section_id": section_id,
                            "feedback": fb_text,
                            "current_content": current_content,
                            "section_order": list(section_order),
                            "section_formats": {
                                sid: st.session_state.get(f"drp_section_format_{sid}", "Narrative")
                                for sid in section_order
                            },
                            "section_approved": {
                                sid: st.session_state.get(f"drp_section_approved_{sid}", False)
                                for sid in section_order
                            },
                        }
                        st.session_state["drp_regen_request"] = regen_request
                        return regen_request

        # C4. Bottom action row
        st.markdown("---")
        bot_left, bot_right = st.columns([3, 2])
        with bot_left:
            if st.button("Preview document →", type="primary", key="drp_goto_preview"):
                st.session_state["drp_active_tab"] = "preview"
                st.rerun()
        with bot_right:
            st.caption(f"{approved_count} / {total} sections approved")

    # -----------------------------------------------------------------------
    # D. PREVIEW TAB
    # -----------------------------------------------------------------------
    else:
        # D1. Build sections list for preview
        preview_sections = []
        for sid in section_order:
            preview_sections.append({
                "section_id": sid,
                "display_name": DISPLAY_NAMES.get(sid, sid),
                "content": _strip_citations(st.session_state.get(f"drp_section_content_{sid}", "")),
                "format": st.session_state.get(f"drp_section_format_{sid}", "Narrative"),
            })

        # D2. Render preview
        preview_html = _build_preview_html(preview_sections, tor_data)
        st.components.v1.html(preview_html, height=700, scrolling=True)

        # D3. Action buttons
        st.markdown("")
        d_col1, d_col2, d_col3 = st.columns(3)
        with d_col1:
            if st.button(
                "✅ Confirm and generate .docx",
                type="primary",
                key="drp_confirm",
            ):
                st.session_state["drp_confirmed"] = True

        with d_col2:
            # Offer prompt .txt download if available from discovery panel
            prompt_txt = st.session_state.get("dp_prompt_txt", "")
            if prompt_txt:
                st.download_button(
                    label="📄 Download prompt .txt",
                    data=prompt_txt,
                    file_name=f"GovRisk_Prompt_{datetime.now().strftime('%Y-%m-%d')}.txt",
                    mime="text/plain",
                    key="drp_prompt_download",
                )

        with d_col3:
            if st.button("← Back to editor", key="drp_back_to_editor"):
                st.session_state["drp_active_tab"] = "editor"
                st.rerun()

        # D4. Return approved_draft if confirmed
        if st.session_state.get("drp_confirmed"):
            return {
                "sections": {
                    sid: st.session_state.get(f"drp_section_content_{sid}", "")
                    for sid in section_order
                },
                "section_order": list(section_order),
                "section_formats": {
                    sid: st.session_state.get(f"drp_section_format_{sid}", "Narrative")
                    for sid in section_order
                },
                "citations_in_output": False,
                "interpretation_log": generated_draft.get("interpretation_log", []),
                "summary": generated_draft.get("summary", {}),
            }

    return None
