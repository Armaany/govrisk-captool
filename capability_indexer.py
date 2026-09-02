"""
capability_indexer.py — Task 2
Scans capability_library/, chunks documents, and stores them in ChromaDB.
"""

import os
import json
import uuid
import logging
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import chromadb
import pdfplumber

from chroma_client import get_collection
from docx import Document
from typing import TypedDict, List, Tuple

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

__all__ = ["index_library", "chunk_text", "detect_tags", "IndexingSummary"]


class IndexingSummary(TypedDict):
    documents_processed: int
    chunks_created: int
    documents_skipped: int


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

def index_library(force_reindex: bool = False) -> IndexingSummary:
    """
    Scan CAPABILITY_LIBRARY_PATH for .docx and .pdf files, chunk them,
    and store in ChromaDB collection "govrisk_capabilities".

    Args:
        force_reindex: If True, delete existing chunks for a file before re-indexing.

    Returns:
        IndexingSummary with documents_processed, chunks_created, documents_skipped.
    """
    library_path = os.path.abspath(CAPABILITY_LIBRARY_PATH)

    # Connect to ChromaDB via the defensive shared factory (heals the
    # misleading RustBindings error by falling back to a writable index dir).
    collection = get_collection(CHROMA_DB_PATH)

    documents_processed = 0
    chunks_created = 0
    documents_skipped = 0

    if not os.path.isdir(library_path):
        logger.warning(f"Capability library path does not exist: {library_path}")
        return IndexingSummary(
            documents_processed=0,
            chunks_created=0,
            documents_skipped=0,
        )

    for filename in os.listdir(library_path):
        filepath = os.path.join(library_path, filename)
        if not os.path.isfile(filepath):
            continue

        ext = os.path.splitext(filename)[1].lower()
        if ext not in (".docx", ".pdf"):
            continue

        # Skip-if-indexed logic
        existing = collection.get(where={"source_file": filename})
        if existing and existing.get("ids") and len(existing["ids"]) > 0:
            if not force_reindex:
                logger.info(f"Skipping already-indexed file: {filename}")
                documents_skipped += 1
                continue
            else:
                # Delete existing chunks for this file
                logger.info(f"Force re-indexing: deleting existing chunks for {filename}")
                collection.delete(where={"source_file": filename})

        # Extract text
        if ext == ".docx":
            try:
                page_texts = _extract_docx(filepath)
                doc_type = "word"
            except Exception as e:
                logger.warning(f"Failed to extract .docx {filename}: {e}")
                continue
        else:  # .pdf
            page_texts, success = _extract_pdf(filepath, filename)
            if not success:
                continue
            doc_type = "pdf"

        if not page_texts:
            logger.info(f"No text extracted from {filename}, skipping.")
            continue

        # Chunk all extracted text
        all_chunks: List[Tuple[str, int]] = []
        for page_number, text in page_texts:
            page_chunks = chunk_text(text, page_number)
            all_chunks.extend(page_chunks)

        if not all_chunks:
            logger.info(f"No chunks produced from {filename}, skipping.")
            continue

        # Store chunks in ChromaDB
        ids = []
        documents_list = []
        metadatas = []

        for i, (chunk_text_val, page_num) in enumerate(all_chunks):
            detected_geography, detected_thematic = detect_tags(chunk_text_val)

            metadata = {
                "source_file": filename,
                "page_number": page_num,
                "chunk_index": i,
                "geography": json.dumps(detected_geography),
                "thematic_areas": json.dumps(detected_thematic),
                "project_name": "",
                "year": 0,
                "donor": "",
                "country": "",
                "doc_type": doc_type,
            }

            ids.append(str(uuid.uuid4()))
            documents_list.append(chunk_text_val)
            metadatas.append(metadata)

        # Add to ChromaDB in batches to avoid issues with large documents
        batch_size = 100
        for start in range(0, len(ids), batch_size):
            end = start + batch_size
            collection.add(
                ids=ids[start:end],
                documents=documents_list[start:end],
                metadatas=metadatas[start:end],
            )

        chunks_created += len(all_chunks)
        documents_processed += 1
        logger.info(f"Indexed {filename}: {len(all_chunks)} chunks")

    return IndexingSummary(
        documents_processed=documents_processed,
        chunks_created=chunks_created,
        documents_skipped=documents_skipped,
    )
