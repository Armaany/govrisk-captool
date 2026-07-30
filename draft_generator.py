"""
draft_generator.py — Task 5

Generates a structured capability statement draft using the Claude API,
given a TorData dict and a list of retrieved capability chunks.
"""
import json
import logging
import re

import anthropic

from config import MODEL_NAME, ANTHROPIC_API_KEY


def _strip_markdown_fences(text: str) -> str:
    text = text.strip()
    # Find the first { and last } and extract only the JSON object
    start = text.find('{')
    end = text.rfind('}')
    if start != -1 and end != -1 and end > start:
        return text[start:end + 1]
    return text

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Custom exception (available for callers; never raised internally)
# ---------------------------------------------------------------------------

class GenerationError(Exception):
    """Available for callers who want to surface an error-state dict as an exception."""
    pass


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ALL_SECTIONS = [
    "opening_statement",
    "institutional_overview",
    "country_table",
    "geographic_experience",
    "thematic_areas",
    "selected_project_experience",
    "alignment_with_tor",
]

# JSON schema string for the user prompt (from SPEC.md §4.4)
_JSON_SCHEMA = """{
    "sections": {
        "opening_statement": "string with [REF:filename:page_N] tags",
        "institutional_overview": "string with [REF:filename:page_N] tags",
        "country_table": [
            {
                "country": "string",
                "project_count": "integer",
                "year_range": "string",
                "named_identifiers": ["list of strings"],
                "donors": ["list of strings"]
            }
        ],
        "geographic_experience": "string with [REF:filename:page_N] tags",
        "thematic_areas": "string with [REF:filename:page_N] tags",
        "selected_project_experience": "string with [REF:filename:page_N] tags",
        "alignment_with_tor": "string with [REF:filename:page_N] tags"
    },
    "interpretation_log": [
        {
            "section": "string",
            "inference_made": "string",
            "source_used": "string",
            "gap_flagged": "string or null",
            "confidence": "HIGH | MEDIUM | LOW"
        }
    ],
    "summary": {
        "sections_generated": "integer",
        "projects_referenced": "integer",
        "countries_covered": "integer",
        "documents_used": "integer",
        "overall_confidence": "HIGH | MEDIUM | LOW"
    }
}"""

# ---------------------------------------------------------------------------
# System prompt (from SPEC.md §6.2)
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = (
    "You are a proposal writer for GovRisk, a consulting firm specializing in\n"
    "AML/CFT, anti-corruption, justice reform, illicit financial flows, and human\n"
    "trafficking prevention in Latin America and the Caribbean.\n"
    "You generate capability statements from provided source documents only.\n"
    "\n"
    "STRICT RULES — these are non-negotiable:\n"
    "Use ONLY content from the provided source chunks. Never invent.\n"
    "Every project cited must include: name, year, country, donor, named identifier.\n"
    "Most recent experience first. Ongoing projects marked (ongoing).\n"
    "Impact language: institutional adoption and operational change only.\n"
    "Never use: \"strengthened coordination\", \"improved capacity\", or similar generic phrases.\n"
    "Bold: section headings and subheadings ONLY. Nothing else.\n"
    "Each country gets its own paragraph with project count, year range, named projects.\n"
    "Completed projects = past tense. Ongoing = present tense + (ongoing).\n"
    "Every paragraph must end with at least one inline citation: [REF:filename:page_N]\n"
    "Never fill gaps silently. Flag all gaps in the Interpretation Log.\n"
    "GovRisk role: significant subcontractor, leading components, key team members."
)

# ---------------------------------------------------------------------------
# User prompt template
# ---------------------------------------------------------------------------

_USER_PROMPT_TEMPLATE = (
    "Generate a capability statement for the following opportunity.\n"
    "\n"
    "TERMS OF REFERENCE SUMMARY:\n"
    "{tor_summary}\n"
    "\n"
    "SECTIONS TO INCLUDE:\n"
    "{sections_list}\n"
    "\n"
    "OUTPUT LANGUAGE: {language}\n"
    "\n"
    "SOURCE CAPABILITY CHUNKS:\n"
    "{formatted_chunks}\n"
    "\n"
    "Generate the capability statement following all system rules.\n"
    "After the full draft, append an INTERPRETATION LOG in this exact format:\n"
    "\n"
    "INTERPRETATION LOG\n"
    "Section: [section name]\n"
    "Inference: [what inference was made and why]\n"
    "Source: [source file and page]\n"
    "Gap: [gap description or \"None\"]\n"
    "Confidence: HIGH | MEDIUM | LOW\n"
    "\n"
    "Repeat one block per section.\n"
    "\n"
    "Return the full output as JSON matching this structure:\n"
    "{json_schema}"
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_context_block(retrieved_chunks: list) -> str:
    """
    Task 5.2: Build a context string from at most 20 chunks.
    Each chunk formatted as: [Source: {source_file} p.{page_number}]\n{text}
    Chunks separated by \n\n---\n\n
    """
    capped = retrieved_chunks[:20]
    if not capped:
        return "No capability library content available."

    parts = []
    for chunk in capped:
        source_file = chunk.get("source_file", "unknown")
        page_number = chunk.get("page_number", 0)
        text = chunk.get("text", "")
        formatted = f"[Source: {source_file} p.{page_number}]\n{text}"
        parts.append(formatted)

    return "\n\n---\n\n".join(parts)


def _build_tor_summary(tor_data: dict) -> str:
    """Build the TOR summary string for the user prompt."""
    return (
        f"Title: {tor_data.get('title', '')}\n"
        f"Funder: {tor_data.get('funder', '')}\n"
        f"Geography: {', '.join(tor_data.get('geography', []))}\n"
        f"Thematic Areas: {', '.join(tor_data.get('thematic_areas', []))}\n"
        f"Key Requirements: {chr(10).join('- ' + r for r in tor_data.get('key_requirements', []))}"
    )


def _error_state(message: str) -> dict:
    """Return a well-formed error-state dict."""
    return {
        "sections": {},
        "interpretation_log": [],
        "summary": {
            "sections_generated": 0,
            "projects_referenced": 0,
            "countries_covered": 0,
            "documents_used": 0,
            "overall_confidence": "LOW",
        },
        "error": message,
    }


def _call_claude(client: anthropic.Anthropic, system: str, user_prompt: str) -> str:
    """Make a single Claude API call and return the raw text response."""
    response = client.messages.create(
        model=MODEL_NAME,
        max_tokens=16000,
        system=system,
        messages=[{"role": "user", "content": user_prompt}],
    )
    return response.content[0].text


def _derive_confidence(interpretation_log: list) -> str:
    """
    Task 5.7: Derive overall confidence from interpretation log entries.
    Returns HIGH if all entries are HIGH, LOW if any are LOW, else MEDIUM.
    """
    if not interpretation_log:
        return "LOW"
    confidences = [entry.get("confidence", "LOW") for entry in interpretation_log]
    if all(c == "HIGH" for c in confidences):
        return "HIGH"
    if any(c == "LOW" for c in confidences):
        return "LOW"
    return "MEDIUM"


def _validate_log_entry(entry: dict) -> dict:
    """
    Task 5.6: Ensure all required keys exist in an interpretation log entry.
    """
    return {
        "section": entry.get("section", ""),
        "inference_made": entry.get("inference_made", ""),
        "source_used": entry.get("source_used", ""),
        "gap_flagged": entry.get("gap_flagged", None),
        "confidence": entry.get("confidence", "LOW"),
    }


def _validate_and_normalise(data: dict, sections_to_include: list, retrieved_chunks: list) -> dict:
    """
    Task 5.5 + 5.6 + 5.7: Validate and normalise the parsed GeneratedDraft dict.
    """
    # Ensure top-level keys exist
    if "sections" not in data or not isinstance(data["sections"], dict):
        data["sections"] = {}
    if "interpretation_log" not in data or not isinstance(data["interpretation_log"], list):
        data["interpretation_log"] = []
    if "summary" not in data or not isinstance(data["summary"], dict):
        data["summary"] = {
            "sections_generated": 0,
            "projects_referenced": 0,
            "countries_covered": 0,
            "documents_used": 0,
            "overall_confidence": "LOW",
        }

    sections = data["sections"]

    # Ensure all required section keys are present
    required_sections = sections_to_include if sections_to_include is not None else ALL_SECTIONS
    for section_key in required_sections:
        if section_key not in sections:
            sections[section_key] = ""

    # country_table must be a list
    if "country_table" not in sections or not isinstance(sections.get("country_table"), list):
        sections["country_table"] = []

    # Validate each interpretation log entry
    data["interpretation_log"] = [
        _validate_log_entry(entry) for entry in data["interpretation_log"]
    ]

    # Build summary from parsed data (Task 5.7)
    country_table = sections.get("country_table", [])
    interpretation_log = data["interpretation_log"]

    # Collect all text from string sections for REF counting
    full_text_parts = []
    for key, val in sections.items():
        if isinstance(val, str):
            full_text_parts.append(val)
    full_text = " ".join(full_text_parts)

    data["summary"] = {
        "sections_generated": len([s for s in sections.values() if s and s != []]),
        "projects_referenced": len(set(re.findall(r'\[REF:([^:]+):', full_text))),
        "countries_covered": len(country_table),
        "documents_used": len(set(c.get("source_file", "") for c in retrieved_chunks[:20])),
        "overall_confidence": _derive_confidence(interpretation_log),
    }

    return data


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def generate_draft(
    tor_data: dict,
    retrieved_chunks: list,
    sections_to_include: list = None,
    output_language: str = "English",
    feedback: str = "",
    single_section: str = None,
) -> dict:
    """
    Generate a capability statement draft using the Claude API.

    Args:
        tor_data:           TorData dict from tor_extractor.
        retrieved_chunks:   List of chunk dicts from capability_retriever.
        sections_to_include: List of section names to include; None = all sections.
        output_language:    "English" | "Spanish" | "Match ToR"
        feedback:           Mark's instruction for how to adjust (optional).
        single_section:     If set, regenerate only this one section_id.

    Returns:
        GeneratedDraft dict, or error-state dict on failure.
        Never raises exceptions.
    """
    # Cap chunks to MAX_GENERATION_CHUNKS
    from config import MAX_GENERATION_CHUNKS
    if len(retrieved_chunks) > MAX_GENERATION_CHUNKS:
        retrieved_chunks = sorted(
            retrieved_chunks,
            key=lambda c: c.get("relevance_score", 0),
            reverse=True,
        )[:MAX_GENERATION_CHUNKS]

    # Handle single_section mode
    if single_section:
        if single_section not in ALL_SECTIONS:
            return _error_state(f"Unknown section: {single_section}")
        sections_to_include = [single_section]

    # Build prompt components
    try:
        tor_summary = _build_tor_summary(tor_data)
        sections_list = "\n".join(
            f"- {s}" for s in (sections_to_include or ALL_SECTIONS)
        )
        formatted_chunks = _build_context_block(retrieved_chunks)

        # Feedback instruction — prepended when Mark provides guidance
        feedback_block = ""
        if feedback and feedback.strip():
            feedback_block = (
                f"\n\nMARK'S INSTRUCTION FOR THIS SECTION:\n{feedback.strip()}\n"
                "Apply this instruction when writing the section below.\n"
            )

        user_prompt = _USER_PROMPT_TEMPLATE.format(
            tor_summary=tor_summary,
            sections_list=sections_list,
            language=output_language,
            formatted_chunks=feedback_block + formatted_chunks,
            json_schema=_JSON_SCHEMA,
        )
    except Exception as exc:
        return _error_state(f"Failed to build prompt: {exc}")

    # Initialise Claude client
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    except Exception as exc:
        return _error_state(f"Failed to initialise Anthropic client: {exc}")

    # First API call attempt
    try:
        raw_text = _call_claude(client, SYSTEM_PROMPT, user_prompt)
        print('RAW_LEN:', len(raw_text), 'LAST100:', repr(raw_text[-100:]))
    except Exception as exc:
        return _error_state(f"Claude API call failed: {exc}")

    # Task 5.4: JSON parsing with one retry
    try:
        data = json.loads(_strip_markdown_fences(raw_text))
    except json.JSONDecodeError:
        # Retry once
        try:
            raw_text = _call_claude(client, SYSTEM_PROMPT, user_prompt)
            print('RAW_LEN:', len(raw_text), 'LAST100:', repr(raw_text[-100:]))
        except Exception as exc:
            return _error_state(f"Claude API call failed on retry: {exc}")

        try:
            data = json.loads(_strip_markdown_fences(raw_text))
        except json.JSONDecodeError:
            return _error_state(
                "Claude API returned invalid JSON after retry. Please try again."
            )

    # Task 5.5 + 5.6 + 5.7: Validate and normalise
    try:
        data = _validate_and_normalise(data, sections_to_include, retrieved_chunks)
    except Exception as exc:
        return _error_state(f"Failed to validate generated draft: {exc}")

    return data
