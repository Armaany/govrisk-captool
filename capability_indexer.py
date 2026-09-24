"""
capability_indexer.py — Task 2 / Phase 2A

Scans capability_library/, chunks documents, and stores them in ChromaDB.

Phase 2A additions
------------------
This module now OWNS index state. It performs SHA-256 content-hash incremental
synchronization (not filename-only skipping), writes a versioned manifest
atomically beside whichever index is actually active (configured or recovery),
protects synchronization with a process-level non-blocking lock, and returns a
richly structured summary that the UI renders without ever writing index state
itself.

Key invariants
--------------
* Source documents are NEVER modified or deleted.
* A missing/unreadable library is NEVER treated as a successful empty library;
  the existing index is preserved and an explicit failure state is returned.
* A single failing document never prevents healthy documents from indexing.
* Changed documents replace their chunks without leaving stale duplicates, and
  extraction failure for a changed document preserves its previous chunks.
* The manifest is written only after a successful or partially-successful sync.
"""

import os
import json
import hashlib
import logging
import re
import sys
import tempfile
import threading
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import chromadb
import pdfplumber

import chroma_client
from chroma_client import get_collection, get_persist_status, manifest_path
from docx import Document
from typing import TypedDict, List, Optional, Tuple

from config import (
    CAPABILITY_LIBRARY_PATH,
    CHROMA_DB_PATH,
    GEOGRAPHY_OPTIONS,
    THEMATIC_OPTIONS,
    MAX_TOKENS_PER_CHUNK,
    CHUNK_OVERLAP_TOKENS,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

__all__ = [
    "index_library",
    "chunk_text",
    "detect_tags",
    "IndexingSummary",
    "IndexingInProgressError",
    "COLLECTION_NAME",
    "MANIFEST_SCHEMA_VERSION",
    "INDEX_ENGINE_VERSION",
    "SUPPORTED_EXTENSIONS",
    "compute_file_hash",
    "normalize_relative_name",
    "deterministic_chunk_id",
]

COLLECTION_NAME = "govrisk_capabilities"

# Manifest schema version. Bump when the manifest structure changes.
MANIFEST_SCHEMA_VERSION = 1

# Identifier for the index/embedding pipeline. Bump when chunking or embedding
# semantics change so a manifest cannot be mistaken for a compatible one.
INDEX_ENGINE_VERSION = "govrisk-index-v1"

SUPPORTED_EXTENSIONS = (".docx", ".pdf")

# Status values used in both per-document inventory and the top-level summary.
STATUS_READY = "ready"
STATUS_EMPTY_INDEX = "empty_index"
STATUS_PARTIAL = "partial_success"
STATUS_LIBRARY_UNAVAILABLE = "library_unavailable"
STATUS_INDEX_UNAVAILABLE = "index_unavailable"
STATUS_IN_PROGRESS = "indexing_in_progress"
# Source folder is readable but contains zero supported documents while the
# index still holds data. Incremental sync must NOT erase the index in this
# case; clearing it requires a separate explicit destructive action.
STATUS_SOURCE_LIBRARY_EMPTY = "source_library_empty"
# The indexing work completed but the manifest could not be published
# atomically. This is an infrastructure failure, not a normal ready outcome.
STATUS_MANIFEST_WRITE_FAILED = "manifest_write_failed"

# Per-document statuses.
DOC_STATUS_INDEXED = "indexed"
DOC_STATUS_UNCHANGED = "unchanged"
DOC_STATUS_FAILED = "failed"
DOC_STATUS_REMOVED = "removed"


class IndexingInProgressError(RuntimeError):
    """Raised/returned when a synchronization is already running in-process."""


class IndexingSummary(TypedDict, total=False):
    # --- Backwards-compatible keys (kept, with honest semantics) ---
    documents_processed: int      # docs newly indexed or re-indexed this run
    chunks_created: int           # chunks written this run (new/replacement)
    documents_skipped: int        # unchanged docs skipped this run (== unchanged)

    # --- Phase 2A structured fields ---
    source_documents_total: int   # supported source files present now
    indexed_documents_total: int  # distinct successfully indexed source files
    chunks_total: int             # collection.count() after sync (chunks, not docs)
    documents_unchanged: int
    documents_removed: int
    documents_failed: int
    failed_documents_total: int   # == len(failed_documents); mirrors manifest
    storage_mode: str             # "configured" or "recovery"
    last_successful_index_at: Optional[str]  # UTC ISO 8601 ending in Z
    status: str                   # one of the STATUS_* values
    error: Optional[str]
    failed_documents: List[dict]  # [{filename, reason, category}]
    documents: List[dict]         # per-document inventory


# ---------------------------------------------------------------------------
# Process-level, non-blocking indexing lock.
# ---------------------------------------------------------------------------

_INDEX_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# Content-hash / identity helpers.
# ---------------------------------------------------------------------------

def normalize_relative_name(library_path: str, filepath: str) -> str:
    """Return a normalized, forward-slash relative name for a source file.

    Using a stable relative name (rather than an absolute path) keeps document
    identity portable across machines and across the configured/recovery split.
    """
    rel = os.path.relpath(os.path.abspath(filepath), os.path.abspath(library_path))
    return rel.replace(os.sep, "/")


def compute_file_hash(filepath: str) -> str:
    """Return the SHA-256 hex digest of a file's raw bytes."""
    h = hashlib.sha256()
    with open(filepath, "rb") as handle:
        for block in iter(lambda: handle.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def index_config_fingerprint() -> str:
    """Return a short fingerprint of the effective index configuration.

    The fingerprint incorporates the engine version and the chunking settings
    (max tokens per chunk and overlap). When it differs from what a document's
    chunks were indexed under, the document must be re-indexed even if its bytes
    are unchanged, because the stored chunks no longer match the current config.
    """
    raw = "{}|max={}|overlap={}".format(
        INDEX_ENGINE_VERSION, MAX_TOKENS_PER_CHUNK, CHUNK_OVERLAP_TOKENS
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def deterministic_chunk_id(relative_name: str, content_hash: str, index: int) -> str:
    """Return a generation-specific, deterministic chunk id.

    The id incorporates the normalized relative filename, the document's content
    hash, and the chunk ordinal. Because the content hash is part of the id, a
    changed document produces an entirely NEW id space (a new "generation"),
    which is what makes transaction-safe replacement possible: new-generation
    chunks can be added alongside the old ones and, on failure, deleted by their
    exact ids without ever touching the old generation.
    """
    return "{}::{}::chunk::{:06d}".format(relative_name, content_hash, index)


# ---------------------------------------------------------------------------
# Text extraction helpers
# ---------------------------------------------------------------------------

def _extract_docx(filepath: str) -> List[Tuple[int, str]]:
    """
    Extract text from a .docx file.
    Returns list of (page_number, text) tuples.
    Page numbers are approximated: increment every 40 paragraphs.
    """
    doc = Document(filepath)
    pages: List[Tuple[int, str]] = []
    page_number = 1
    para_count = 0

    # Collect all text units (paragraphs + table cells) in document order
    text_units: List[str] = []

    # We need to iterate in document order, interleaving paragraphs and tables.
    # python-docx exposes doc.element.body children for this.
    from docx.oxml.ns import qn

    for child in doc.element.body:
        tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
        if tag == "p":
            # It's a paragraph
            para_text = child.text_content() if hasattr(child, "text_content") else ""
            # Use python-docx paragraph text extraction
            from docx.text.paragraph import Paragraph
            para = Paragraph(child, doc)
            text_units.append(("para", para.text))
        elif tag == "tbl":
            # It's a table — extract all cell texts
            from docx.table import Table
            tbl = Table(child, doc)
            for row in tbl.rows:
                for cell in row.cells:
                    text_units.append(("cell", cell.text))

    for kind, text in text_units:
        if text.strip():
            pages.append((page_number, text))
        if kind == "para":
            para_count += 1
            if para_count % 40 == 0:
                page_number += 1

    return pages


def _extract_pdf(filepath: str, filename: str) -> Tuple[List[Tuple[int, str]], bool]:
    """
    Extract text from a .pdf file using pdfplumber.
    Returns (list of (page_number, text) tuples, success_flag).
    On failure: logs warning, returns ([], False).
    """
    try:
        pages: List[Tuple[int, str]] = []
        with pdfplumber.open(filepath) as pdf:
            for i, page in enumerate(pdf.pages):
                text = page.extract_text()
                if text:
                    pages.append((i + 1, text))
        return pages, True
    except Exception as e:
        logger.warning(f"pdfplumber failed on {filename}: {e}")
        return [], False


def _extract_pages(filepath: str, filename: str, ext: str):
    """Extract page texts uniformly for supported types.

    Returns ``(pages, doc_type, success, failure_reason)``. ``success`` is False
    when extraction raised or the type is unsupported; ``failure_reason`` carries
    a safe, human-readable reason (never raw source content).
    """
    if ext == ".docx":
        try:
            pages = _extract_docx(filepath)
            return pages, "word", True, None
        except Exception as e:  # noqa: BLE001 - report, never crash the whole run
            logger.warning("Failed to extract .docx %s: %s", filename, e)
            return [], "word", False, "docx_extraction_error"
    elif ext == ".pdf":
        pages, ok = _extract_pdf(filepath, filename)
        if not ok:
            return [], "pdf", False, "pdf_extraction_error"
        return pages, "pdf", True, None
    return [], "unknown", False, "unsupported_type"


def _build_chunks_for_pages(page_texts, doc_type: str, relative_name: str, content_hash: str):
    """Chunk extracted pages into generation-specific chunk records.

    Returns ``(ids, documents, metadatas)`` aligned by position. Chunk ids are
    generation-specific (relative name + content hash + ordinal), so the chunks
    for a changed document occupy a brand-new id space and can be written before
    the old generation is removed. Each chunk records its ``content_hash`` and
    the current ``config_fingerprint`` so future runs can detect either a
    content change or an index-configuration change.
    """
    all_chunks: List[Tuple[str, int]] = []
    for page_number, text in page_texts:
        all_chunks.extend(chunk_text(text, page_number))

    fingerprint = index_config_fingerprint()
    ids: List[str] = []
    documents_list: List[str] = []
    metadatas: List[dict] = []
    for i, (chunk_text_val, page_num) in enumerate(all_chunks):
        detected_geography, detected_thematic = detect_tags(chunk_text_val)
        metadatas.append({
            "source_file": relative_name,
            "page_number": page_num,
            "chunk_index": i,
            "geography": json.dumps(detected_geography),
            "thematic_areas": json.dumps(detected_thematic),
            "project_name": "",
            "year": 0,
            "donor": "",
            "country": "",
            "doc_type": doc_type,
            "content_hash": content_hash,
            "config_fingerprint": fingerprint,
        })
        ids.append(deterministic_chunk_id(relative_name, content_hash, i))
        documents_list.append(chunk_text_val)
    return ids, documents_list, metadatas


# ---------------------------------------------------------------------------
# Text chunker
# ---------------------------------------------------------------------------

def chunk_text(text: str, page_number: int) -> List[Tuple[str, int]]:
    """
    Split text into chunks of at most MAX_TOKENS_PER_CHUNK tokens (words),
    with CHUNK_OVERLAP_TOKENS overlap between consecutive chunks.
    Never splits mid-sentence.

    Returns list of (chunk_text, page_number) tuples.
    """
    if not text or not text.strip():
        return []

    # Split text into sentences using sentence-ending punctuation
    # Pattern: split after . ! ? followed by whitespace or end of string
    sentence_pattern = re.compile(r"(?<=[.!?])(?:\s+|$)")
    raw_sentences = sentence_pattern.split(text)

    # Reconstruct sentences with their trailing punctuation
    sentences: List[str] = []
    for s in raw_sentences:
        s = s.strip()
        if s:
            sentences.append(s)

    if not sentences:
        return []

    chunks: List[Tuple[str, int]] = []
    current_words: List[str] = []
    overlap_words: List[str] = []

    for sentence in sentences:
        sentence_words = sentence.split()
        if not sentence_words:
            continue

        # If adding this sentence would exceed the limit, flush current chunk
        if current_words and len(current_words) + len(sentence_words) > MAX_TOKENS_PER_CHUNK:
            chunk_text_val = " ".join(current_words)
            chunks.append((chunk_text_val, page_number))

            # Prepare overlap: last CHUNK_OVERLAP_TOKENS words of current chunk
            overlap_words = current_words[-CHUNK_OVERLAP_TOKENS:] if len(current_words) >= CHUNK_OVERLAP_TOKENS else current_words[:]
            current_words = overlap_words + sentence_words
        else:
            current_words.extend(sentence_words)

        # If a single sentence is longer than MAX_TOKENS_PER_CHUNK, force-split it
        while len(current_words) > MAX_TOKENS_PER_CHUNK:
            chunk_words = current_words[:MAX_TOKENS_PER_CHUNK]
            chunk_text_val = " ".join(chunk_words)
            chunks.append((chunk_text_val, page_number))
            overlap_words = current_words[MAX_TOKENS_PER_CHUNK - CHUNK_OVERLAP_TOKENS:MAX_TOKENS_PER_CHUNK]
            current_words = overlap_words + current_words[MAX_TOKENS_PER_CHUNK:]

    # Flush remaining words
    if current_words:
        chunk_text_val = " ".join(current_words)
        chunks.append((chunk_text_val, page_number))

    return chunks


# ---------------------------------------------------------------------------
# Keyword detection
# ---------------------------------------------------------------------------

def detect_tags(text: str) -> Tuple[List[str], List[str]]:
    """
    Detect geography and thematic tags in text by keyword matching.
    Returns (geography_list, thematic_list).
    Matching is case-insensitive.
    """
    text_lower = text.lower()
    geography: List[str] = []
    thematic: List[str] = []

    for option in GEOGRAPHY_OPTIONS:
        if option.lower() in text_lower:
            geography.append(option)

    for option in THEMATIC_OPTIONS:
        if option.lower() in text_lower:
            thematic.append(option)

    return geography, thematic


# ---------------------------------------------------------------------------
# Main indexer
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Manifest writing (atomic, versioned, beside the ACTIVE index).
# ---------------------------------------------------------------------------

def _utc_now_z() -> str:
    """Return a timezone-aware UTC timestamp in ISO 8601 ending with 'Z'."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_manifest_atomic(configured_path: str, manifest: dict) -> str:
    """Atomically write ``manifest`` beside the active index; return its path.

    Uses a temp file in the SAME directory, flush + fsync, then os.replace so a
    reader never observes a partially written manifest.
    """
    target = manifest_path(configured_path)
    target_dir = os.path.dirname(target)
    os.makedirs(target_dir, exist_ok=True)

    fd, tmp = tempfile.mkstemp(prefix=".index_manifest.", suffix=".tmp", dir=target_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(manifest, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, target)
    except Exception:
        # Best-effort cleanup of the temp file if replace never happened.
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        raise
    return target


def _existing_doc_state(collection) -> dict:
    """Map ``source_file`` -> recorded index state for that document.

    Each value is ``{"hash": <content_hash|None>, "fingerprint": <str|None>,
    "ids": [<exact chunk ids>]}``. This captures the *exact* old chunk ids so a
    changed document can be replaced transactionally (delete precisely those ids
    only after the new generation is fully written), and records the config
    fingerprint so a configuration change forces a re-index of unchanged bytes.

    Reads only ids + metadata. Missing hash/fingerprint map to None so a legacy
    index is treated as changed and re-synced.
    """
    state: dict = {}
    try:
        existing = collection.get(include=["metadatas"])
    except Exception as e:  # noqa: BLE001
        logger.warning("Could not read existing index metadata: %s", e)
        return state
    ids = existing.get("ids", []) or []
    metas = existing.get("metadatas", []) or []
    for chunk_id, meta in zip(ids, metas):
        src = (meta or {}).get("source_file")
        if src is None:
            continue
        entry = state.setdefault(
            src, {"hash": (meta or {}).get("content_hash"),
                  "fingerprint": (meta or {}).get("config_fingerprint"),
                  "ids": []}
        )
        entry["ids"].append(chunk_id)
    return state


def _list_source_documents(library_path: str):
    """Return supported source files present as ``[(relative_name, filepath)]``.

    Raises OSError if the directory cannot be listed so callers can distinguish
    "unreadable library" from "empty library".
    """
    found = []
    for filename in sorted(os.listdir(library_path)):
        filepath = os.path.join(library_path, filename)
        if not os.path.isfile(filepath):
            continue
        ext = os.path.splitext(filename)[1].lower()
        if ext not in SUPPORTED_EXTENSIONS:
            continue
        rel = normalize_relative_name(library_path, filepath)
        found.append((rel, filepath))
    return found


def _base_summary(storage_mode: str) -> dict:
    return {
        "documents_processed": 0,
        "chunks_created": 0,
        "documents_skipped": 0,
        "source_documents_total": 0,
        "indexed_documents_total": 0,
        "chunks_total": 0,
        "documents_unchanged": 0,
        "documents_removed": 0,
        "documents_failed": 0,
        "failed_documents_total": 0,
        "storage_mode": storage_mode,
        "last_successful_index_at": None,
        "status": STATUS_READY,
        "error": None,
        "failed_documents": [],
        "documents": [],
    }


def index_library(force_reindex: bool = False) -> IndexingSummary:
    """Content-hash incremental synchronization of the capability library.

    Behaviour (Phase 2A):

    * New document -> extract, chunk, index.
    * Unchanged filename + SHA-256 -> skip.
    * Changed hash -> extract & prepare replacement chunks, then delete old
      chunks only after replacement is ready (extraction failure keeps old).
    * Removed source document -> delete stale chunks, but only after a valid
      source-directory inventory succeeds.
    * Unsupported files -> ignored.
    * Missing/unreadable library -> existing index preserved; explicit failure
      state returned (NEVER a successful empty library).
    * One failed document never blocks healthy documents.

    Only one synchronization may run per process at a time; a concurrent call
    returns a summary with ``status == STATUS_IN_PROGRESS`` without touching the
    index. On success or partial success a versioned manifest is written
    atomically beside the active index.

    ``force_reindex`` re-indexes every present document regardless of hash.
    """
    # Non-blocking, process-level lock. A second concurrent call must not begin
    # extraction or touch Chroma.
    if not _INDEX_LOCK.acquire(blocking=False):
        logger.warning("index_library called while a sync is already in progress")
        summary = _base_summary(storage_mode="unknown")
        summary["status"] = STATUS_IN_PROGRESS
        summary["error"] = "Indexing already in progress."
        return IndexingSummary(**summary)

    try:
        return _index_library_locked(force_reindex=force_reindex)
    finally:
        # Guaranteed release on both success and exception.
        _INDEX_LOCK.release()


def _index_library_locked(force_reindex: bool) -> IndexingSummary:
    library_path = os.path.abspath(CAPABILITY_LIBRARY_PATH)

    summary = _base_summary("unknown")

    # Connect to ChromaDB via the defensive shared factory (heals the
    # misleading RustBindings error by falling back to a writable index dir).
    # We must open the client BEFORE reading storage mode: opening is what
    # triggers (and caches) any recovery fallback, so the resolved directory is
    # only authoritative afterwards.
    try:
        collection = get_collection(CHROMA_DB_PATH)
    except Exception as e:  # noqa: BLE001
        logger.warning("ChromaDB unavailable during indexing: %s", e)
        summary["status"] = STATUS_INDEX_UNAVAILABLE
        summary["error"] = "{}: {}".format(type(e).__name__, e)
        return IndexingSummary(**summary)

    # Now the resolved-directory cache reflects any recovery fallback, so the
    # storage mode reported here (and written to the manifest) is honest.
    try:
        storage_mode = get_persist_status(CHROMA_DB_PATH).mode
    except Exception:  # noqa: BLE001
        storage_mode = "unknown"
    summary["storage_mode"] = storage_mode

    # Inventory the source directory. A missing/unreadable library must preserve
    # the existing index and return an explicit failure — never an empty success.
    if not os.path.isdir(library_path):
        logger.warning("Capability library directory missing/unreadable: %s", library_path)
        summary["status"] = STATUS_LIBRARY_UNAVAILABLE
        summary["error"] = "Capability library directory is missing or unreadable."
        try:
            summary["chunks_total"] = collection.count()
        except Exception:  # noqa: BLE001
            pass
        return IndexingSummary(**summary)

    try:
        source_docs = _list_source_documents(library_path)
    except OSError as e:
        logger.warning("Capability library directory unreadable: %s", e)
        summary["status"] = STATUS_LIBRARY_UNAVAILABLE
        summary["error"] = "Capability library directory is missing or unreadable."
        try:
            summary["chunks_total"] = collection.count()
        except Exception:  # noqa: BLE001
            pass
        return IndexingSummary(**summary)

    summary["source_documents_total"] = len(source_docs)
    present_relnames = {rel for rel, _ in source_docs}
    existing_state = _existing_doc_state(collection)

    try:
        existing_chunk_total = collection.count()
    except Exception:  # noqa: BLE001
        existing_chunk_total = 0

    # --- Empty-library protection (blocker 2) ------------------------------
    # A readable but EMPTY source folder must not erase a non-empty valid index
    # during incremental synchronization. Clearing every indexed document is a
    # separate, explicit destructive action (rebuild), never a side effect here.
    if not source_docs:
        if existing_chunk_total > 0:
            logger.warning(
                "Source library is empty but the index still holds %d chunks; "
                "preserving the index (source_library_empty).",
                existing_chunk_total,
            )
            summary["chunks_total"] = existing_chunk_total
            summary["indexed_documents_total"] = len(existing_state)
            summary["status"] = STATUS_SOURCE_LIBRARY_EMPTY
            summary["error"] = (
                "No supported source documents are present. The existing search "
                "index has been preserved and was not modified."
            )
            # Publish a manifest that honestly reflects the preserved index.
            _publish_manifest_or_flag(
                summary, storage_mode, documents_inventory=[
                    {"filename": rel, "content_hash": st.get("hash"),
                     "file_size": None, "chunk_count": len(st.get("ids", [])),
                     "status": DOC_STATUS_UNCHANGED}
                    for rel, st in sorted(existing_state.items())
                ], failed_documents=[],
            )
            return IndexingSummary(**summary)
        # Both source folder and index are empty.
        summary["chunks_total"] = 0
        summary["indexed_documents_total"] = 0
        summary["status"] = STATUS_EMPTY_INDEX
        _publish_manifest_or_flag(summary, storage_mode, [], [])
        return IndexingSummary(**summary)

    current_fingerprint = index_config_fingerprint()

    documents_inventory: List[dict] = []
    failed_documents: List[dict] = []
    indexed_relnames = set()

    for rel, filepath in source_docs:
        prior = existing_state.get(rel)
        previously_indexed = prior is not None
        old_ids = list(prior["ids"]) if previously_indexed else []

        # Compute the current content hash first; a hash failure is a per-doc
        # failure that must not stop the run.
        try:
            content_hash = compute_file_hash(filepath)
            file_size = os.path.getsize(filepath)
        except OSError as e:
            logger.warning("Could not read source document %s: %s", rel, e)
            failed_documents.append({"filename": rel, "category": "read_error", "reason": "read_error"})
            documents_inventory.append({
                "filename": rel, "content_hash": None, "file_size": None,
                "chunk_count": _count_chunks_for(collection, rel), "status": DOC_STATUS_FAILED,
                "failure_category": "read_error",
            })
            # Preserve whatever was previously indexed for this doc.
            if previously_indexed:
                indexed_relnames.add(rel)
            continue

        # Unchanged means same content hash AND same index-configuration
        # fingerprint. A configuration change forces a re-index (blocker 4).
        hash_matches = previously_indexed and prior.get("hash") == content_hash
        fingerprint_matches = previously_indexed and prior.get("fingerprint") == current_fingerprint
        unchanged = hash_matches and fingerprint_matches and not force_reindex

        if unchanged:
            summary["documents_unchanged"] += 1
            indexed_relnames.add(rel)
            documents_inventory.append({
                "filename": rel, "content_hash": content_hash, "file_size": file_size,
                "chunk_count": len(old_ids), "status": DOC_STATUS_UNCHANGED,
            })
            continue

        # New or changed (or forced, or config-changed): extract and prepare the
        # replacement BEFORE deleting anything, so an extraction failure keeps
        # the old generation intact.
        ext = os.path.splitext(filepath)[1].lower()
        pages, doc_type, ok, reason = _extract_pages(filepath, rel, ext)
        if not ok:
            failed_documents.append({"filename": rel, "category": reason, "reason": reason})
            documents_inventory.append({
                "filename": rel, "content_hash": content_hash, "file_size": file_size,
                "chunk_count": len(old_ids), "status": DOC_STATUS_FAILED,
                "failure_category": reason,
            })
            if previously_indexed:
                indexed_relnames.add(rel)
            continue

        new_ids, docs_list, metadatas = _build_chunks_for_pages(
            pages, doc_type, rel, content_hash
        )
        if not new_ids:
            logger.info("No chunks produced from %s", rel)
            failed_documents.append({"filename": rel, "category": "no_text", "reason": "no_text_extracted"})
            documents_inventory.append({
                "filename": rel, "content_hash": content_hash, "file_size": file_size,
                "chunk_count": len(old_ids), "status": DOC_STATUS_FAILED,
                "failure_category": "no_text",
            })
            if previously_indexed:
                indexed_relnames.add(rel)
            continue

        # --- Transaction-safe replacement (blocker 1) ---------------------
        # 1. Add the new generation first (its ids are content-hash specific and
        #    disjoint from the old generation, unless bytes are unchanged but the
        #    config changed — in which case ids collide and upsert is required).
        # 2. If any batch fails, delete the new-generation ids added so far and
        #    preserve the old generation entirely.
        # 3. Only after every batch succeeds, delete the EXACT old ids (never a
        #    broad source_file delete that could remove the new generation).
        write_ok, added_ids, write_error = _add_generation(
            collection, new_ids, docs_list, metadatas
        )
        if not write_ok:
            logger.warning("Failed to write new generation for %s: %s", rel, write_error)
            rollback_ok = _rollback_added(collection, added_ids)
            category = "write_error" if rollback_ok else "write_error_rollback_failed"
            if not rollback_ok:
                logger.error(
                    "Rollback of partial new generation FAILED for %s; "
                    "index may contain orphan new-generation chunks.", rel
                )
            failed_documents.append({"filename": rel, "category": category, "reason": category})
            documents_inventory.append({
                "filename": rel, "content_hash": content_hash, "file_size": file_size,
                "chunk_count": _count_chunks_for(collection, rel), "status": DOC_STATUS_FAILED,
                "failure_category": category,
            })
            # Old evidence is preserved (never deleted on failure).
            if previously_indexed:
                indexed_relnames.add(rel)
            continue

        # New generation is fully written; now remove exactly the old ids that
        # are not part of the new generation (bytes-unchanged + config-changed
        # produces identical ids, so exclude them from deletion).
        stale_old_ids = [cid for cid in old_ids if cid not in set(new_ids)]
        if stale_old_ids:
            try:
                collection.delete(ids=stale_old_ids)
            except Exception as e:  # noqa: BLE001
                # New generation is present and correct; failing to prune the old
                # generation is a partial success, not a data-loss event.
                logger.warning("Failed to delete old generation for %s: %s", rel, e)
                failed_documents.append({
                    "filename": rel, "category": "stale_delete_error",
                    "reason": "stale_delete_error",
                })
                documents_inventory.append({
                    "filename": rel, "content_hash": content_hash, "file_size": file_size,
                    "chunk_count": _count_chunks_for(collection, rel),
                    "status": DOC_STATUS_FAILED, "failure_category": "stale_delete_error",
                })
                # The document IS indexed (new generation present).
                indexed_relnames.add(rel)
                continue

        summary["documents_processed"] += 1
        summary["chunks_created"] += len(new_ids)
        indexed_relnames.add(rel)
        documents_inventory.append({
            "filename": rel, "content_hash": content_hash, "file_size": file_size,
            "chunk_count": len(new_ids), "status": DOC_STATUS_INDEXED,
        })
        logger.info("Indexed %s: %d chunks", rel, len(new_ids))

    # Removed documents: delete stale chunks by their EXACT ids, only now that a
    # valid non-empty inventory has been established. A deletion failure is a
    # partial success (blocker 3): the document is still present in Chroma, so it
    # is still counted in indexed_documents_total and recorded as a failure.
    for stale_rel in sorted(set(existing_state) - present_relnames):
        stale_ids = list(existing_state[stale_rel]["ids"])
        try:
            if stale_ids:
                collection.delete(ids=stale_ids)
            summary["documents_removed"] += 1
            documents_inventory.append({
                "filename": stale_rel, "content_hash": None, "file_size": None,
                "chunk_count": 0, "status": DOC_STATUS_REMOVED,
            })
            indexed_relnames.discard(stale_rel)
            logger.info("Removed stale chunks for deleted document %s", stale_rel)
        except Exception as e:  # noqa: BLE001
            logger.warning("Failed to remove stale chunks for %s: %s", stale_rel, e)
            failed_documents.append({
                "filename": stale_rel, "category": "removed_delete_error",
                "reason": "removed_delete_error",
            })
            documents_inventory.append({
                "filename": stale_rel, "content_hash": existing_state[stale_rel].get("hash"),
                "file_size": None, "chunk_count": _count_chunks_for(collection, stale_rel),
                "status": DOC_STATUS_FAILED, "failure_category": "removed_delete_error",
            })
            # Still present in Chroma -> still counted as indexed.
            indexed_relnames.add(stale_rel)

    # Final tallies.
    summary["documents_failed"] = len(failed_documents)
    summary["failed_documents_total"] = len(failed_documents)
    summary["failed_documents"] = failed_documents
    summary["documents_skipped"] = summary["documents_unchanged"]
    summary["indexed_documents_total"] = len(indexed_relnames)
    summary["documents"] = documents_inventory
    try:
        summary["chunks_total"] = collection.count()
    except Exception:  # noqa: BLE001
        summary["chunks_total"] = summary["chunks_created"]

    # Overall status.
    if failed_documents:
        summary["status"] = STATUS_PARTIAL
    elif summary["indexed_documents_total"] == 0:
        summary["status"] = STATUS_EMPTY_INDEX
    else:
        summary["status"] = STATUS_READY

    _publish_manifest_or_flag(summary, storage_mode, documents_inventory, failed_documents)
    return IndexingSummary(**summary)


def _build_manifest(summary: dict, storage_mode: str, documents_inventory, failed_documents) -> dict:
    """Build the manifest dict from the current summary and inventories."""
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "status": summary["status"],
        "last_successful_index_at": summary.get("last_successful_index_at"),
        "collection_name": COLLECTION_NAME,
        "storage_mode": storage_mode,
        "source_documents_total": summary["source_documents_total"],
        "indexed_documents_total": summary["indexed_documents_total"],
        "chunks_total": summary["chunks_total"],
        "failed_documents_total": len(failed_documents),
        "failed_documents": failed_documents,
        "config_fingerprint": index_config_fingerprint(),
        "settings": {
            "max_tokens_per_chunk": MAX_TOKENS_PER_CHUNK,
            "chunk_overlap_tokens": CHUNK_OVERLAP_TOKENS,
            "index_engine_version": INDEX_ENGINE_VERSION,
        },
        "documents": documents_inventory,
    }


def _publish_manifest_or_flag(summary: dict, storage_mode: str, documents_inventory, failed_documents):
    """Atomically publish the manifest, or flag a publication failure.

    On success, stamp ``last_successful_index_at`` and write the manifest.
    On failure (blocker 5): do NOT claim a new successful timestamp was
    persisted, set an explicit infrastructure status, and expose a safe error
    category — never silently proceed as if everything completed normally.
    """
    # Tentative timestamp for the manifest content; only "kept" on success.
    timestamp = _utc_now_z()
    summary["last_successful_index_at"] = timestamp
    manifest = _build_manifest(summary, storage_mode, documents_inventory, failed_documents)
    try:
        _write_manifest_atomic(CHROMA_DB_PATH, manifest)
    except Exception as e:  # noqa: BLE001
        logger.error("Failed to publish index manifest atomically: %s", e)
        summary["status"] = STATUS_MANIFEST_WRITE_FAILED
        summary["error"] = "manifest_write_failed"
        # We cannot claim a successful persisted timestamp.
        summary["last_successful_index_at"] = None


def _add_generation(collection, ids, documents_list, metadatas, batch_size: int = 100):
    """Add a new generation batch-by-batch, tracking exactly what was added.

    Returns ``(ok, added_ids, error)``. ``added_ids`` lists the ids successfully
    written so far (for precise rollback if a later batch fails).
    """
    added_ids: List[str] = []
    for start in range(0, len(ids), batch_size):
        end = start + batch_size
        batch_ids = ids[start:end]
        try:
            collection.add(
                ids=batch_ids,
                documents=documents_list[start:end],
                metadatas=metadatas[start:end],
            )
        except Exception as e:  # noqa: BLE001
            return False, added_ids, e
        added_ids.extend(batch_ids)
    return True, added_ids, None


def _rollback_added(collection, added_ids) -> bool:
    """Delete new-generation ids added before a failure. Return success."""
    if not added_ids:
        return True
    try:
        collection.delete(ids=list(added_ids))
        return True
    except Exception as e:  # noqa: BLE001
        logger.error("Rollback delete failed: %s", e)
        return False


def _count_chunks_for(collection, relative_name: str) -> int:
    """Return the number of chunks currently stored for a source document."""
    try:
        got = collection.get(where={"source_file": relative_name})
        return len(got.get("ids", []) or [])
    except Exception:  # noqa: BLE001
        return 0


def _add_in_batches(collection, ids, documents_list, metadatas, batch_size: int = 100):
    """Add chunks to ChromaDB in batches to avoid oversized single writes."""
    for start in range(0, len(ids), batch_size):
        end = start + batch_size
        collection.add(
            ids=ids[start:end],
            documents=documents_list[start:end],
            metadatas=metadatas[start:end],
        )
