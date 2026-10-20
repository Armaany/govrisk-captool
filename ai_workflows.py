"""Cost-safe wrappers around paid extraction and generation calls."""

from __future__ import annotations

import hashlib

from ai_request_cache import run_cached_json
from config import (
    EXTRACTION_MAX_TOKENS,
    EXTRACTION_MODEL_NAME,
    GENERATION_MAX_TOKENS,
    GENERATION_MODEL_NAME,
)
from draft_generator import generate_draft
from tor_extractor import extract_tor


EXTRACTION_PROMPT_VERSION = "cost-safe-v1"
GENERATION_PROMPT_VERSION = "cost-safe-v1"


def extract_tor_cached(
    file_bytes: bytes,
    filename: str,
    *,
    cache_dir: str | None = None,
) -> tuple[dict, bool]:
    """Extract once per exact file/model contract and reuse successful output."""
    payload = {
        "file_sha256": hashlib.sha256(file_bytes).hexdigest(),
        "filename": filename,
        "model": EXTRACTION_MODEL_NAME,
        "max_tokens": EXTRACTION_MAX_TOKENS,
        "prompt_version": EXTRACTION_PROMPT_VERSION,
    }
    return run_cached_json(
        "tor-extraction",
        payload,
        lambda: extract_tor(file_bytes, filename),
        cache_dir=cache_dir,
    )


def generate_draft_cached(
    tor_data: dict,
    retrieved_chunks: list,
    sections_to_include: list | None = None,
    output_language: str = "English",
    feedback: str = "",
    single_section: str | None = None,
    *,
    cache_dir: str | None = None,
) -> tuple[dict, bool]:
    """Generate once per exact evidence/option contract and reuse success."""
    payload = {
        "tor_data": tor_data,
        "retrieved_chunks": retrieved_chunks,
        "sections_to_include": sections_to_include,
        "output_language": output_language,
        "feedback": feedback,
        "single_section": single_section,
        "model": GENERATION_MODEL_NAME,
        "max_tokens": GENERATION_MAX_TOKENS,
        "prompt_version": GENERATION_PROMPT_VERSION,
    }
    return run_cached_json(
        "draft-generation",
        payload,
        lambda: generate_draft(
            tor_data,
            retrieved_chunks,
            sections_to_include=sections_to_include,
            output_language=output_language,
            feedback=feedback,
            single_section=single_section,
        ),
        cache_dir=cache_dir,
    )
