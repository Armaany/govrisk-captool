"""
draft_generator.py — Task 5

Generates a structured capability statement draft using the Claude API,
given a TorData dict and a list of retrieved capability chunks.
"""
import json
import logging
import re

import anthropic

from ai_request_cache import response_usage, safe_ai_error
from config import (
    ANTHROPIC_API_KEY,
    GENERATION_TIMEOUT_SECONDS,
    GENERATION_MAX_TOKENS,
    GENERATION_MODEL_NAME,
)


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

# Native structured-output schema.  Claude constrains decoding to this schema,
# so a completed response cannot contain malformed JSON.  Summary counts remain
# application-owned and are derived after validation rather than model-authored.
_DRAFT_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "sections": {
            "type": "object",
            "properties": {
                "opening_statement": {"type": "string"},
                "institutional_overview": {"type": "string"},
                "country_table": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "country": {"type": "string"},
                            "project_count": {"type": "integer"},
                            "year_range": {"type": "string"},
                            "named_identifiers": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "donors": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                        },
                        "required": [
                            "country",
                            "project_count",
                            "year_range",
                            "named_identifiers",
                            "donors",
                        ],
                        "additionalProperties": False,
                    },
                },
                "geographic_experience": {"type": "string"},
                "thematic_areas": {"type": "string"},
                "selected_project_experience": {"type": "string"},
                "alignment_with_tor": {"type": "string"},
            },
            "required": ALL_SECTIONS,
            "additionalProperties": False,
        },
        "interpretation_log": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "section": {"type": "string"},
                    "inference_made": {"type": "string"},
                    "source_used": {"type": "string"},
                    "gap_flagged": {"type": ["string", "null"]},
                    "confidence": {
                        "type": "string",
                        "enum": ["HIGH", "MEDIUM", "LOW"],
                    },
                },
                "required": [
                    "section",
                    "inference_made",
                    "source_used",
                    "gap_flagged",
                    "confidence",
                ],
                "additionalProperties": False,
            },
        },
    },
    "required": ["sections", "interpretation_log"],
    "additionalProperties": False,
}

_JSON_SCHEMA = json.dumps(_DRAFT_OUTPUT_SCHEMA, indent=2)

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
    "Keep each narrative section under 350 words and selected_project_experience "
    "under 700 words. Keep interpretation-log entries concise.\n"
    "Populate only the requested sections; return an empty string (or [] for "
    "country_table) for excluded sections.\n"
    "Return only the structured JSON requested by the response schema:\n"
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


def _call_claude(
    client: anthropic.Anthropic,
    system: str,
    user_prompt: str,
) -> tuple[str, dict, str | None]:
    """Make one Claude call and return text, usage, and the stop reason."""
    response = client.messages.create(
        model=GENERATION_MODEL_NAME,
        max_tokens=GENERATION_MAX_TOKENS,
        system=system,
        messages=[{"role": "user", "content": user_prompt}],
        output_config={
            "format": {
                "type": "json_schema",
                "schema": _DRAFT_OUTPUT_SCHEMA,
            }
        },
    )
    raw_text = next(
        (
            block.text
            for block in response.content
            if isinstance(getattr(block, "text", None), str)
        ),
        "",
    )
    stop_reason = getattr(response, "stop_reason", None)
    if not isinstance(stop_reason, str):
        stop_reason = None
    return (
        raw_text,
        response_usage(response, GENERATION_MODEL_NAME),
        stop_reason,
    )


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
        client = anthropic.Anthropic(
            api_key=ANTHROPIC_API_KEY,
            timeout=GENERATION_TIMEOUT_SECONDS,
            max_retries=0,
        )
    except Exception:
        return _error_state("Could not initialise the AI client.")

    # First API call attempt
    try:
        raw_text, usage, stop_reason = _call_claude(
            client, SYSTEM_PROMPT, user_prompt
        )
    except Exception as exc:
        return _error_state(
            safe_ai_error(exc, "Draft generation", GENERATION_TIMEOUT_SECONDS)
        )

    if stop_reason in {"max_tokens", "model_context_window_exceeded"}:
        result = _error_state(
            "The AI response reached its output limit before the structured draft "
            "was complete. No automatic retry was made. Select fewer sections or "
            "evidence items before trying again."
        )
        result["_ai_usage"] = usage
        return result
    if stop_reason == "refusal":
        result = _error_state(
            "The AI provider declined this request. No automatic retry was made."
        )
        result["_ai_usage"] = usage
        return result

    # Parse once.  Invalid structured output must never cause an invisible
    # second paid request; the user may explicitly retry after seeing the error.
    try:
        data = json.loads(_strip_markdown_fences(raw_text))
    except json.JSONDecodeError:
        result = _error_state(
            "The AI completed the request but did not return the required "
            "structured draft. No automatic retry was made."
        )
        result["_ai_usage"] = usage
        return result

    # Task 5.5 + 5.6 + 5.7: Validate and normalise
    try:
        data = _validate_and_normalise(data, sections_to_include, retrieved_chunks)
    except Exception as exc:
        return _error_state(f"Failed to validate generated draft: {exc}")

    data["_ai_usage"] = usage
    return data
