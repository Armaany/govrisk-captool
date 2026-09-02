"""Defensive ChromaDB client factory shared by indexer, retriever, and app.

Background
----------
In some deployed environments (e.g. Streamlit Cloud) ``chromadb`` 1.5.x raises::

    'RustBindingsAPI' object has no attribute 'bindings'

This message is misleading. ``RustBindingsAPI`` assigns ``self.bindings`` only
after its native constructor succeeds, but its ``__del__`` cleanup deletes that
attribute unconditionally. So when the native constructor fails for an *earlier*
reason (most commonly a non-writable persist directory, or an on-disk index
written by an incompatible build), the visible error surfaces during garbage
collection as the missing-``bindings`` ``AttributeError`` and hides the real
cause.

This module makes initialization robust and diagnosable:

1. It resolves and ensures the configured persist directory exists and is
   writable, and reports the earliest underlying exception verbatim.
2. If the configured directory is not usable (read-only, or an existing index
   that fails to open), it falls back to a fresh writable directory so the demo
   can still index and retrieve.
3. It never deletes source documents. A rebuild only clears the *generated*
   index directory, and only when explicitly requested.
"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile

import chromadb

logger = logging.getLogger(__name__)

COLLECTION_NAME = "govrisk_capabilities"

_RESOLVED_PERSIST_DIR = {}


class ChromaUnavailableError(RuntimeError):
    """Raised when no writable ChromaDB persist directory can be established."""


def _dir_is_writable(path):
    """Return True if ``path`` exists (or can be created) and is writable."""
    try:
        os.makedirs(path, exist_ok=True)
    except OSError as exc:
        logger.warning("Cannot create Chroma directory %s: %s", path, exc)
        return False
    if not os.access(path, os.W_OK):
        return False
    probe = os.path.join(path, ".chroma_write_probe")
    try:
        with open(probe, "w", encoding="utf-8") as handle:
            handle.write("ok")
        os.remove(probe)
        return True
    except OSError as exc:
        logger.warning("Chroma directory %s not writable: %s", path, exc)
        return False


def _fallback_dir():
    """A per-user temp directory that is writable in restricted environments."""
    return os.path.join(tempfile.gettempdir(), "govrisk_chroma_index")


def _try_client(path):
    """Construct a PersistentClient, letting the earliest real error propagate."""
    return chromadb.PersistentClient(path=path)


def resolve_persist_dir(configured_path):
    """Return a usable persist directory, preferring the configured one."""
    configured = os.path.abspath(configured_path)
    if _dir_is_writable(configured):
        return configured

    fallback = _fallback_dir()
    logger.warning(
        "Configured Chroma directory is not writable (%s); falling back to %s",
        configured,
        fallback,
    )
    if _dir_is_writable(fallback):
        return fallback

    raise ChromaUnavailableError(
        "No writable ChromaDB directory available. "
        "Tried configured path '{}' and fallback '{}'.".format(configured, fallback)
    )


def _safe_clear_generated_index(persist_dir):
    """Delete only the generated Chroma index files under ``persist_dir``.

    Preserves the separate capability_library source documents, which live in a
    different directory entirely.
    """
    if not os.path.isdir(persist_dir):
        return
    logger.warning("Rebuilding generated Chroma index at %s", persist_dir)
    for entry in os.listdir(persist_dir):
        full = os.path.join(persist_dir, entry)
        try:
            if os.path.isdir(full):
                shutil.rmtree(full, ignore_errors=True)
            else:
                os.remove(full)
        except OSError as exc:
            logger.warning("Could not remove %s during rebuild: %s", full, exc)


def get_client(configured_path):
    """Return a PersistentClient, healing common deployment failures."""
    cache_key = os.path.abspath(configured_path)
    cached = _RESOLVED_PERSIST_DIR.get(cache_key)
    if cached is not None:
        try:
            return _try_client(cached)
        except Exception:
            _RESOLVED_PERSIST_DIR.pop(cache_key, None)

    persist_dir = resolve_persist_dir(configured_path)

    try:
        client = _try_client(persist_dir)
        _RESOLVED_PERSIST_DIR[cache_key] = persist_dir
        return client
    except Exception as first_error:
        logger.warning(
            "ChromaDB failed to open index at %s: %s: %s",
            persist_dir,
            type(first_error).__name__,
            first_error,
        )
        fresh_dir = _fallback_dir()
        if os.path.abspath(fresh_dir) == os.path.abspath(persist_dir):
            _safe_clear_generated_index(fresh_dir)
        if not _dir_is_writable(fresh_dir):
            raise ChromaUnavailableError(
                "ChromaDB could not initialize and no writable fallback "
                "directory is available. Earliest error: {}: {}".format(
                    type(first_error).__name__, first_error
                )
            ) from first_error
        try:
            client = _try_client(fresh_dir)
            _RESOLVED_PERSIST_DIR[cache_key] = fresh_dir
            logger.info("ChromaDB recovered using fresh index dir %s", fresh_dir)
            return client
        except Exception as second_error:
            raise ChromaUnavailableError(
                "ChromaDB initialization failed even with a fresh index "
                "directory. Earliest error: {}: {}. Retry error: {}: {}".format(
                    type(first_error).__name__, first_error,
                    type(second_error).__name__, second_error,
                )
            ) from second_error


def get_collection(configured_path):
    """Return the shared capability collection, healing init failures."""
    client = get_client(configured_path)
    return client.get_or_create_collection(COLLECTION_NAME)


def rebuild_index_dir(configured_path):
    """Explicitly clear the generated index and return the usable directory.

    Preserves source documents (they live under the capability library path,
    not the Chroma directory). Callers should re-run indexing afterwards.
    """
    persist_dir = resolve_persist_dir(configured_path)
    _safe_clear_generated_index(persist_dir)
    _RESOLVED_PERSIST_DIR.pop(os.path.abspath(configured_path), None)
    return persist_dir