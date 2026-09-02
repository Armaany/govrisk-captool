"""Tests for the defensive ChromaDB client factory.

Covers:
- Fresh writable index directory initializes and supports add/count/query.
- Distinguish fresh-index success from an existing-index open.
- Writability detection.
- Deterministic mocked recovery: configured client fails, recovery succeeds.
- Recovery uses a genuinely fresh, process-specific directory.
- Subsequent calls reuse the resolved recovery directory.
- Both failures raise ChromaUnavailableError containing both messages.
- Client init never invokes the clear/rebuild helper.
- Explicit rebuild removes recognized Chroma artifacts and preserves others.
- Unsafe/broad rebuild targets are rejected.
- Empty capability library behavior (count == 0).
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import patch

import chroma_client
from chroma_client import (
    ChromaUnavailableError,
    UnsafeRebuildTargetError,
    get_client,
    get_collection,
    rebuild_index_dir,
    resolve_persist_dir,
    _dir_is_writable,
    _is_recognized_chroma_artifact,
)


@pytest.fixture(autouse=True)
def _reset_module_state():
    """Each test starts with clean module-level caches."""
    chroma_client._RESOLVED_PERSIST_DIR = {}
    chroma_client._RECOVERY_DIR = None
    yield
    chroma_client._RESOLVED_PERSIST_DIR = {}
    chroma_client._RECOVERY_DIR = None


# ---------------------------------------------------------------------------
# Real-client behaviour (small, fast, local)
# ---------------------------------------------------------------------------

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
    chroma_client._RESOLVED_PERSIST_DIR = {}
    col2 = get_collection(persist)
    assert col2.count() == 1  # existing-index open, data preserved


def test_writability_detection_true_for_tmp(tmp_path):
    assert _dir_is_writable(str(tmp_path / "w")) is True


def test_resolve_prefers_configured_when_writable(tmp_path):
    configured = str(tmp_path / "configured")
    resolved = resolve_persist_dir(configured)
    assert os.path.abspath(resolved) == os.path.abspath(configured)


def test_empty_library_count_is_zero(tmp_path):
    col = get_collection(str(tmp_path / "empty_lib"))
    assert col.count() == 0


# ---------------------------------------------------------------------------
# Deterministic mocked recovery behaviour
# ---------------------------------------------------------------------------

class _FakeClient:
    def __init__(self, path):
        self.path = path


def test_configured_fails_recovery_succeeds(tmp_path):
    """Configured client raises; recovery client on a fresh dir succeeds."""
    configured = str(tmp_path / "configured")

    calls = []

    def fake_try_client(path):
        calls.append(os.path.abspath(path))
        # First call is the configured dir -> fail. Recovery dir -> succeed.
        if os.path.abspath(path) == os.path.abspath(configured):
            raise RuntimeError("configured boom")
        return _FakeClient(path)

    with patch.object(chroma_client, "_try_client", side_effect=fake_try_client):
        client = get_client(configured)

    assert isinstance(client, _FakeClient)
    # It recovered onto a directory other than the configured one.
    assert os.path.abspath(client.path) != os.path.abspath(configured)
    assert len(calls) == 2


def test_recovery_uses_genuinely_fresh_process_specific_dir(tmp_path):
    """The recovery directory embeds the pid and is not the configured path."""
    configured = str(tmp_path / "configured")

    def fake_try_client(path):
        if os.path.abspath(path) == os.path.abspath(configured):
            raise RuntimeError("configured boom")
        return _FakeClient(path)

    with patch.object(chroma_client, "_try_client", side_effect=fake_try_client):
        client = get_client(configured)

    recovery_path = os.path.abspath(client.path)
    assert str(os.getpid()) in recovery_path
    assert "govrisk_chroma_recovery" in recovery_path
    assert recovery_path != os.path.abspath(configured)


def test_subsequent_calls_reuse_resolved_recovery_dir(tmp_path):
    """After recovery, later get_client calls reuse the same recovery dir."""
    configured = str(tmp_path / "configured")
    seen_paths = []

    def fake_try_client(path):
        seen_paths.append(os.path.abspath(path))
        if os.path.abspath(path) == os.path.abspath(configured):
            raise RuntimeError("configured boom")
        return _FakeClient(path)

    with patch.object(chroma_client, "_try_client", side_effect=fake_try_client):
        first = get_client(configured)
        second = get_client(configured)

    assert os.path.abspath(first.path) == os.path.abspath(second.path)
    # The cached recovery dir is reused on the second call (no re-attempt of the
    # failing configured path).
    assert seen_paths[-1] == os.path.abspath(first.path)


def test_both_failures_raise_with_both_messages(tmp_path):
    """When configured AND recovery both fail, both messages are surfaced."""
    configured = str(tmp_path / "configured")

    def fake_try_client(path):
        if os.path.abspath(path) == os.path.abspath(configured):
            raise RuntimeError("configured boom")
        raise RuntimeError("recovery boom")

    with patch.object(chroma_client, "_try_client", side_effect=fake_try_client):
        with pytest.raises(ChromaUnavailableError) as excinfo:
            get_client(configured)

    message = str(excinfo.value)
    assert "configured boom" in message
    assert "recovery boom" in message


def test_client_init_never_calls_clear_or_rebuild(tmp_path):
    """get_client must never invoke the destructive clear helper."""
    configured = str(tmp_path / "configured")

    def fake_try_client(path):
        if os.path.abspath(path) == os.path.abspath(configured):
            raise RuntimeError("configured boom")
        return _FakeClient(path)

    with patch.object(chroma_client, "_try_client", side_effect=fake_try_client):
        with patch.object(
            chroma_client, "_safe_clear_generated_index"
        ) as clear_spy:
            get_client(configured)
            clear_spy.assert_not_called()


# ---------------------------------------------------------------------------
# Explicit rebuild safety
# ---------------------------------------------------------------------------

def test_rebuild_removes_recognized_chroma_artifacts(tmp_path):
    persist = tmp_path / "gen_index"
    persist.mkdir()
    (persist / "chroma.sqlite3").write_text("index-data")
    seg = persist / "12345678-1234-1234-1234-1234567890ab"
    seg.mkdir()
    (seg / "data.bin").write_text("vectors")

    rebuild_index_dir(str(persist))

    assert not (persist / "chroma.sqlite3").exists()
    assert not seg.exists()


def test_rebuild_preserves_unrelated_sentinel_files(tmp_path):
    persist = tmp_path / "gen_index2"
    persist.mkdir()
    (persist / "chroma.sqlite3").write_text("index-data")
    sentinel = persist / "IMPORTANT_README.txt"
    sentinel.write_text("keep me")
    other = persist / "notes"
    other.mkdir()
    (other / "note.md").write_text("keep me too")

    rebuild_index_dir(str(persist))

    assert not (persist / "chroma.sqlite3").exists()
    assert sentinel.exists()
    assert sentinel.read_text() == "keep me"
    assert (other / "note.md").exists()


def test_rebuild_rejects_unsafe_broad_targets(tmp_path):
    # Filesystem/drive root.
    root = os.path.abspath(os.sep)
    with pytest.raises(UnsafeRebuildTargetError):
        chroma_client._safe_clear_generated_index(root)

    # Home directory.
    with pytest.raises(UnsafeRebuildTargetError):
        chroma_client._safe_clear_generated_index(os.path.expanduser("~"))


def test_rebuild_rejects_capability_library_dir(tmp_path):
    library = tmp_path / "cap_lib"
    library.mkdir()
    (library / "source.docx").write_text("SOURCE")
    with patch("config.CAPABILITY_LIBRARY_PATH", str(library)):
        with pytest.raises(UnsafeRebuildTargetError):
            chroma_client._safe_clear_generated_index(str(library))
    # Source document untouched.
    assert (library / "source.docx").read_text() == "SOURCE"


def test_recognized_artifact_matcher():
    assert _is_recognized_chroma_artifact("chroma.sqlite3") is True
    assert _is_recognized_chroma_artifact("12345678-1234-1234-1234-1234567890ab") is True
    assert _is_recognized_chroma_artifact("IMPORTANT_README.txt") is False
    assert _is_recognized_chroma_artifact("notes") is False