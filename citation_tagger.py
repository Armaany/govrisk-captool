"""citation_tagger.py — Task 6

Parses inline [REF:filename:page_N] tags from draft sections,
strips them from display text, and builds per-paragraph citation footnotes.
"""
import re
from typing import List, Dict

REF_PATTERN = re.compile(r'\[REF:([^:\]]+):page_(\d+)\]')
CLEAN_PATTERN = re.compile(r'\[REF:[^\]]+\]')


def format_citation(filename: str, page: int) -> str:
    """Return the formatted display string for a citation.

    Args:
        filename: Source document filename.
        page: Page number.

    Returns:
        String in the form "Source: {filename}, p.{page}".
    """
    return f"Source: {filename}, p.{page}"


def _process_paragraph(paragraph: str) -> dict | None:
    """Process a single paragraph: extract citations, clean text.

    Args:
        paragraph: Raw paragraph text, possibly containing [REF:...] tags.

    Returns:
        Dict with "text" (clean) and "citations" (deduplicated list), or
        None if the clean text is empty after stripping.
    """
    matches = REF_PATTERN.findall(paragraph)

    # Build deduplicated citations list, preserving first-occurrence order
    seen = set()
    citations = []
    for fname, page_str in matches:
        key = (fname, int(page_str))
        if key not in seen:
            seen.add(key)
            citations.append({"filename": fname, "page": int(page_str)})

    clean_text = CLEAN_PATTERN.sub('', paragraph).strip()

    if not clean_text:
        return None

    return {"text": clean_text, "citations": citations}


def tag_citations(draft_sections: dict) -> dict:
    """Process all text sections from a generated draft, stripping inline REF tags
    and building per-paragraph citation footnotes.

    Args:
        draft_sections: dict mapping section names to text strings (or lists for
                        country_table). Only string values are processed; lists are
                        passed through unchanged.

    Returns:
        citation_result dict matching schema §4.5:
        {
            "paragraphs": [
                {
                    "text": str,        # clean text, no [REF:...] tags
                    "citations": [      # list of citation dicts
                        {"filename": str, "page": int}
                    ]
                }
            ]
        }
    """
    if not isinstance(draft_sections, dict):
        return {"paragraphs": []}

    paragraphs = []

    for section_name, section_value in draft_sections.items():
        # Skip non-string values (e.g., country_table list)
        if not isinstance(section_value, str):
            continue
        if not section_value.strip():
            continue

        # Split by double newline to get paragraphs
        raw_paragraphs = section_value.split('\n\n')

        for raw_para in raw_paragraphs:
            result = _process_paragraph(raw_para)
            if result is not None:
                paragraphs.append(result)

    return {"paragraphs": paragraphs}
