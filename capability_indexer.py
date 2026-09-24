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


def deterministic_chunk_id(relative_name: str, index: int) -> str:
    """Return a stable chunk id derived from the document identity + position.

    Deterministic ids mean re-indexing a changed document overwrites the same
    id space and cannot leave stale duplicate chunks behind.
    """
    return "{}::chunk::{:06d}".format(relative_name, index)


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


def _build_chunks_for_pages(page_texts, doc_type: str, relative_name: str):
    """Chunk extracted pages into deterministic-id chunk records.

    Returns ``(ids, documents, metadatas)`` aligned by position. Chunk ids are
    deterministic on ``relative_name`` + ordinal so a re-index of a changed
    document overwrites the same id space (no stale duplicates).
    """
    all_chunks: List[Tuple[str, int]] = []
    for page_number, text in page_texts:
        all_chunks.extend(chunk_text(text, page_number))

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
        })
        ids.append(deterministic_chunk_id(relative_name, i))
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


def _existing_doc_hashes(collection) -> dict:
    """Map ``source_file`` -> most recently recorded ``content_hash`` in index.

    Reads only metadata. Missing content_hash entries map to None so a legacy
    index (indexed before hashes existed) is treated as changed and re-synced.
    """
    hashes: dict = {}
    try:
        existing = collection.get(include=["metadatas"])
    except Exception as e:  # noqa: BLE001
        logger.warning("Could not read existing index metadata: %s", e)
        return hashes
    for meta in existing.get("metadatas", []) or []:
        src = meta.get("source_file")
        if src is None:
            continue
        hashes.setdefault(src, meta.get("content_hash"))
    return hashes


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
    existing_hashes = _existing_doc_hashes(collection)

    documents_inventory: List[dict] = []
    failed_documents: List[dict] = []
    indexed_relnames = set()

    for rel, filepath in source_docs:
        # Compute the current content hash first; a hash failure is a per-doc
        # failure that must not stop the run.
        try:
            content_hash = compute_file_hash(filepath)
            file_size = os.path.getsize(filepath)
        except OSError as e:
            logger.warning("Could not read source document %s: %s", rel, e)
            failed_documents.append({"filename": rel, "category": "read_error", "reason": str(e)})
            documents_inventory.append({
                "filename": rel, "content_hash": None, "file_size": None,
                "chunk_count": 0, "status": DOC_STATUS_FAILED,
                "failure_category": "read_error",
            })
            # Preserve whatever was previously indexed for this doc.
            if rel in existing_hashes:
                indexed_relnames.add(rel)
            continue

        previously_indexed = rel in existing_hashes
        unchanged = (
            previously_indexed
            and not force_reindex
            and existing_hashes.get(rel) == content_hash
        )

        if unchanged:
            summary["documents_unchanged"] += 1
            indexed_relnames.add(rel)
            documents_inventory.append({
                "filename": rel, "content_hash": content_hash, "file_size": file_size,
                "chunk_count": _count_chunks_for(collection, rel),
                "status": DOC_STATUS_UNCHANGED,
            })
            continue

        # New or changed (or forced): extract and prepare replacement BEFORE
        # deleting anything, so an extraction failure preserves old chunks.
        ext = os.path.splitext(filepath)[1].lower()
        pages, doc_type, ok, reason = _extract_pages(filepath, rel, ext)
        if not ok:
            failed_documents.append({"filename": rel, "category": reason, "reason": reason})
            documents_inventory.append({
                "filename": rel, "content_hash": content_hash, "file_size": file_size,
                "chunk_count": _count_chunks_for(collection, rel),
                "status": DOC_STATUS_FAILED, "failure_category": reason,
            })
            # Preserve previous valid chunks for a changed document.
            if previously_indexed:
                indexed_relnames.add(rel)
            continue

        ids, docs_list, metadatas = _build_chunks_for_pages(pages, doc_type, rel)
        if not ids:
            # No text/chunks produced. Treat as a soft failure but preserve any
            # previous chunks (do not silently wipe a doc on a transient empty).
            logger.info("No chunks produced from %s", rel)
            failed_documents.append({"filename": rel, "category": "no_text", "reason": "no_text_extracted"})
            documents_inventory.append({
                "filename": rel, "content_hash": content_hash, "file_size": file_size,
                "chunk_count": _count_chunks_for(collection, rel),
                "status": DOC_STATUS_FAILED, "failure_category": "no_text",
            })
            if previously_indexed:
                indexed_relnames.add(rel)
            continue

        # Stamp content hash on each chunk so future runs can detect changes.
        for meta in metadatas:
            meta["content_hash"] = content_hash

        # Replacement succeeded in preparation: now remove old chunks (if any)
        # and add the new ones. Deterministic ids also prevent duplicates.
        try:
            if previously_indexed:
                collection.delete(where={"source_file": rel})
            _add_in_batches(collection, ids, docs_list, metadatas)
        except Exception as e:  # noqa: BLE001
            logger.warning("Failed to write chunks for %s: %s", rel, e)
            failed_documents.append({"filename": rel, "category": "write_error", "reason": str(e)})
            documents_inventory.append({
                "filename": rel, "content_hash": content_hash, "file_size": file_size,
                "chunk_count": _count_chunks_for(collection, rel),
                "status": DOC_STATUS_FAILED, "failure_category": "write_error",
            })
            if previously_indexed:
                indexed_relnames.add(rel)
            continue

        summary["documents_processed"] += 1
        summary["chunks_created"] += len(ids)
        indexed_relnames.add(rel)
        documents_inventory.append({
            "filename": rel, "content_hash": content_hash, "file_size": file_size,
            "chunk_count": len(ids), "status": DOC_STATUS_INDEXED,
        })
        logger.info("Indexed %s: %d chunks", rel, len(ids))

    # Removed documents: delete stale chunks only now that inventory succeeded.
    for stale_rel in sorted(set(existing_hashes) - present_relnames):
        try:
            collection.delete(where={"source_file": stale_rel})
            summary["documents_removed"] += 1
            documents_inventory.append({
                "filename": stale_rel, "content_hash": None, "file_size": None,
                "chunk_count": 0, "status": DOC_STATUS_REMOVED,
            })
            indexed_relnames.discard(stale_rel)
            logger.info("Removed stale chunks for deleted document %s", stale_rel)
        except Exception as e:  # noqa: BLE001
            logger.warning("Failed to remove stale chunks for %s: %s", stale_rel, e)

    # Final tallies.
    summary["documents_failed"] = len(failed_documents)
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

    # Write the manifest only after a successful or partially-successful sync.
    summary["last_successful_index_at"] = _utc_now_z()
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "last_successful_index_at": summary["last_successful_index_at"],
        "collection_name": COLLECTION_NAME,
        "storage_mode": storage_mode,
        "source_documents_total": summary["source_documents_total"],
        "indexed_documents_total": summary["indexed_documents_total"],
        "chunks_total": summary["chunks_total"],
        "failed_documents": failed_documents,
        "settings": {
            "max_tokens_per_chunk": MAX_TOKENS_PER_CHUNK,
            "chunk_overlap_tokens": CHUNK_OVERLAP_TOKENS,
            "index_engine_version": INDEX_ENGINE_VERSION,
        },
        "documents": documents_inventory,
    }
    try:
        _write_manifest_atomic(CHROMA_DB_PATH, manifest)
    except Exception as e:  # noqa: BLE001
        # A manifest write failure must not lose the actual indexing work; it is
        # reported but does not change index contents.
        logger.warning("Failed to write index manifest: %s", e)

    return IndexingSummary(**summary)


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
