"""
capability_retriever.py — Task 3
Queries ChromaDB for relevant capability chunks given tor_data and filters.
"""

import os
import json
import sys
import logging

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import chromadb

from config import CHROMA_DB_PATH, MAX_RETRIEVAL_RESULTS

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

__all__ = ["retrieve_chunks"]


# ---------------------------------------------------------------------------
# Query string builder (Task 3.2)
# ---------------------------------------------------------------------------

def _build_query_string(tor_data: dict) -> str:
    """
    Concatenate thematic_areas, key_requirements, and geography from tor_data
    into a single space-separated query string.
    Falls back to "capability statement" if tor_data is empty or missing fields.
    """
    parts = []
    parts.extend(tor_data.get("thematic_areas", []) or [])
    parts.extend(tor_data.get("key_requirements", []) or [])
    parts.extend(tor_data.get("geography", []) or [])

    query = " ".join(str(p) for p in parts if p)
    return query.strip() if query.strip() else "capability statement"


# ---------------------------------------------------------------------------
# Metadata parsing helpers (Task 3.6)
# ---------------------------------------------------------------------------

def _parse_json_list(value) -> list:
    """Parse a JSON string back to a list; return [] on failure."""
    if isinstance(value, list):
        return value
    if not value:
        return []
    try:
        result = json.loads(value)
        return result if isinstance(result, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def _none_if_empty_str(value) -> "str | None":
    """Return None if value is an empty string or None, else return value."""
    if value is None or value == "":
        return None
    return value


def _none_if_zero(value) -> "int | None":
    """Return None if value is 0 or None, else return value."""
    if value is None or value == 0:
        return None
    return value


# ---------------------------------------------------------------------------
# Post-query filter (Task 3.3 practical approach)
# ---------------------------------------------------------------------------

def _chunk_satisfies_filters(metadata: dict, filters: dict) -> bool:
    """
    Check whether a chunk's metadata satisfies the active filters.
    AND logic between filter types, OR logic within each type.
    A filter type is inactive (skipped) if its list is empty.
    """
    geo_filter = filters.get("geography", [])
    thematic_filter = filters.get("thematic_areas", [])
    funder_filter = filters.get("funder", [])

    # Geography filter
    if geo_filter:
        chunk_geo = _parse_json_list(metadata.get("geography", "[]"))
        if not any(g in chunk_geo for g in geo_filter):
            return False

    # Thematic areas filter
    if thematic_filter:
        chunk_thematic = _parse_json_list(metadata.get("thematic_areas", "[]"))
        if not any(t in chunk_thematic for t in thematic_filter):
            return False

    # Funder filter — stored in donor field
    if funder_filter:
        chunk_donor = metadata.get("donor", "") or ""
        if not any(f.lower() in chunk_donor.lower() for f in funder_filter):
            return False

    return True


# ---------------------------------------------------------------------------
# Main retriever (Task 3.1)
# ---------------------------------------------------------------------------

def retrieve_chunks(
    tor_data: dict,
    filters: dict,
    top_k: int = None,
) -> dict:
    """
    Retrieve relevant capability chunks from ChromaDB.

    Args:
        tor_data:  TorData dict from tor_extractor (or any dict with the same keys).
        filters:   {"geography": [...], "thematic_areas": [...], "funder": [...]}
        top_k:     Maximum chunks to return; defaults to MAX_RETRIEVAL_RESULTS.

    Returns:
        RetrievalResult dict.
    """
    if top_k is None:
        top_k = MAX_RETRIEVAL_RESULTS

    # Normalise filters
    filters = filters or {}
    geo_filter = filters.get("geography", []) or []
    thematic_filter = filters.get("thematic_areas", []) or []
    funder_filter = filters.get("funder", []) or []
    normalised_filters = {
        "geography": list(geo_filter),
        "thematic_areas": list(thematic_filter),
        "funder": list(funder_filter),
    }

    empty_result = {
        "retrieved_chunks": [],
        "total_chunks_retrieved": 0,
        "documents_used": [],
        "filters_applied": normalised_filters,
    }

    # Connect to ChromaDB (Task 3.3)
    chroma_path = os.path.abspath(CHROMA_DB_PATH)
    try:
        client = chromadb.PersistentClient(path=chroma_path)
    except Exception as e:
        logger.warning(f"Could not connect to ChromaDB at {chroma_path}: {e}")
        return empty_result

    # Get or create collection — never crash if it doesn't exist yet
    try:
        collection = client.get_or_create_collection("govrisk_capabilities")
    except Exception as e:
        logger.warning(f"Could not get ChromaDB collection: {e}")
        return empty_result

    # Handle empty collection (Task 3.3 / Requirement 4.6)
    try:
        count = collection.count()
    except Exception as e:
        logger.warning(f"Could not count ChromaDB collection: {e}")
        return empty_result

    if count == 0:
        return empty_result

    # Build query string (Task 3.2)
    query_string = _build_query_string(tor_data)

    # Request more candidates than needed to allow for deduplication + filtering
    # (Task 3.3 practical approach: query without where clause, filter in Python)
    n_results = min(top_k * 3, count)
    n_results = max(n_results, 1)

    try:
        query_result = collection.query(
            query_texts=[query_string],
            n_results=n_results,
            include=["documents", "metadatas", "distances"],
        )
    except Exception as e:
        logger.warning(f"ChromaDB query failed: {e}")
        return empty_result

    # Unpack results (ChromaDB returns lists-of-lists for batch queries)
    ids_list = query_result.get("ids", [[]])[0] or []
    docs_list = query_result.get("documents", [[]])[0] or []
    metas_list = query_result.get("metadatas", [[]])[0] or []
    dists_list = query_result.get("distances", [[]])[0] or []

    # Build candidate list with relevance scores
    # ChromaDB cosine distance: 0 = identical, 1 = orthogonal, 2 = opposite.
    # Use 1/(1+d) so scores are always in (0, 1] and monotonically decreasing with distance.
    candidates = []
    for chunk_id, text, meta, dist in zip(ids_list, docs_list, metas_list, dists_list):
        relevance_score = 1.0 / (1.0 + dist)
        candidates.append({
            "chunk_id": chunk_id,
            "text": text,
            "relevance_score": relevance_score,
            "metadata": meta,
            "distance": dist,
        })

    # Apply post-query filters (Task 3.3)
    filtered = [c for c in candidates if _chunk_satisfies_filters(c["metadata"], normalised_filters)]

    # Deduplication by (source_file, page_number) — keep first (highest score) (Task 3.4)
    seen_pairs: set = set()
    deduplicated = []
    for c in filtered:
        meta = c["metadata"]
        pair = (meta.get("source_file", ""), meta.get("page_number", 0))
        if pair not in seen_pairs:
            seen_pairs.add(pair)
            deduplicated.append(c)

    # Cap at top_k, preserving score order (Task 3.5)
    # Results from ChromaDB are already ordered by distance (ascending = relevance descending)
    capped = deduplicated[:min(top_k, MAX_RETRIEVAL_RESULTS)]

    # Build output chunks (Task 3.6 metadata parsing)
    retrieved_chunks = []
    for c in capped:
        meta = c["metadata"]
        chunk_dict = {
            "chunk_id": c["chunk_id"],
            "text": c["text"],
            "relevance_score": c["relevance_score"],
            "source_file": meta.get("source_file", ""),
            "page_number": meta.get("page_number", 0),
            "geography": _parse_json_list(meta.get("geography", "[]")),
            "thematic_areas": _parse_json_list(meta.get("thematic_areas", "[]")),
            "project_name": _none_if_empty_str(meta.get("project_name", "")),
            "year": _none_if_zero(meta.get("year", 0)),
            "donor": _none_if_empty_str(meta.get("donor", "")),
            "country": _none_if_empty_str(meta.get("country", "")),
        }
        retrieved_chunks.append(chunk_dict)

    documents_used = list({c["source_file"] for c in retrieved_chunks})

    return {
        "retrieved_chunks": retrieved_chunks,
        "total_chunks_retrieved": len(retrieved_chunks),
        "documents_used": documents_used,
        "filters_applied": normalised_filters,
    }
