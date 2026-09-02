"""Tests for the defensive ChromaDB client factory.

Covers:
- Fresh writable index directory initializes and supports add/count/query.
- Distinguish fresh-index success from an existing-index open.
- Writability detection.
- Safe rebuild clears only the generated index, preserving source documents.
- Empty capability library behavior (count == 0).
- Retrieval works using the application's configured dependency versions.
"""
import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import chroma_client
from chroma_client import (
    ChromaUnavailableError,
    get_client,
    get_collection,
    rebuild_index_dir,
    resolve_persist_dir,
    _dir_is_writable,
)


@pytest.fixture(autouse=True)
def _reset_resolved_dir():
    """Each test starts with a clean module-level cache."""
    chroma_client._RESOLVED_PERSIST_DIR = {}
    yield
    chroma_client._RESOLVED_PERSIST_DIR = {}


def test_fresh_writable_dir_initializes(tmp_path):
    fresh = str(tmp_path / "fresh_index")
    col = get_collection(fresh)
    assert col.count() == 0  # fresh-index success, empty library


def test_fresh_index_supports_add_and_query(tmp_path):
    fresh = str(tmp_path / "fresh_query")
    col = get_collection(fresh)
    col.add(
        ids=["a"],
        documents=["anti-corruption justice reform in Colombia"],
        metadatas=[{"source_file": "t.docx", "page_number": 1}],
    )
    assert col.count() == 1
    result = col.query(query_texts=["justice reform"], n_results=1)
    assert result["ids"][0][0] == "a"


def test_existing_index_reopens_with_same_data(tmp_path):
    persist = str(tmp_path / "persist_index")
    col = get_collection(persist)
    col.add(ids=["x"], documents=["existing content"], metadatas=[{"source_file": "e.docx"}])
    assert col.count() == 1
    # Reset the process cache and reopen the *existing* index.
    chroma_client._RESOLVED_PERSIST_DIR = {}
    col2 = get_collection(persist)
    assert col2.count() == 1  # existing-index open, data preserved


def test_writability_detection_true_for_tmp(tmp_path):
    assert _dir_is_writable(str(tmp_path / "w")) is True


def test_resolve_prefers_configured_when_writable(tmp_path):
    configured = str(tmp_path / "configured")
    resolved = resolve_persist_dir(configured)
    assert os.path.abspath(resolved) == os.path.abspath(configured)


def test_rebuild_clears_generated_index_but_preserves_source_docs(tmp_path):
    # Simulate an index dir with generated files.
    persist = tmp_path / "gen_index"
    persist.mkdir()
    (persist / "chroma.sqlite3").write_text("index-data")
    sub = persist / "some-uuid"
    sub.mkdir()
    (sub / "data.bin").write_text("vectors")

    # Separate source-document library must NOT be touched.
    library = tmp_path / "capability_library"
    library.mkdir()
    source_doc = library / "capability.docx"
    source_doc.write_text("SOURCE DOCUMENT")

    rebuild_index_dir(str(persist))

    # Generated index contents cleared.
    assert list(persist.iterdir()) == []
    # Source documents fully preserved.
    assert source_doc.exists()
    assert source_doc.read_text() == "SOURCE DOCUMENT"


def test_empty_library_count_is_zero(tmp_path):
    col = get_collection(str(tmp_path / "empty_lib"))
    assert col.count() == 0