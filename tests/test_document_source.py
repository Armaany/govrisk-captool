from types import SimpleNamespace
from unittest.mock import mock_open, patch

import pytest

from document_source import (
    DocumentSourceError,
    SessionUploadDocumentSource,
    prepare_source_documents,
    safe_upload_name,
)


def _upload(name, content=b"document bytes"):
    return SimpleNamespace(name=name, getvalue=lambda: content)


def test_safe_upload_name_removes_paths_and_rejects_unsupported_types():
    assert safe_upload_name(r"C:\private\report.PDF") == "report.pdf"
    assert safe_upload_name("../../regional.docx") == "regional.docx"
    with pytest.raises(DocumentSourceError, match="Only PDF and DOCX"):
        safe_upload_name("secrets.txt")


def test_prepare_documents_rejects_duplicate_names_case_insensitively():
    with pytest.raises(DocumentSourceError, match="filenames must be unique"):
        prepare_source_documents((_upload("Report.pdf"), _upload("report.PDF")))


def test_prepare_documents_records_hash_size_and_safe_identity():
    documents = prepare_source_documents((_upload("folder/evidence.pdf", b"abc"),))
    assert documents[0].source_id == "evidence.pdf"
    assert documents[0].display_name == "evidence.pdf"
    assert documents[0].size_bytes == 3
    assert len(documents[0].sha256) == 64


def test_session_workspace_identity_changes_with_content(monkeypatch):
    captured = []

    def fake_local(library_id, display_name, source_path, workspace_root, source_type):
        captured.append((library_id, source_path, workspace_root, source_type))
        return library_id

    monkeypatch.setattr("document_source.local_folder_workspace", fake_local)
    with patch("document_source.Path.mkdir"), patch(
        "document_source.Path.exists", return_value=False
    ), patch("document_source.Path.open", mock_open()):
        first = SessionUploadDocumentSource("session", (_upload("one.pdf", b"one"),)).materialize()
        second = SessionUploadDocumentSource("session", (_upload("one.pdf", b"two"),)).materialize()

    assert first != second
    assert first.startswith("session-")
    assert len(captured) == 2
    assert all(item[3] == "session_upload" for item in captured)


def test_empty_upload_set_is_rejected_before_any_workspace_write():
    with pytest.raises(DocumentSourceError, match="Upload at least one"):
        SessionUploadDocumentSource("session", ()).materialize()
