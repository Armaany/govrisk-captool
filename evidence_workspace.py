"""Evidence workspace identity and isolated storage configuration."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path


_LIBRARY_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{2,63}$")


@dataclass(frozen=True)
class EvidenceWorkspace:
    """A source library paired with an isolated generated search index."""

    library_id: str
    display_name: str
    source_path: str
    persist_path: str
    collection_name: str
    source_type: str = "local_folder"


def validate_library_id(library_id: str) -> str:
    """Validate and return a path-safe, stable evidence-library identifier."""
    value = str(library_id or "").strip().lower()
    if not _LIBRARY_ID_PATTERN.fullmatch(value):
        raise ValueError(
            "library_id must be 3-64 lowercase characters using only letters, "
            "numbers, hyphens, or underscores"
        )
    return value


def collection_name_for_library(library_id: str) -> str:
    """Return a Chroma-safe collection name without leaking the library name."""
    stable_id = validate_library_id(library_id)
    digest = hashlib.sha256(stable_id.encode("utf-8")).hexdigest()[:24]
    return f"evidence_{digest}"


def local_folder_workspace(
    library_id: str,
    display_name: str,
    source_path: str,
    workspace_root: str = "./evidence_workspaces",
    source_type: str = "local_folder",
) -> EvidenceWorkspace:
    """Build an isolated workspace for a read-only local source folder."""
    stable_id = validate_library_id(library_id)
    source = str(Path(source_path).expanduser().resolve())
    root = Path(workspace_root).expanduser().resolve()
    persist = root / stable_id / "chroma_db"
    return EvidenceWorkspace(
        library_id=stable_id,
        display_name=str(display_name or stable_id).strip() or stable_id,
        source_path=source,
        persist_path=str(persist),
        collection_name=collection_name_for_library(stable_id),
        source_type=source_type,
    )


def sync_workspace(workspace: EvidenceWorkspace, force_reindex: bool = False) -> dict:
    """Synchronise one workspace without touching any other library/index."""
    if not isinstance(workspace, EvidenceWorkspace):
        raise TypeError("workspace must be an EvidenceWorkspace")

    # Lazy import avoids making workspace identity depend on Chroma at import
    # time and keeps future non-local source implementations lightweight.
    from capability_indexer import index_library

    return index_library(
        force_reindex=force_reindex,
        library_path=workspace.source_path,
        chroma_db_path=workspace.persist_path,
        collection_name=workspace.collection_name,
    )
