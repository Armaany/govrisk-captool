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
2. If the configured directory cannot open a client, it retries against a
   genuinely fresh, process-specific recovery directory so the demo can still
   index and retrieve. It NEVER deletes an index automatically.
3. Rebuilding is explicit only, removes only recognized Chroma artifacts, and
   refuses broad/unsafe targets. Source documents are never touched.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import tempfile
import uuid

import chromadb

logger = logging.getLogger(__name__)

COLLECTION_NAME = "govrisk_capabilities"

# Recognized Chroma-generated artifacts. Segment directories are 36-char UUIDs.
_CHROMA_FILE_ARTIFACTS = frozenset(
    {"chroma.sqlite3", "chroma.sqlite3-shm", "chroma.sqlite3-wal", ".chroma_write_probe"}
)
_UUID_SEGMENT_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)

# Cache the directory that actually worked, keyed by the configured path, so
# every consumer in a single process agrees on the same store.
_RESOLVED_PERSIST_DIR = {}

# A single process-specific recovery directory, created lazily and reused for
# the lifetime of the process once established.
_RECOVERY_DIR = None


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


def _recovery_dir():
    """Return a genuinely fresh, process-specific recovery directory.

    The directory name embeds the process id and a random uuid so it never
    collides with a stale index from a previous run. It is created once and
    reused for the remainder of the process.
    """
    global _RECOVERY_DIR
    if _RECOVERY_DIR is not None:
        return _RECOVERY_DIR
    name = "govrisk_chroma_recovery_{}_{}".format(os.getpid(), uuid.uuid4().hex)
    _RECOVERY_DIR = os.path.join(tempfile.gettempdir(), name)
    return _RECOVERY_DIR


def _try_client(path):
    """Construct a PersistentClient, letting the earliest real error propagate."""
    return chromadb.PersistentClient(path=path)


def resolve_persist_dir(configured_path):
    """Return a usable persist directory, preferring the configured one.

    Order of preference:
      1. The configured path, if writable.
      2. The process-specific recovery directory, if the configured path is not
         writable.

    Raises ChromaUnavailableError if neither can be made writable.
    """
    configured = os.path.abspath(configured_path)
    if _dir_is_writable(configured):
        return configured

    recovery = _recovery_dir()
    logger.warning(
        "Configured Chroma directory is not writable (%s); falling back to %s",
        configured,
        recovery,
    )
    if _dir_is_writable(recovery):
        return recovery

    raise ChromaUnavailableError(
        "No writable ChromaDB directory available. "
        "Tried configured path '{}' and recovery '{}'.".format(configured, recovery)
    )


def get_client(configured_path):
    """Return a PersistentClient, healing common deployment failures.

    Never deletes an index automatically. If the configured index cannot open,
    it retries against a genuinely fresh recovery directory. If recovery also
    fails, it raises ChromaUnavailableError carrying BOTH the earliest
    configured-index error and the recovery error.
    """
    cache_key = os.path.abspath(configured_path)
    cached = _RESOLVED_PERSIST_DIR.get(cache_key)
    if cached is not None:
        try:
            return _try_client(cached)
        except Exception as cached_error:
            # Do not discard cached-path errors silently.
            logger.warning(
                "Cached Chroma dir %s failed to reopen: %s: %s",
                cached,
                type(cached_error).__name__,
                cached_error,
            )
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
        # Retry against a genuinely fresh recovery directory. We do NOT delete
        # the configured index; we simply use a clean, empty location.
        recovery = _recovery_dir()
        if os.path.abspath(recovery) == os.path.abspath(persist_dir):
            # The configured path already WAS the recovery dir and it failed;
            # allocate a brand new one so recovery is truly fresh.
            global _RECOVERY_DIR
            _RECOVERY_DIR = None
            recovery = _recovery_dir()

        if not _dir_is_writable(recovery):
            raise ChromaUnavailableError(
                "ChromaDB could not initialize and no writable recovery "
                "directory is available. Configured-index error: {}: {}".format(
                    type(first_error).__name__, first_error
                )
            ) from first_error

        try:
            client = _try_client(recovery)
            _RESOLVED_PERSIST_DIR[cache_key] = recovery
            logger.info("ChromaDB recovered using fresh recovery dir %s", recovery)
            return client
        except Exception as recovery_error:
            raise ChromaUnavailableError(
                "ChromaDB initialization failed. "
                "Configured-index error: {}: {}. "
                "Recovery error: {}: {}".format(
                    type(first_error).__name__, first_error,
                    type(recovery_error).__name__, recovery_error,
                )
            ) from recovery_error


def get_collection(configured_path):
    """Return the shared capability collection, healing init failures."""
    client = get_client(configured_path)
    return client.get_or_create_collection(COLLECTION_NAME)


# ---------------------------------------------------------------------------
# Explicit, guarded rebuild of the generated index only.
# ---------------------------------------------------------------------------

class UnsafeRebuildTargetError(ValueError):
    """Raised when a rebuild target is a broad/unsafe filesystem location."""


def _is_unsafe_rebuild_target(persist_dir):
    """Return True if ``persist_dir`` is a broad/unsafe location to clear.

    Refuses filesystem roots, the user's home directory, and the capability
    library directory (source documents).
    """
    resolved = os.path.abspath(persist_dir)

    # Filesystem root (e.g. "/" or "C:\\").
    if os.path.dirname(resolved) == resolved:
        return True

    # A drive root like "C:\\" on Windows.
    drive, tail = os.path.splitdrive(resolved)
    if drive and tail in ("\\", "/", ""):
        return True

    # Home directory.
    if resolved == os.path.abspath(os.path.expanduser("~")):
        return True

    # The capability-library source-document directory (or a parent of it).
    try:
        from config import CAPABILITY_LIBRARY_PATH

        library = os.path.abspath(CAPABILITY_LIBRARY_PATH)
        if resolved == library or library.startswith(resolved + os.sep):
            return True
    except Exception:  # noqa: BLE001 - config not importable in isolated tests
        pass

    return False


def _is_recognized_chroma_artifact(name):
    """Return True if ``name`` is a recognized Chroma-generated artifact."""
    if name in _CHROMA_FILE_ARTIFACTS:
        return True
    if _UUID_SEGMENT_RE.match(name):
        return True
    return False


def _safe_clear_generated_index(persist_dir):
    """Delete only recognized Chroma-generated artifacts under ``persist_dir``.

    Rejects broad/unsafe targets. Preserves unrelated files. Never touches the
    separate capability_library source documents.
    """
    resolved = os.path.abspath(persist_dir)
    if _is_unsafe_rebuild_target(resolved):
        raise UnsafeRebuildTargetError(
            "Refusing to rebuild an unsafe/broad target: {}".format(resolved)
        )
    if not os.path.isdir(resolved):
        return

    logger.warning("Rebuilding generated Chroma index at %s", resolved)
    for entry in os.listdir(resolved):
        if not _is_recognized_chroma_artifact(entry):
            # Preserve unrelated files.
            continue
        full = os.path.join(resolved, entry)
        try:
            if os.path.isdir(full):
                shutil.rmtree(full, ignore_errors=True)
            else:
                os.remove(full)
        except OSError as exc:
            logger.warning("Could not remove %s during rebuild: %s", full, exc)


def rebuild_index_dir(configured_path):
    """Explicitly clear recognized generated index artifacts and return the dir.

    Preserves source documents (they live under the capability library path,
    not the Chroma directory) and any unrelated files. Callers should re-run
    indexing afterwards. This is NEVER invoked automatically by get_client().
    """
    persist_dir = resolve_persist_dir(configured_path)
    _safe_clear_generated_index(persist_dir)
    _RESOLVED_PERSIST_DIR.pop(os.path.abspath(configured_path), None)
    return persist_dir