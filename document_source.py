"""Document-source adapters for isolated evidence workspaces.

The initial implementation supports the established local folder and temporary
Streamlit session uploads. Source files are copied into a generated workspace;
the indexer never modifies the originals.
"""

from __future__ import annotations

import hashlib
import os
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable, Protocol

from evidence_workspace import EvidenceWorkspace, local_folder_workspace


SUPPORTED_EXTENSIONS = frozenset({".docx", ".pdf"})
MAX_UPLOAD_DOCUMENTS = 20
MAX_UPLOAD_BYTES_PER_DOCUMENT = 25 * 1024 * 1024
MAX_UPLOAD_BYTES_TOTAL = 100 * 1024 * 1024


class DocumentSourceError(ValueError):
    """Safe, user-presentable document-source validation failure."""


@dataclass(frozen=True)
class SourceDocument:
    source_id: str
    display_name: str
    content: bytes
    sha256: str
    size_bytes: int


class DocumentSource(Protocol):
    """Contract for materialising read-only documents into one workspace."""

    def materialize(self) -> EvidenceWorkspace:
        ...


def _upload_bytes(upload) -> bytes:
    if hasattr(upload, "getvalue"):
        value = upload.getvalue()
    elif hasattr(upload, "read"):
        value = upload.read()
    else:
        raise DocumentSourceError("An uploaded document could not be read.")
    if not isinstance(value, (bytes, bytearray)):
        raise DocumentSourceError("An uploaded document could not be read.")
    return bytes(value)


def safe_upload_name(value: str) -> str:
    """Return a path-free, cross-platform filename for a supported document."""
    raw = unicodedata.normalize("NFKC", str(value or "")).replace("\\", "/")
    name = PurePosixPath(raw).name.strip().strip(".")
    name = re.sub(r"[\x00-\x1f<>:\"/\\|?*]", "_", name)
    if not name:
        raise DocumentSourceError("Every uploaded document must have a filename.")
    stem, extension = os.path.splitext(name)
    extension = extension.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise DocumentSourceError("Only PDF and DOCX evidence documents are supported.")
    stem = stem.strip().strip(".") or "document"
    # Keep enough room for the extension and avoid problematic Windows paths.
    return stem[:110] + extension


def prepare_source_documents(uploads: Iterable) -> list[SourceDocument]:
    """Validate uploads and convert them into immutable source records."""
    items = list(uploads or [])
    if not items:
        raise DocumentSourceError("Upload at least one PDF or DOCX document.")
    if len(items) > MAX_UPLOAD_DOCUMENTS:
        raise DocumentSourceError(f"Upload no more than {MAX_UPLOAD_DOCUMENTS} documents at once.")

    documents = []
    seen_names = set()
    total = 0
    for upload in items:
        name = safe_upload_name(getattr(upload, "name", ""))
        key = name.casefold()
        if key in seen_names:
            raise DocumentSourceError(
                "Uploaded document filenames must be unique within a workspace."
            )
        seen_names.add(key)
        content = _upload_bytes(upload)
        size = len(content)
        if size == 0:
            raise DocumentSourceError(f"{name} is empty.")
        if size > MAX_UPLOAD_BYTES_PER_DOCUMENT:
            raise DocumentSourceError(
                f"{name} exceeds the {MAX_UPLOAD_BYTES_PER_DOCUMENT // (1024 * 1024)} MB limit."
            )
        total += size
        if total > MAX_UPLOAD_BYTES_TOTAL:
            raise DocumentSourceError(
                f"The upload exceeds the {MAX_UPLOAD_BYTES_TOTAL // (1024 * 1024)} MB total limit."
            )
        digest = hashlib.sha256(content).hexdigest()
        documents.append(SourceDocument(name, name, content, digest, size))
    return documents


@dataclass(frozen=True)
class LocalFolderDocumentSource:
    library_id: str
    display_name: str
    source_path: str
    workspace_root: str = "./evidence_workspaces"

    def materialize(self) -> EvidenceWorkspace:
        return local_folder_workspace(
            self.library_id,
            self.display_name,
            self.source_path,
            self.workspace_root,
        )


@dataclass(frozen=True)
class SessionUploadDocumentSource:
    session_token: str
    uploads: tuple
    workspace_root: str = "./evidence_workspaces"

    def materialize(self) -> EvidenceWorkspace:
        documents = prepare_source_documents(self.uploads)
        session_hash = hashlib.sha256(self.session_token.encode("utf-8")).hexdigest()[:12]
        snapshot_raw = "|".join(f"{doc.source_id}:{doc.sha256}" for doc in documents)
        snapshot_hash = hashlib.sha256(snapshot_raw.encode("utf-8")).hexdigest()[:12]
        library_id = f"session-{session_hash}-{snapshot_hash}"

        root = Path(self.workspace_root).expanduser().resolve()
        source_path = (root / "sessions" / library_id / "source").resolve()
        if os.path.commonpath([str(source_path), str(root)]) != str(root):
            raise DocumentSourceError("The temporary workspace path is unsafe.")
        source_path.mkdir(parents=True, exist_ok=True)

        for document in documents:
            target = source_path / document.source_id
            if target.exists():
                if hashlib.sha256(target.read_bytes()).hexdigest() != document.sha256:
                    raise DocumentSourceError("The temporary workspace contains a conflicting file.")
                continue
            with target.open("xb") as handle:
                handle.write(document.content)

        return local_folder_workspace(
            library_id,
            "Temporary uploaded evidence",
            str(source_path),
            str(root),
            source_type="session_upload",
        )
