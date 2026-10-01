"""Grounded free-form evidence search and deterministic catalogue export.

This module is deliberately additive: the established ToR-to-capability-
statement flow remains unchanged. A user-authored request is used only to
retrieve indexed chunks. The catalogue is rendered from exact excerpts that
are verified against those chunks; no LLM is asked to invent or rewrite facts.
"""

from __future__ import annotations

import io
import os
import re
from collections import OrderedDict
from pathlib import PurePosixPath
from typing import Iterable

from docx import Document
from docx.enum.table import WD_ALIGN_VERTICAL, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

from capability_retriever import retrieve_query_chunks


DEFAULT_TOP_K = 50
DEFAULT_EXCERPTS_PER_DOCUMENT = 3
DEFAULT_EXCERPT_CHAR_LIMIT = 900

_STOP_WORDS = {
    "about", "after", "against", "also", "among", "and", "are", "all",
    "been", "being", "build", "capabilities", "demonstrating", "experience",
    "find", "for", "from", "have", "include", "into", "more", "most",
    "of", "our", "past", "project", "projects", "provide", "relevant",
    "than", "that", "the", "their", "this", "those", "through", "to",
    "using", "want", "were", "what", "where", "which", "with", "within",
}


def _normalise_whitespace(value: str) -> str:
    return " ".join(str(value or "").split())


def _query_terms(query: str) -> set[str]:
    words = re.findall(r"[\w'-]+", str(query or "").casefold(), flags=re.UNICODE)
    return {word for word in words if len(word) >= 3 and word not in _STOP_WORDS}


def _sentences(text: str) -> list[str]:
    clean = _normalise_whitespace(text)
    if not clean:
        return []
    parts = re.split(r"(?<=[.!?])\s+", clean)
    return [part.strip() for part in parts if part.strip()]


def select_grounded_excerpt(text: str, query: str, max_chars: int = DEFAULT_EXCERPT_CHAR_LIMIT) -> str:
    """Select a query-relevant excerpt that remains an exact text substring.

    The function never paraphrases. It chooses the highest-scoring sentence and
    then adds adjacent sentences while the configured character limit permits.
    If no query term is present, it returns the beginning of the chunk, ending
    only at a sentence boundary when possible.
    """
    clean = _normalise_whitespace(text)
    if not clean or max_chars < 1:
        return ""

    sentences = _sentences(clean)
    if not sentences:
        return clean[:max_chars]

    terms = _query_terms(query)
    scores = []
    for index, sentence in enumerate(sentences):
        folded = sentence.casefold()
        score = sum(1 for term in terms if term in folded)
        scores.append((score, -index, index))
    best_index = max(scores)[2] if scores else 0

    chosen = [sentences[best_index]]
    left = best_index - 1
    right = best_index + 1
    while True:
        added = False
        if right < len(sentences):
            candidate = " ".join(chosen + [sentences[right]])
            if len(candidate) <= max_chars:
                chosen.append(sentences[right])
                right += 1
                added = True
        if left >= 0:
            candidate = " ".join([sentences[left]] + chosen)
            if len(candidate) <= max_chars:
                chosen.insert(0, sentences[left])
                left -= 1
                added = True
        if not added:
            break

    excerpt = " ".join(chosen)
    if len(excerpt) <= max_chars:
        return excerpt

    # One unusually long sentence. Preserve exact characters and disclose the
    # truncation with an ellipsis outside the verified quote text in the UI.
    return excerpt[:max_chars].rstrip()


def quote_occurs_in_chunk(quote: str, chunk_text: str) -> bool:
    """Return True when a normalised quote occurs in the cited chunk."""
    normalised_quote = _normalise_whitespace(quote)
    normalised_chunk = _normalise_whitespace(chunk_text)
    return bool(normalised_quote) and normalised_quote in normalised_chunk


def _safe_source_name(value: str) -> str:
    value = str(value or "").replace("\\", "/").strip()
    name = PurePosixPath(value).name.strip()
    return name or "Unknown source"


def _source_locator(source_file: str, page_number) -> dict:
    try:
        number = int(page_number)
    except (TypeError, ValueError):
        number = 0

    extension = os.path.splitext(str(source_file or ""))[1].lower()
    if extension == ".pdf" and number > 0:
        return {
            "locator_type": "verified_pdf_page",
            "locator_value": number,
            "locator_label": f"PDF page {number}",
        }
    if extension == ".docx" and number > 0:
        return {
            "locator_type": "approximate_docx_segment",
            "locator_value": number,
            "locator_label": f"DOCX extraction segment {number} (not a verified page)",
        }
    return {
        "locator_type": "document_chunk",
        "locator_value": None,
        "locator_label": "Document chunk",
    }


def build_evidence_packets(
    retrieved_chunks: Iterable[dict],
    query: str,
    excerpts_per_document: int = DEFAULT_EXCERPTS_PER_DOCUMENT,
    excerpt_char_limit: int = DEFAULT_EXCERPT_CHAR_LIMIT,
) -> list[dict]:
    """Build verified, source-groupable evidence packets from retrieved chunks."""
    if excerpts_per_document < 1:
        return []

    per_source: dict[str, int] = {}
    seen_chunk_ids: set[str] = set()
    packets = []

    for chunk in retrieved_chunks or []:
        if not isinstance(chunk, dict):
            continue
        chunk_id = str(chunk.get("chunk_id") or "").strip()
        source_file = str(chunk.get("source_file") or "").strip()
        text = str(chunk.get("text") or "")
        if not chunk_id or not source_file or not text.strip() or chunk_id in seen_chunk_ids:
            continue

        source_key = source_file.replace("\\", "/").casefold()
        if per_source.get(source_key, 0) >= excerpts_per_document:
            continue

        excerpt = select_grounded_excerpt(text, query, max_chars=excerpt_char_limit)
        verified = quote_occurs_in_chunk(excerpt, text)
        locator = _source_locator(source_file, chunk.get("page_number"))
        try:
            score = float(chunk.get("relevance_score", 0.0))
        except (TypeError, ValueError):
            score = 0.0

        packet = {
            "chunk_id": chunk_id,
            "source_file": source_file,
            "source_name": _safe_source_name(source_file),
            "quote": excerpt,
            "relevance_score": max(0.0, min(score, 1.0)),
            "verification_status": "verified" if verified else "needs_review",
            **locator,
        }
        packets.append(packet)
        seen_chunk_ids.add(chunk_id)
        per_source[source_key] = per_source.get(source_key, 0) + 1

    return packets


def group_evidence_by_source(packets: Iterable[dict]) -> list[dict]:
    """Group verified packets by source while preserving retrieval order."""
    grouped: OrderedDict[str, dict] = OrderedDict()
    for packet in packets or []:
        if not isinstance(packet, dict):
            continue
        source_file = str(packet.get("source_file") or "")
        group = grouped.setdefault(
            source_file,
            {
                "source_file": source_file,
                "source_name": packet.get("source_name") or _safe_source_name(source_file),
                "evidence": [],
                "best_relevance_score": 0.0,
            },
        )
        group["evidence"].append(packet)
        group["best_relevance_score"] = max(
            group["best_relevance_score"], packet.get("relevance_score", 0.0)
        )
    return list(grouped.values())


def search_evidence(
    query: str,
    filters: dict = None,
    top_k: int = DEFAULT_TOP_K,
    excerpts_per_document: int = DEFAULT_EXCERPTS_PER_DOCUMENT,
) -> dict:
    """Search the indexed library and return source-grounded evidence groups."""
    clean_query = _normalise_whitespace(query)
    if not clean_query:
        return {
            "query": "",
            "retrieved_chunks": 0,
            "documents_found": 0,
            "verified_evidence": 0,
            "needs_review": 0,
            "groups": [],
            "library_unavailable": False,
            "validation_error": "Enter an evidence request before searching.",
        }

    retrieval = retrieve_query_chunks(clean_query, filters or {}, top_k=top_k)
    if retrieval.get("library_unavailable"):
        return {
            "query": clean_query,
            "retrieved_chunks": 0,
            "documents_found": 0,
            "verified_evidence": 0,
            "needs_review": 0,
            "groups": [],
            "library_unavailable": True,
            "library_error": retrieval.get("library_error", "Library search unavailable."),
        }

    chunks = retrieval.get("retrieved_chunks", [])
    packets = build_evidence_packets(
        chunks,
        clean_query,
        excerpts_per_document=excerpts_per_document,
    )
    groups = group_evidence_by_source(packets)
    verified = sum(p.get("verification_status") == "verified" for p in packets)
    needs_review = len(packets) - verified
    return {
        "query": clean_query,
        "retrieved_chunks": len(chunks),
        "documents_found": len(groups),
        "verified_evidence": verified,
        "needs_review": needs_review,
        "groups": groups,
        "library_unavailable": False,
    }


def _set_cell_shading(cell, fill: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = tc_pr.find(qn("w:shd"))
    if shd is None:
        shd = OxmlElement("w:shd")
        tc_pr.append(shd)
    shd.set(qn("w:fill"), fill)


def _set_repeat_table_header(row) -> None:
    tr_pr = row._tr.get_or_add_trPr()
    header = OxmlElement("w:tblHeader")
    header.set(qn("w:val"), "true")
    tr_pr.append(header)


def build_evidence_catalogue_docx(result: dict) -> bytes:
    """Render verified evidence into a deterministic DOCX byte string."""
    document = Document()
    section = document.sections[0]
    section.top_margin = Inches(0.65)
    section.bottom_margin = Inches(0.65)
    section.left_margin = Inches(0.72)
    section.right_margin = Inches(0.72)

    normal = document.styles["Normal"]
    normal.font.name = "Aptos"
    normal.font.size = Pt(9.5)
    normal._element.rPr.rFonts.set(qn("w:ascii"), "Aptos")
    normal._element.rPr.rFonts.set(qn("w:hAnsi"), "Aptos")

    title = document.add_heading("Evidence Search Catalogue", level=0)
    title.alignment = WD_ALIGN_PARAGRAPH.LEFT
    document.add_paragraph("Request: " + str(result.get("query") or ""))
    document.add_paragraph(
        "Documents found: {documents} | Verified evidence excerpts: {verified} | "
        "Needs review: {review}".format(
            documents=result.get("documents_found", 0),
            verified=result.get("verified_evidence", 0),
            review=result.get("needs_review", 0),
        )
    )
    note = document.add_paragraph()
    run = note.add_run(
        "This is a retrieval evidence catalogue, not a finished bid narrative. "
        "Every verified excerpt below occurs in its cited indexed chunk."
    )
    run.italic = True
    run.font.color.rgb = RGBColor(80, 80, 80)

    for group in result.get("groups", []) or []:
        document.add_heading(str(group.get("source_name") or "Unknown source"), level=1)
        table = document.add_table(rows=1, cols=4)
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        table.autofit = False
        widths = [0.75, 1.65, 3.72, 0.65]
        headers = ["Status", "Location", "Exact evidence excerpt", "Score"]
        _set_repeat_table_header(table.rows[0])
        for index, header_text in enumerate(headers):
            cell = table.rows[0].cells[index]
            cell.width = Inches(widths[index])
            cell.text = header_text
            cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
            _set_cell_shading(cell, "17365D")
            for header_run in cell.paragraphs[0].runs:
                header_run.bold = True
                header_run.font.color.rgb = RGBColor(255, 255, 255)
                header_run.font.size = Pt(8.2)

        for packet in group.get("evidence", []) or []:
            row = table.add_row()
            values = [
                "Verified" if packet.get("verification_status") == "verified" else "Review",
                packet.get("locator_label") or "Document chunk",
                packet.get("quote") or "",
                "{:.0%}".format(packet.get("relevance_score", 0.0)),
            ]
            for index, value in enumerate(values):
                cell = row.cells[index]
                cell.width = Inches(widths[index])
                cell.text = str(value)
                cell.vertical_alignment = WD_ALIGN_VERTICAL.TOP
                for body_run in cell.paragraphs[0].runs:
                    body_run.font.size = Pt(8.2)
            chunk_note = row.cells[2].add_paragraph()
            chunk_run = chunk_note.add_run("Chunk ID: " + str(packet.get("chunk_id") or ""))
            chunk_run.font.size = Pt(7.2)
            chunk_run.font.color.rgb = RGBColor(100, 100, 100)

    if not result.get("groups"):
        document.add_paragraph("No evidence was returned for this request.")

    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()

