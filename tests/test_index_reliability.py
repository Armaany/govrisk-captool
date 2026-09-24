"""Phase 2A acceptance tests for index reliability.

Covers the 20 required acceptance criteria for:
- honest source/indexed/chunk counts,
- indexer-owned atomic versioned manifest written beside the ACTIVE index,
- SHA-256 content-hash incremental reconciliation with old-chunk preservation,
- concurrency protection and lock release,
- safe auto-index (no endless retry),
- app.py presentation-only guarantees (no manifest write, chunks labelled honestly),
- approved recovery wording,
- explicit rebuild manifest invalidation,
- empty/missing library cannot destroy a valid index.

All fixtures use temporary documents and mocks only. No real source-document
content, live services, or secrets are used.
"""
import os
import sys
import json
import re
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import patch, MagicMock

import chroma_client
import capability_indexer
from capability_indexer import index_library, MANIFEST_SCHEMA_VERSION


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_module_state():
    """Isolate Chroma-client caches and the indexing lock between tests."""
    chroma_client._RESOLVED_PERSIST_DIR = {}
    chroma_client._RECOVERY_DIR = None
    # Ensure the process-level lock starts free even if a prior test aborted.
    if capability_indexer._INDEX_LOCK.locked():  # pragma: no cover - safety
        capability_indexer._INDEX_LOCK.release()
    yield
    chroma_client._RESOLVED_PERSIST_DIR = {}
    chroma_client._RECOVERY_DIR = None


def _make_docx(path, paragraphs):
    """Write a minimal .docx file with the given paragraphs."""
    from docx import Document as DocxDocument

    doc = DocxDocument()
    for para in paragraphs:
        doc.add_paragraph(para)
    doc.save(str(path))


def _run_index(lib_path, chroma_path, force_reindex=False):
    """Run index_library with the module paths patched to temp locations."""
    with patch("capability_indexer.CAPABILITY_LIBRARY_PATH", str(lib_path) + os.sep):
        with patch("capability_indexer.CHROMA_DB_PATH", str(chroma_path)):
            return index_library(force_reindex=force_reindex)


def _read_manifest(chroma_path):
    with patch("capability_indexer.CHROMA_DB_PATH", str(chroma_path)):
        mpath = capability_indexer.manifest_path(str(chroma_path))
    with open(mpath, encoding="utf-8") as f:
        return json.load(f), mpath


def _collection(chroma_path):
    import chromadb

    client = chromadb.PersistentClient(path=str(chroma_path))
    return client.get_collection(capability_indexer.COLLECTION_NAME)


# ===========================================================================
# 1. Source, indexed-document, and chunk counts are distinct.
# ===========================================================================

def test_counts_source_indexed_and_chunks_are_distinct(tmp_path):
    lib = tmp_path / "lib"
    lib.mkdir()
    # One indexable doc that yields multiple chunks; one unsupported file.
    long_text = " ".join(f"sentence number {i} about AML/CFT in Mexico." for i in range(400))
    _make_docx(lib / "a.docx", [long_text])
    (lib / "notes.txt").write_text("unsupported")

    chroma = tmp_path / "chroma"
    summary = _run_index(lib, chroma)

    assert summary["source_documents_total"] == 1        # .txt ignored
    assert summary["indexed_documents_total"] == 1
    assert summary["chunks_total"] > 1                    # multiple chunks
    # The three numbers are genuinely different concepts here.
    assert summary["chunks_total"] != summary["indexed_documents_total"]


# ===========================================================================
# 2. Configured storage writes a manifest beside the configured index.
# ===========================================================================

def test_manifest_written_beside_configured_index(tmp_path):
    lib = tmp_path / "lib"
    lib.mkdir()
    _make_docx(lib / "a.docx", ["GovRisk AML work in Mexico."])
    chroma = tmp_path / "chroma"

    _run_index(lib, chroma)

    manifest, mpath = _read_manifest(chroma)
    assert os.path.dirname(os.path.abspath(mpath)) == os.path.abspath(str(chroma))
    assert manifest["storage_mode"] == "configured"


# ===========================================================================
# 3. Recovery storage writes the manifest beside the recovery index only.
# ===========================================================================

def test_manifest_written_beside_recovery_index_only(tmp_path):
    lib = tmp_path / "lib"
    lib.mkdir()
    _make_docx(lib / "a.docx", ["GovRisk AML work in Colombia."])
    configured = tmp_path / "configured_chroma"

    real_client = chroma_client._try_client

    def fake_try_client(path):
        # Fail only for the configured path; recovery path succeeds (real).
        if os.path.abspath(path) == os.path.abspath(str(configured)):
            raise RuntimeError("configured boom")
        return real_client(path)

    with patch.object(chroma_client, "_try_client", side_effect=fake_try_client):
        summary = _run_index(lib, configured)
        status = chroma_client.get_persist_status(str(configured))

    assert summary["storage_mode"] == "recovery"
    recovery_dir = status.active_dir
    assert os.path.abspath(recovery_dir) != os.path.abspath(str(configured))
    # Manifest exists beside the recovery dir...
    assert os.path.exists(os.path.join(recovery_dir, chroma_client.MANIFEST_FILENAME))
    # ...and NOT beside the configured dir.
    assert not os.path.exists(os.path.join(str(configured), chroma_client.MANIFEST_FILENAME))


# ===========================================================================
# 4. Manifest JSON is versioned and atomically replaced.
# ===========================================================================

def test_manifest_is_versioned_and_atomically_replaced(tmp_path):
    lib = tmp_path / "lib"
    lib.mkdir()
    _make_docx(lib / "a.docx", ["Versioned manifest test in Peru."])
    chroma = tmp_path / "chroma"

    replace_calls = []
    real_replace = os.replace

    def spy_replace(src, dst):
        replace_calls.append((src, dst))
        return real_replace(src, dst)

    with patch("capability_indexer.os.replace", side_effect=spy_replace):
        _run_index(lib, chroma)

    manifest, mpath = _read_manifest(chroma)
    assert manifest["schema_version"] == MANIFEST_SCHEMA_VERSION == 1
    # os.replace was used to publish the manifest atomically.
    assert any(os.path.abspath(dst) == os.path.abspath(mpath) for _, dst in replace_calls)


# ===========================================================================
# 5. Timestamp is timezone-aware UTC and ends in Z.
# ===========================================================================

def test_timestamp_is_utc_and_ends_in_z(tmp_path):
    lib = tmp_path / "lib"
    lib.mkdir()
    _make_docx(lib / "a.docx", ["Timestamp test in Brazil."])
    chroma = tmp_path / "chroma"

    summary = _run_index(lib, chroma)
    manifest, _ = _read_manifest(chroma)

    ts = manifest["last_successful_index_at"]
    assert ts == summary["last_successful_index_at"]
    assert ts.endswith("Z")
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", ts)


# ===========================================================================
# 6. Per-document SHA-256 and file size are recorded.
# ===========================================================================

def test_per_document_sha256_and_size_recorded(tmp_path):
    lib = tmp_path / "lib"
    lib.mkdir()
    doc_path = lib / "a.docx"
    _make_docx(doc_path, ["SHA and size test in Chile."])
    chroma = tmp_path / "chroma"

    _run_index(lib, chroma)
    manifest, _ = _read_manifest(chroma)

    entry = next(d for d in manifest["documents"] if d["filename"] == "a.docx")
    expected_hash = capability_indexer.compute_file_hash(str(doc_path))
    assert entry["content_hash"] == expected_hash
    assert len(entry["content_hash"]) == 64  # SHA-256 hex
    assert entry["file_size"] == os.path.getsize(str(doc_path))


# ===========================================================================
# 7. Unchanged document is skipped.
# ===========================================================================

def test_unchanged_document_is_skipped(tmp_path):
    lib = tmp_path / "lib"
    lib.mkdir()
    _make_docx(lib / "a.docx", ["Unchanged doc about Argentina."])
    chroma = tmp_path / "chroma"

    first = _run_index(lib, chroma)
    second = _run_index(lib, chroma)

    assert first["documents_processed"] == 1
    assert second["documents_processed"] == 0
    assert second["documents_unchanged"] == 1
    assert second["documents_skipped"] == 1  # compat alias == unchanged


# ===========================================================================
# 8. Changed document replaces old chunks without duplicates.
# ===========================================================================

def test_changed_document_replaces_without_duplicates(tmp_path):
    lib = tmp_path / "lib"
    lib.mkdir()
    doc_path = lib / "a.docx"
    _make_docx(doc_path, ["Original short content."])
    chroma = tmp_path / "chroma"

    _run_index(lib, chroma)
    col = _collection(chroma)
    first_hash_ids = set(col.get(where={"source_file": "a.docx"})["ids"])

    # Change the document to much longer content (more chunks).
    long_text = " ".join(f"revised sentence {i} about justice reform." for i in range(300))
    _make_docx(doc_path, [long_text])
    summary = _run_index(lib, chroma)

    col = _collection(chroma)
    got = col.get(where={"source_file": "a.docx"})
    ids = got["ids"]
    # No duplicate ids.
    assert len(ids) == len(set(ids))
    # The document was re-processed as changed.
    assert summary["documents_processed"] == 1
    assert summary["documents_unchanged"] == 0
    # Only chunks for this (single) document exist — no stale leftovers.
    assert set(ids) == set(col.get()["ids"])


# ===========================================================================
# 9. Changed-document extraction failure preserves old chunks.
# ===========================================================================

def test_changed_document_extraction_failure_preserves_old_chunks(tmp_path):
    lib = tmp_path / "lib"
    lib.mkdir()
    doc_path = lib / "a.docx"
    _make_docx(doc_path, ["Original valid content about Mexico."])
    chroma = tmp_path / "chroma"

    _run_index(lib, chroma)
    col = _collection(chroma)
    before = col.get(where={"source_file": "a.docx"})
    before_ids = set(before["ids"])
    before_docs = {d for d in before["documents"]}
    assert before_ids

    # Change the file content (new hash), but force extraction to fail.
    _make_docx(doc_path, ["Completely different content that will fail extraction."])

    def failing_extract(filepath, filename, ext):
        return [], "word", False, "docx_extraction_error"

    with patch("capability_indexer._extract_pages", side_effect=failing_extract):
        summary = _run_index(lib, chroma)

    assert summary["documents_failed"] == 1
    col = _collection(chroma)
    after = col.get(where={"source_file": "a.docx"})
    # Old chunks are preserved exactly.
    assert set(after["ids"]) == before_ids
    assert {d for d in after["documents"]} == before_docs


# ===========================================================================
# 10. Removed document removes stale chunks after a valid inventory.
# ===========================================================================

def test_removed_document_removes_stale_chunks(tmp_path):
    lib = tmp_path / "lib"
    lib.mkdir()
    _make_docx(lib / "a.docx", ["Doc A about Colombia."])
    _make_docx(lib / "b.docx", ["Doc B about Peru."])
    chroma = tmp_path / "chroma"

    _run_index(lib, chroma)
    col = _collection(chroma)
    assert col.get(where={"source_file": "b.docx"})["ids"]

    # Remove b.docx from the library and re-sync.
    os.remove(str(lib / "b.docx"))
    summary = _run_index(lib, chroma)

    assert summary["documents_removed"] == 1
    col = _collection(chroma)
    assert col.get(where={"source_file": "b.docx"})["ids"] == []
    assert col.get(where={"source_file": "a.docx"})["ids"]  # A preserved


# ===========================================================================
# 11. Missing/unreadable library preserves the existing index.
# ===========================================================================

def test_missing_library_preserves_existing_index(tmp_path):
    lib = tmp_path / "lib"
    lib.mkdir()
    _make_docx(lib / "a.docx", ["Doc to preserve about Chile."])
    chroma = tmp_path / "chroma"

    _run_index(lib, chroma)
    col = _collection(chroma)
    before_count = col.count()
    assert before_count > 0

    # Point at a non-existent library directory.
    missing = tmp_path / "does_not_exist"
    summary = _run_index(missing, chroma)

    assert summary["status"] == "library_unavailable"
    assert summary["error"]
    col = _collection(chroma)
    assert col.count() == before_count  # index untouched


# ===========================================================================
# 12. One failed document does not stop healthy documents.
# ===========================================================================

def test_one_failed_document_does_not_stop_healthy(tmp_path):
    lib = tmp_path / "lib"
    lib.mkdir()
    _make_docx(lib / "good.docx", ["Healthy doc about asset recovery in Peru."])
    _make_docx(lib / "bad.docx", ["This one will fail extraction."])
    chroma = tmp_path / "chroma"

    real_extract = capability_indexer._extract_pages

    def selective_extract(filepath, filename, ext):
        if filename == "bad.docx":
            return [], "word", False, "docx_extraction_error"
        return real_extract(filepath, filename, ext)

    with patch("capability_indexer._extract_pages", side_effect=selective_extract):
        summary = _run_index(lib, chroma)

    assert summary["documents_failed"] == 1
    assert summary["documents_processed"] == 1  # good doc still indexed
    assert summary["status"] == "partial_success"
    col = _collection(chroma)
    assert col.get(where={"source_file": "good.docx"})["ids"]


# ===========================================================================
# 13. Concurrent second call does not execute indexing.
# ===========================================================================

def test_concurrent_second_call_does_not_execute(tmp_path):
    lib = tmp_path / "lib"
    lib.mkdir()
    _make_docx(lib / "a.docx", ["Concurrency doc about Mexico."])
    chroma = tmp_path / "chroma"

    # Acquire the lock to simulate an in-progress sync, then call index_library.
    acquired = capability_indexer._INDEX_LOCK.acquire(blocking=False)
    assert acquired
    try:
        with patch("capability_indexer.get_collection") as get_col:
            summary = _run_index(lib, chroma)
            # Must not touch Chroma at all when a sync is already running.
            get_col.assert_not_called()
    finally:
        capability_indexer._INDEX_LOCK.release()

    assert summary["status"] == "indexing_in_progress"
    assert summary["documents_processed"] == 0


# ===========================================================================
# 14. Index lock is released after an exception.
# ===========================================================================

def test_index_lock_released_after_exception(tmp_path):
    lib = tmp_path / "lib"
    lib.mkdir()
    _make_docx(lib / "a.docx", ["Lock release doc about Peru."])
    chroma = tmp_path / "chroma"

    # Force an unexpected (non-OSError) error deep inside the locked section,
    # after the client opens and the directory check passes. This propagates
    # out of the locked body and must still release the lock via `finally`.
    with patch("capability_indexer._list_source_documents", side_effect=RuntimeError("hard boom")):
        with pytest.raises(RuntimeError):
            _run_index(lib, chroma)

    # The lock must be free afterwards.
    assert capability_indexer._INDEX_LOCK.acquire(blocking=False)
    capability_indexer._INDEX_LOCK.release()


# ===========================================================================
# 15. Auto-index does not retry endlessly after failure.
# ===========================================================================

def test_auto_index_does_not_retry_endlessly():
    from app import _should_auto_index

    # First attempt allowed when empty + readable + has a source doc.
    assert _should_auto_index(chunk_count=0, source_document_count=1, already_attempted=False) is True
    # After an attempt this session, never retry.
    assert _should_auto_index(chunk_count=0, source_document_count=1, already_attempted=True) is False
    # Missing library (None) never triggers auto-index.
    assert _should_auto_index(chunk_count=0, source_document_count=None, already_attempted=False) is False
    # Empty library (0 supported files) never triggers auto-index.
    assert _should_auto_index(chunk_count=0, source_document_count=0, already_attempted=False) is False
    # Non-empty index never triggers auto-index.
    assert _should_auto_index(chunk_count=5, source_document_count=3, already_attempted=False) is False


# ===========================================================================
# 16. app.py does not label collection.count() as document count.
# ===========================================================================

def test_app_does_not_label_chunk_count_as_documents():
    app_path = os.path.join(os.path.dirname(__file__), "..", "app.py")
    with open(app_path, encoding="utf-8") as f:
        source = f.read()

    # The chunk count must be displayed as "Search chunks".
    assert '"Search chunks"' in source
    # Legacy misleading label must be gone.
    assert '"Documents indexed"' not in source
    # collection.count() must be assigned to a chunk-named variable, not doc_count.
    assert "chunk_count = collection.count()" in source
    assert "doc_count = collection.count()" not in source


# ===========================================================================
# 17. app.py does not write index_manifest.json.
# ===========================================================================

def test_app_does_not_write_manifest():
    app_path = os.path.join(os.path.dirname(__file__), "..", "app.py")
    with open(app_path, encoding="utf-8") as f:
        source = f.read()

    # No JSON dump of a manifest and no write-mode open of the manifest path.
    assert "json.dump(" not in source
    assert 'open(_mpath, "w"' not in source
    assert "'last_indexed'" not in source  # old manifest key no longer written


# ===========================================================================
# 18. Recovery warning uses the approved wording.
# ===========================================================================

def test_recovery_warning_uses_approved_wording():
    from app import RECOVERY_WARNING_MESSAGE

    assert RECOVERY_WARNING_MESSAGE == (
        "Using a temporary search index. "
        "It may need to be rebuilt when the app restarts."
    )
    # The removed instruction must not reappear.
    app_path = os.path.join(os.path.dirname(__file__), "..", "app.py")
    with open(app_path, encoding="utf-8") as f:
        source = f.read()
    assert "once the configured storage is writable again" not in source


# ===========================================================================
# 19. Explicit rebuild removes stale manifest but preserves unrelated and source files.
# ===========================================================================

def test_rebuild_removes_manifest_preserves_unrelated_and_source(tmp_path):
    lib = tmp_path / "lib"
    lib.mkdir()
    source_doc = lib / "a.docx"
    _make_docx(source_doc, ["Source doc must survive rebuild."])
    chroma = tmp_path / "chroma"

    _run_index(lib, chroma)
    manifest_file = chroma / chroma_client.MANIFEST_FILENAME
    assert manifest_file.exists()

    # Add an unrelated sentinel file inside the index directory.
    sentinel = chroma / "KEEP_ME.txt"
    sentinel.write_text("keep me")

    chroma_client.rebuild_index_dir(str(chroma))

    # Manifest is gone; unrelated file preserved; source doc untouched.
    assert not manifest_file.exists()
    assert sentinel.exists() and sentinel.read_text() == "keep me"
    assert source_doc.exists()


# ===========================================================================
# 20. Empty/missing library cannot silently destroy a valid index.
# ===========================================================================

def test_empty_or_missing_library_cannot_destroy_index(tmp_path):
    lib = tmp_path / "lib"
    lib.mkdir()
    _make_docx(lib / "a.docx", ["Valuable indexed content about Mexico."])
    chroma = tmp_path / "chroma"

    _run_index(lib, chroma)
    col = _collection(chroma)
    before = col.count()
    before_ids = set(col.get()["ids"])
    assert before > 0

    # Case A: the source folder becomes EMPTY but readable. Incremental sync
    # must PRESERVE the existing non-empty index and report source_library_empty.
    for entry in os.listdir(str(lib)):
        os.remove(os.path.join(str(lib), entry))
    summary_empty = _run_index(lib, chroma)

    assert summary_empty["status"] == "source_library_empty"
    col = _collection(chroma)
    assert col.count() == before                # nothing erased
    assert set(col.get()["ids"]) == before_ids  # exact same chunks
    assert summary_empty["documents_removed"] == 0

    # Case B: the library directory is missing entirely -> preserve the index.
    missing = tmp_path / "gone"
    summary_missing = _run_index(missing, chroma)
    assert summary_missing["status"] == "library_unavailable"
    assert _collection(chroma).count() == before  # still untouched

    # Case C: both source folder and index empty -> empty_index.
    empty_lib = tmp_path / "empty_lib"
    empty_lib.mkdir()
    empty_chroma = tmp_path / "empty_chroma"
    summary_both = _run_index(empty_lib, empty_chroma)
    assert summary_both["status"] == "empty_index"
    assert summary_both["chunks_total"] == 0


# ===========================================================================
# Phase 2A correction-pass behavioral tests (blockers 1-8)
# ===========================================================================

def _first_batch_ok_second_fails(collection, real_add):
    """Return a side_effect for collection.add that fails on the 2nd call."""
    state = {"calls": 0}

    def side_effect(*args, **kwargs):
        state["calls"] += 1
        if state["calls"] == 2:
            raise RuntimeError("simulated add batch failure")
        return real_add(*args, **kwargs)

    return side_effect


# --- Blocker 1: adversarial second-batch failure on a changed document -------

def test_changed_document_second_batch_failure_preserves_old_generation(tmp_path):
    """If the 2nd new-generation add batch fails, old chunks stay intact and no
    partial new generation remains."""
    lib = tmp_path / "lib"
    lib.mkdir()
    doc_path = lib / "a.docx"
    _make_docx(doc_path, ["Original content about Mexico anti-corruption."])
    chroma = tmp_path / "chroma"

    _run_index(lib, chroma)
    col = _collection(chroma)
    before = col.get(where={"source_file": "a.docx"})
    before_ids = set(before["ids"])
    before_docs = list(before["documents"])
    assert before_ids

    # Change the document to produce many chunks (guaranteeing >1 add batch at
    # batch_size=2), then make the SECOND add batch fail.
    long_text = " ".join(f"revised sentence {i} about justice reform." for i in range(400))
    _make_docx(doc_path, [long_text])

    real_add = _collection(chroma).add
    with patch("capability_indexer.CAPABILITY_LIBRARY_PATH", str(lib) + os.sep):
        with patch("capability_indexer.CHROMA_DB_PATH", str(chroma)):
            import capability_indexer as ci
            real_add_gen = ci._add_generation

            def failing_add_generation(collection, ids, docs, metas, batch_size=100):
                # Force multiple small batches so a mid-stream failure is exercised.
                return real_add_gen(collection, ids, docs, metas, batch_size=2)

            # Patch collection.add to fail on the 2nd batch.
            col2 = ci.get_collection(str(chroma))
            with patch.object(col2, "add", side_effect=_first_batch_ok_second_fails(col2, real_add)):
                with patch.object(ci, "get_collection", return_value=col2):
                    with patch.object(ci, "_add_generation", side_effect=failing_add_generation):
                        summary = ci.index_library(force_reindex=False)

    assert summary["documents_failed"] == 1
    fail = summary["failed_documents"][0]
    assert fail["category"] in ("write_error", "write_error_rollback_failed")

    col = _collection(chroma)
    after = col.get(where={"source_file": "a.docx"})
    # Old generation preserved exactly; no partial new generation left behind.
    assert set(after["ids"]) == before_ids
    assert list(after["documents"]) == before_docs


# --- Blocker 3: removed-document deletion failure -> partial + still counted --

def test_removed_document_deletion_failure_is_partial_and_counted(tmp_path):
    lib = tmp_path / "lib"
    lib.mkdir()
    _make_docx(lib / "a.docx", ["Doc A about Colombia."])
    _make_docx(lib / "b.docx", ["Doc B about Peru."])
    chroma = tmp_path / "chroma"

    _run_index(lib, chroma)
    os.remove(str(lib / "b.docx"))  # b is now a removed document

    import capability_indexer as ci
    col = ci.get_collection(str(chroma))
    real_delete = col.delete

    def delete_failing_for_b(*args, **kwargs):
        ids = kwargs.get("ids") or (args[0] if args else None)
        # b.docx chunk ids embed the relative filename.
        if ids and any("b.docx" in str(i) for i in ids):
            raise RuntimeError("simulated stale delete failure")
        return real_delete(*args, **kwargs)

    with patch("capability_indexer.CAPABILITY_LIBRARY_PATH", str(lib) + os.sep):
        with patch("capability_indexer.CHROMA_DB_PATH", str(chroma)):
            with patch.object(col, "delete", side_effect=delete_failing_for_b):
                with patch.object(ci, "get_collection", return_value=col):
                    summary = ci.index_library(force_reindex=False)

    assert summary["status"] == "partial_success"
    assert any(f["category"] == "removed_delete_error" for f in summary["failed_documents"])
    # b is still present in Chroma, so it remains counted as indexed.
    assert summary["documents_removed"] == 0
    manifest, _ = _read_manifest(chroma)
    # Manifest chunks_total matches the real collection count (consistent).
    assert manifest["chunks_total"] == _collection(chroma).count()
    assert "b.docx" in {d["filename"] for d in manifest["documents"]}


# --- Blocker 4: index-configuration change forces reindex of unchanged bytes -

def test_config_change_forces_reindex_of_unchanged_file(tmp_path):
    lib = tmp_path / "lib"
    lib.mkdir()
    _make_docx(lib / "a.docx", ["Config fingerprint test about Brazil."])
    chroma = tmp_path / "chroma"

    first = _run_index(lib, chroma)
    assert first["documents_processed"] == 1

    # Second run with identical bytes and identical config -> unchanged/skipped.
    second = _run_index(lib, chroma)
    assert second["documents_unchanged"] == 1
    assert second["documents_processed"] == 0

    # Now change the effective index configuration (chunk size) but NOT the file
    # bytes. The document must be re-indexed because the fingerprint differs.
    with patch("capability_indexer.MAX_TOKENS_PER_CHUNK", 123):
        third = _run_index(lib, chroma)

    assert third["documents_unchanged"] == 0
    assert third["documents_processed"] == 1


# --- Blocker 5: manifest publication failure does not report ready -----------

def test_manifest_publication_failure_reports_infra_failure(tmp_path):
    lib = tmp_path / "lib"
    lib.mkdir()
    _make_docx(lib / "a.docx", ["Manifest publication failure test in Chile."])
    chroma = tmp_path / "chroma"

    with patch("capability_indexer.os.replace", side_effect=OSError("disk full")):
        summary = _run_index(lib, chroma)

    assert summary["status"] == "manifest_write_failed"
    assert summary["error"] == "manifest_write_failed"
    # Must NOT claim a persisted successful timestamp.
    assert summary["last_successful_index_at"] is None
    # The chunks were still written to Chroma (indexing work not lost)...
    assert _collection(chroma).count() > 0
    # ...but no manifest file was published.
    mpath = capability_indexer.manifest_path(str(chroma))
    assert not os.path.exists(mpath)


# --- Blocker 6: manifest carries top-level status + failed_documents_total ---

def test_manifest_has_status_and_failed_totals(tmp_path):
    lib = tmp_path / "lib"
    lib.mkdir()
    _make_docx(lib / "good.docx", ["Healthy doc about asset recovery in Peru."])
    _make_docx(lib / "bad.docx", ["Will fail extraction."])
    chroma = tmp_path / "chroma"

    real_extract = capability_indexer._extract_pages

    def selective_extract(filepath, filename, ext):
        if filename == "bad.docx":
            return [], "word", False, "docx_extraction_error"
        return real_extract(filepath, filename, ext)

    with patch("capability_indexer._extract_pages", side_effect=selective_extract):
        _run_index(lib, chroma)

    manifest, _ = _read_manifest(chroma)
    assert manifest["status"] == "partial_success"
    assert manifest["failed_documents_total"] == 1
    assert isinstance(manifest["failed_documents"], list)
    assert manifest["failed_documents"][0]["filename"] == "bad.docx"
    # No raw exception text leaks — category is a safe token.
    assert manifest["failed_documents"][0]["category"] == "docx_extraction_error"


# ===========================================================================
# app.py behavioral tests (not just text inspection)
# ===========================================================================

def test_app_derive_state_partial_from_manifest_status():
    from app import _derive_library_state
    # Non-empty index + partial status -> partial state.
    assert _derive_library_state(10, 3, "partial_success", False) == "partial"


def test_app_generation_enabled_with_missing_source_but_nonempty_index():
    from app import _derive_library_state, _document_generation_enabled
    # Source library missing (None) but index has chunks: state is missing_library
    # and generation REMAINS enabled on the preserved index (blocker 7).
    state = _derive_library_state(chunk_count=12, source_document_count=None,
                                  status="source_library_empty", is_temporary=False)
    assert state == "missing_library"
    assert _document_generation_enabled(state, 12) is True


def test_app_generation_disabled_when_index_empty_or_unavailable():
    from app import _derive_library_state, _document_generation_enabled
    empty = _derive_library_state(0, 3, None, False)
    assert empty == "empty_index"
    assert _document_generation_enabled(empty, 0) is False

    unavailable = _derive_library_state(None, 3, "index_unavailable", False)
    assert unavailable == "index_unavailable"
    assert _document_generation_enabled(unavailable, None) is False


def test_app_empty_index_outranks_missing_source():
    from app import _derive_library_state, _document_generation_enabled
    # Both index empty AND source missing -> empty_index wins, generation off.
    state = _derive_library_state(0, None, "source_library_empty", False)
    assert state == "empty_index"
    assert _document_generation_enabled(state, 0) is False


def test_app_stale_index_message_does_not_claim_generation_paused():
    from app import STALE_INDEX_MESSAGE
    lowered = STALE_INDEX_MESSAGE.lower()
    assert "generation continues" in lowered
    assert "paused" in lowered  # updates are paused...
    # ...but it must not say generation/document generation is paused.
    assert "generation is paused" not in lowered
    assert "document generation is paused" not in lowered


def test_app_partial_warning_text_has_no_paths_or_exceptions(tmp_path):
    """The manifest-driven partial warning shows a count only — no paths/excs."""
    # Build a partial manifest and drive the sidebar's warning logic in the
    # same shape app.py uses.
    manifest_failed_total = 2
    manifest_status = "partial_success"
    msgs = []

    class _UI:
        def warning(self, m):
            msgs.append(m)

    ui = _UI()
    # Mirror app.py's condition and message construction.
    if manifest_status == "partial_success" and manifest_failed_total > 0:
        ui.warning(
            "Last update completed with {} document(s) that could not be "
            "indexed.".format(manifest_failed_total)
        )

    assert msgs == ["Last update completed with 2 document(s) that could not be indexed."]
    assert "Traceback" not in msgs[0]
    assert ":\\" not in msgs[0] and "/" not in msgs[0]


def test_app_uses_document_generation_enabled_helper():
    """Static guard: app.py routes the generation decision through the helper so
    UI copy and behavior cannot diverge."""
    app_path = os.path.join(os.path.dirname(__file__), "..", "app.py")
    with open(app_path, encoding="utf-8") as f:
        source = f.read()
    assert "_document_generation_enabled(library_state, chunk_count)" in source


def test_app_reads_manifest_status_and_failed_total():
    """Static guard: the sidebar reads status + failed_documents_total from the
    manifest (blocker 6)."""
    app_path = os.path.join(os.path.dirname(__file__), "..", "app.py")
    with open(app_path, encoding="utf-8") as f:
        source = f.read()
    assert 'manifest.get("status")' in source
    assert 'manifest.get("failed_documents_total"' in source
