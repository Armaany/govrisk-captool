"""
tor_extractor.py — Task 4

Extracts structured requirements from a Terms of Reference (ToR) document.
Supports .docx and .pdf file types.
"""
import io
import json
import logging
import re

import anthropic

from ai_request_cache import response_usage, safe_ai_error
from config import (
    ANTHROPIC_API_KEY,
    EXTRACTION_TIMEOUT_SECONDS,
    EXTRACTION_MAX_TOKENS,
    EXTRACTION_MODEL_NAME,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Custom exception (available for callers; never raised inside extract_tor)
# ---------------------------------------------------------------------------

class ExtractionError(Exception):
    """Raised by callers who want to surface an error-state dict as an exception."""
    pass


# ---------------------------------------------------------------------------
# Prompts (from SPEC.md §6.1)
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = (
    "You are analyzing a Terms of Reference or Notice of Funding Opportunity document. "
    "Extract structured information accurately.\n"
    "Use the document's own language — do not normalize, generalize, or substitute terms. "
    "If a term appears explicitly in the document, use it exactly as written.\n"
    "Return ONLY valid JSON. No markdown fences. No explanation."
)

USER_PROMPT_TEMPLATE = (
    "Analyze this document and return a JSON object with these fields:\n\n"
    '"title": The title or name of the opportunity. String.\n'
    '"funder": The organization or government body funding this. '
    "Use exact name as written. String.\n"
    '"geography": List of countries or regions that are the TARGET or PRIORITY of this '
    "opportunity. Use names exactly as written in the document. Do not include countries "
    "mentioned only as context or comparisons. List of strings.\n"
    '"thematic_areas": List of themes, technical areas, or subject areas that this '
    "opportunity is about. Use the document's own terms — do not translate or generalize "
    "(e.g. if the doc says \"Financial Intelligence\" keep that, do not replace with "
    "\"AML\"). List of strings.\n"
    '"key_requirements": List of what the responding organization must demonstrate, '
    "deliver, or possess. Each item is one requirement. List of strings. Maximum 8 items.\n"
    '"evaluation_criteria": List of how responses will be evaluated. List of strings. '
    "Maximum 5 items. Empty list if not stated.\n"
    '"language": "English" or "Spanish".\n'
    '"extraction_confidence": "HIGH" if you found all main fields clearly stated. '
    '"MEDIUM" if some fields required inference. '
    '"LOW" if significant information was missing or ambiguous.\n'
    '"source_map": For each item in geography, thematic_areas, funder, and '
    "key_requirements, return the supplied zero-based paragraph number and a short "
    "snippet (max 25 words) from that paragraph that contains the item. "
    'Structure: {{"geography": [{{"term": ..., "paragraph_index": ..., "snippet": ...}}], '
    '"thematic_areas": [...], "funder": [...], "key_requirements": [...]}} '
    "If the paragraph cannot be identified, use paragraph_index: -1 and snippet: \"\".\n\n"
    "The document paragraphs below are already numbered. Do not return or repeat the full "
    "paragraph list; use these exact zero-based numbers in source_map.\n\n"
    "NUMBERED DOCUMENT PARAGRAPHS:\n"
    "{tor_text}"
)

# Required keys and their default values
_REQUIRED_KEYS = {
    "title": "",
    "funder": "",
    "geography": [],
    "thematic_areas": [],
    "key_requirements": [],
    "evaluation_criteria": [],
    "language": "English",
    "source_file": "",
    "extraction_confidence": "LOW",
    "paragraphs": [],
    "source_map": {
        "geography": [],
        "thematic_areas": [],
        "funder": [],
        "key_requirements": [],
    },
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _error_state(filename: str, message: str) -> dict:
    """Return a well-formed error-state dict."""
    return {
        "title": "",
        "funder": "",
        "geography": [],
        "thematic_areas": [],
        "key_requirements": [],
        "evaluation_criteria": [],
        "language": "English",
        "source_file": filename,
        "extraction_confidence": "LOW",
        "error": message,
    }


def _extract_text_docx(file_bytes: bytes) -> str:
    """Extract all text from a .docx file, including table cells."""
    from docx import Document  # python-docx

    doc = Document(io.BytesIO(file_bytes))
    parts = []

    # Paragraphs
    for para in doc.paragraphs:
        if para.text.strip():
            parts.append(para.text)

    # Table cells
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                if cell.text.strip():
                    parts.append(cell.text)

    return "\n".join(parts)


def _extract_text_pdf(file_bytes: bytes) -> str:
    """Extract all text from a .pdf file using pdfplumber."""
    import pdfplumber

    parts = []
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                parts.append(text)

    return "\n".join(parts)


def _truncate_text(text: str) -> str:
    """
    Truncate text to at most 15,000 characters.
    Preserves first 12,000 + last 3,000 characters.
    """
    if len(text) > 15000:
        return text[:12000] + text[-3000:]
    return text


def _document_paragraphs(text: str) -> list[str]:
    """Create the stable paragraph list locally instead of paying to echo it."""
    paragraphs = []
    for block in re.split(r"\n\s*\n|\n", text):
        cleaned = re.sub(r"\s+", " ", block).strip()
        if len(cleaned) >= 20:
            paragraphs.append(cleaned)
        if len(paragraphs) >= 80:
            break
    if not paragraphs and text.strip():
        # Very short or line-heavy notices still need evidence to reach the
        # model.  The UI already warns about unusually short extraction.
        paragraphs.append(re.sub(r"\s+", " ", text).strip())
    return paragraphs


def _numbered_paragraph_text(paragraphs: list[str]) -> str:
    return "\n".join(f"[{index}] {paragraph}" for index, paragraph in enumerate(paragraphs))


def _call_claude(client: anthropic.Anthropic, user_prompt: str) -> tuple[str, dict]:
    """Make one Claude call and return text plus provider token usage."""
    response = client.messages.create(
        model=EXTRACTION_MODEL_NAME,
        max_tokens=EXTRACTION_MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )
    return response.content[0].text, response_usage(response, EXTRACTION_MODEL_NAME)


def _strip_markdown_fences(text: str) -> str:
    text = text.strip()
    # Find the first { and last } and extract only the JSON object
    start = text.find('{')
    end = text.rfind('}')
    if start != -1 and end != -1 and end > start:
        return text[start:end + 1]
    return text


def _fill_defaults(data: dict, filename: str) -> dict:
    """
    Ensure all required keys are present in data.
    Missing keys are filled with defaults. source_file is always overridden.
    """
    for key, default in _REQUIRED_KEYS.items():
        if key not in data:
            # Use a fresh copy for mutable defaults
            data[key] = default.copy() if isinstance(default, (dict, list)) else default
    # Ensure source_map has all four sub-keys
    sm = data.get("source_map", {})
    if not isinstance(sm, dict):
        sm = {}
    for sub_key in ("geography", "thematic_areas", "funder", "key_requirements"):
        if sub_key not in sm:
            sm[sub_key] = []
    data["source_map"] = sm
    # Always override source_file with the actual filename
    data["source_file"] = filename
    return data


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def extract_tor(file_bytes: bytes, filename: str) -> dict:
    """
    Extract structured requirements from a ToR document.
    Returns a tor_data dict matching the TorData schema.
    On error, returns an error-state dict with extraction_confidence="LOW".
    Never raises exceptions — all errors are returned as dicts.
    """
    # 4.2 / 4.7 — File type guard
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if ext not in ("docx", "pdf"):
        return _error_state(filename, "Unsupported file type. Please upload a .docx or .pdf file.")

    # 4.2 — Text extraction
    try:
        if ext == "docx":
            text = _extract_text_docx(file_bytes)
        else:
            text = _extract_text_pdf(file_bytes)
    except Exception as exc:
        return _error_state(filename, f"Failed to extract text from file: {exc}")

    # 4.3 — Text length guard
    if len(text) < 100:
        logger.warning(
            "Extracted text is very short (%d chars) for file '%s'. Proceeding anyway.",
            len(text),
            filename,
        )

    # 4.3 — Truncation
    text = _truncate_text(text)
    paragraphs = _document_paragraphs(text)

    # 4.4 / 4.5 — Claude API call
    user_prompt = USER_PROMPT_TEMPLATE.format(
        tor_text=_numbered_paragraph_text(paragraphs)
    )

    try:
        client = anthropic.Anthropic(
            api_key=ANTHROPIC_API_KEY,
            timeout=EXTRACTION_TIMEOUT_SECONDS,
            max_retries=0,
        )
    except Exception:
        return _error_state(filename, "Could not initialise the AI client.")

    # First attempt
    try:
        raw_text, usage = _call_claude(client, user_prompt)
    except Exception as exc:
        return _error_state(
            filename,
            safe_ai_error(exc, "ToR analysis", EXTRACTION_TIMEOUT_SECONDS),
        )

    # Parse once.  Invalid structured output must never cause an invisible
    # second paid request; the user may explicitly retry after seeing the error.
    try:
        data = json.loads(_strip_markdown_fences(raw_text))
    except json.JSONDecodeError:
        return _error_state(
            filename,
            "The AI response was incomplete or not structured correctly. "
            "No automatic retry was made.",
        )

    # 4.5 — Fill missing keys with defaults, override source_file
    data = _fill_defaults(data, filename)
    data["paragraphs"] = paragraphs
    data["_ai_usage"] = usage

    return data
