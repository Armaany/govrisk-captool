import os

import pytest

import capability_indexer
import chroma_client
from evidence_workspace import (
    collection_name_for_library,
    local_folder_workspace,
    sync_workspace,
    validate_library_id,
)


def test_library_id_rejects_path_traversal_and_unsafe_characters():
    for value in ("../client", "Client Name", "a/b", "x", "", "a" * 65):
        with pytest.raises(ValueError):
            validate_library_id(value)


def test_collection_name_is_stable_and_does_not_expose_library_name():
    first = collection_name_for_library("govrisk-primary")
    second = collection_name_for_library("govrisk-primary")
    other = collection_name_for_library("anna-request")
    assert first == second
    assert first != other
    assert first.startswith("evidence_")
    assert "govrisk" not in first
    assert len(first) >= 3


def test_local_workspaces_have_isolated_persist_paths_and_collections():
    source = os.path.abspath("./source-test-fixture")
    root = os.path.abspath("./workspace-root-test-fixture")

    first = local_folder_workspace("client-one", "Client one", source, root)
    second = local_folder_workspace("client-two", "Client two", source, root)

    assert first.source_path == second.source_path == source
    assert first.persist_path != second.persist_path
    assert first.collection_name != second.collection_name
    assert os.path.commonpath([first.persist_path, root]) == root


def test_sync_workspace_forwards_only_its_isolated_configuration(monkeypatch):
    workspace = local_folder_workspace(
        "client-one",
        "Client one",
        "./source-test-fixture",
        "./workspace-root-test-fixture",
    )
    captured = {}

    def fake_index_library(**kwargs):
        captured.update(kwargs)
        return {"status": "ready"}

    monkeypatch.setattr(capability_indexer, "index_library", fake_index_library)
    assert sync_workspace(workspace, force_reindex=True) == {"status": "ready"}
    assert captured == {
        "force_reindex": True,
        "library_path": workspace.source_path,
        "chroma_db_path": workspace.persist_path,
        "collection_name": workspace.collection_name,
    }


def test_named_collection_is_forwarded_to_chroma_client(monkeypatch):
    captured = {}

    class FakeClient:
        def get_or_create_collection(self, name):
            captured["name"] = name
            return "collection"

    monkeypatch.setattr(chroma_client, "get_client", lambda path: FakeClient())
    assert chroma_client.get_collection("unused", "evidence_123") == "collection"
    assert captured["name"] == "evidence_123"


def test_index_library_defaults_remain_historical_values(monkeypatch):
    captured = {}

    def fake_locked(**kwargs):
        captured.update(kwargs)
        return {"status": "ready"}

    monkeypatch.setattr(capability_indexer, "_index_library_locked", fake_locked)
    result = capability_indexer.index_library()
    assert result == {"status": "ready"}
    assert captured == {
        "force_reindex": False,
        "library_path": None,
        "chroma_db_path": None,
        "collection_name": "govrisk_capabilities",
    }


def test_workspace_namespace_changes_fingerprint_and_chunk_identity():
    default_fp = capability_indexer.index_config_fingerprint()
    workspace_fp = capability_indexer.index_config_fingerprint("evidence_123")
    assert workspace_fp != default_fp

    default_id = capability_indexer.deterministic_chunk_id(
        "same.pdf", "abc", default_fp, 0
    )
    workspace_id = capability_indexer.deterministic_chunk_id(
        "same.pdf", "abc", workspace_fp, 0, identity_namespace="evidence_123"
    )
    assert workspace_id != default_id
    assert workspace_id.startswith("evidence_123::")


def test_default_chunk_identity_remains_backward_compatible():
    assert capability_indexer.deterministic_chunk_id(
        "doc.pdf", "hash", "fingerprint", 7
    ) == "doc.pdf::hash::fingerprint::chunk::000007"
