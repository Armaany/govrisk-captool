# Capability Index Reliability (Phase 2A)

This document describes the ChromaDB index reliability contract implemented in
`chroma_client.py`, `capability_indexer.py`, and `app.py`. It is the source of
truth for how index state is owned, written, counted, reconciled, and surfaced.

## Ownership and layering

- **`chroma_client.py`** resolves *where* the index lives and exposes status.
- **`capability_indexer.py`** owns *all* index state: it performs synchronization
  and is the only component that writes the index manifest.
- **`app.py`** is presentation-only. It reads counts and the manifest and calls
  the indexer. It never writes `index_manifest.json` and never writes to Chroma.

## Active-directory behavior

`chroma_client.get_client()` prefers the configured persist directory. If that
directory cannot open a client, it falls back to a genuinely fresh,
process-specific *recovery* directory and caches that resolution for the life of
the process. `get_persist_status(configured_path)` reports the directory a caller
will actually use:

- `active_dir` — where the index (and manifest) actually live.
- `configured_dir` — the originally configured location.
- `mode` — `configured` or `recovery`.
- `is_temporary` — `True` only for recovery locations.

`manifest_path(configured_path)` always returns `<active_dir>/index_manifest.json`,
so index status never divorces from the index it describes. After a recovery
fallback has occurred in a process, the resolved-directory cache makes recovery
authoritative: status and manifest both track the recovery directory.

### Recovery-mode limitation

Because the resolved-directory cache pins the active directory for the life of
the process, clicking **Update Library** does **not** necessarily migrate back to
configured storage during that process. The UI therefore uses the exact wording:

> Using a temporary search index. It may need to be rebuilt when the app restarts.

Full filesystem paths are never shown in the UI.

## Counts: three distinct values

The sidebar shows three values that must never be conflated:

- **Source documents** — supported `.pdf`/`.docx` files currently present on disk.
- **Indexed documents** — distinct source files that were successfully indexed
  (from the manifest's `indexed_documents_total`).
- **Search chunks** — `collection.count()`. This is a chunk count and is only
  ever labelled as chunks, never as a document count.

## Manifest schema

The manifest is JSON, versioned, and written atomically (temp file in the same
directory, `flush`+`fsync`, then `os.replace`). Fields:

| Field | Meaning |
|---|---|
| `schema_version` | Manifest structure version (currently `1`). |
| `status` | Top-level run status (one of the `STATUS_*` values). |
| `last_successful_index_at` | Timezone-aware UTC ISO 8601 ending in `Z`. Null if publication failed. |
| `collection_name` | Chroma collection name. |
| `storage_mode` | `configured` or `recovery`. |
| `source_documents_total` | Supported source files present at sync time. |
| `indexed_documents_total` | Distinct successfully indexed source files. |
| `chunks_total` | `collection.count()` after sync. |
| `failed_documents_total` | Count of failed documents (mirrors the list length). |
| `failed_documents` | List of `{filename, category, reason}` (safe tokens only). |
| `config_fingerprint` | Fingerprint of the effective index configuration. |
| `settings` | `{max_tokens_per_chunk, chunk_overlap_tokens, index_engine_version}`. |
| `documents` | Per-document inventory (see below). |

Per-document inventory entries carry: normalized relative `filename`, SHA-256
`content_hash`, `file_size`, indexed `chunk_count`, `status`, and a safe
`failure_category` when applicable.

The manifest is written only after a run that reached the tally/publish stage
(`ready`, `partial_success`, `empty_index`, `source_library_empty`). It is not
written for `library_unavailable`, `index_unavailable`, or
`indexing_in_progress` outcomes.

## Generation-specific chunk IDs

Chunk IDs are generation-specific and deterministic:

```
<relative_name>::<content_hash>::chunk::<ordinal>
```

Because the content hash is part of the ID, a changed document produces an
entirely new ID space (a new "generation") that is disjoint from the old one.
This is what makes transaction-safe replacement possible.

## SHA-256 incremental reconciliation

Synchronization is content-hash based, not filename-only:

- **New document** — extract, chunk, index.
- **Unchanged** — same relative filename, same SHA-256, *and* same index-config
  fingerprint — skip.
- **Changed hash** — extract and build the new generation; add it *first*; only
  after every batch succeeds are the exact old-generation IDs deleted.
- **Removed source document** — its stale chunks are deleted by their exact IDs,
  but only after a valid source-directory inventory succeeds.
- **Unsupported files** — ignored.

### Transaction-safe changed-document replacement

For a changed document the indexer:

1. captures the exact old chunk IDs;
2. adds all new-generation chunks first (batch by batch);
3. if any batch fails, deletes the new-generation IDs already added and
   preserves the old IDs/content entirely — reporting a `write_error` (or
   `write_error_rollback_failed` if the rollback delete itself failed);
4. only after every new batch succeeds, deletes the exact old IDs (never a broad
   `source_file` delete that could remove the new generation).

## Index-configuration fingerprint

`index_config_fingerprint()` hashes `INDEX_ENGINE_VERSION`,
`MAX_TOKENS_PER_CHUNK`, and `CHUNK_OVERLAP_TOKENS`. Each chunk records the
fingerprint it was indexed under. When the current fingerprint differs from a
document's recorded fingerprint, the document is re-indexed even if its bytes are
unchanged, because the stored chunks no longer match the active configuration.

### Failure preservation

- **Extraction failure for a changed document** preserves its previous valid
  chunks (nothing is deleted because the replacement was never prepared).
- **Write failure while adding the new generation** rolls back the partial new
  generation and preserves the old generation exactly.
- **Removed-document deletion failure** is a partial success: the document is
  still present in Chroma, so it stays counted in `indexed_documents_total`, and
  the failure is recorded as `removed_delete_error`. The manifest stays
  consistent with what actually remains in Chroma.
- **One failed document never blocks** healthy documents from indexing.
- A **missing or unreadable library** preserves the existing index and returns
  `status == "library_unavailable"`. It is **never** treated as a successful
  empty library.
- Source documents are never modified or deleted by any code path.

### Empty-library protection

A readable but **empty** source folder must not erase a non-empty valid index:

- Zero supported documents present **and** the index still holds data →
  `status == "source_library_empty"`; the index is preserved unchanged, and no
  removals are performed. Clearing every indexed document requires a separate
  explicit destructive action (rebuild), never incremental sync.
- Both the source folder and the index are empty → `status == "empty_index"`.
- When some supported documents remain, genuinely removed documents are
  reconciled normally.

## Manifest publication failure

The manifest is published atomically (temp file + `fsync` + `os.replace`). If
publication fails, the run does **not** report a normal ready status: it returns
`status == "manifest_write_failed"` with the safe error category
`manifest_write_failed`, and `last_successful_index_at` is set to `null` (we do
not claim a timestamp was persisted). The indexing work already written to Chroma
is not lost, but the status is surfaced honestly rather than silently completing.

## Concurrency protection

A process-level, non-blocking lock (`threading.Lock`) guards synchronization.
Only one sync may run at a time. A concurrent second call returns immediately
with `status == "indexing_in_progress"` and does **not** begin extraction or
write to Chroma. The lock is released in a `finally` block on both success and
exception.

## Auto-index safety

Auto-index runs only when **all** hold:

- the searchable index is genuinely empty (`chunks_total == 0`),
- the library directory is readable,
- at least one supported source document exists, and
- the session has not already attempted auto-indexing
  (`st.session_state["auto_index_attempted"]`).

This prevents endless Streamlit rerun loops when the library is missing, empty,
or after a prior failed attempt. Manual **Update Library** performs incremental
synchronization and presents processed, unchanged, removed, failed,
indexed-document, and chunk totals.

## User-visible states and generation

`app._derive_library_state(...)` maps signals to one of: `ready`, `indexing`,
`empty_index`, `missing_library`, `partial`, `recovery`, `index_unavailable`.
An unavailable or empty *index* outranks a missing/empty *source library*.

Document generation depends on **searchable evidence (a non-empty index)**, not
on the presence of the source library. `app._document_generation_enabled(...)`
is the single source of truth, and the generation guard routes through it so UI
copy and behavior cannot disagree:

- **Index empty, unavailable, or indexing in progress** → generation disabled.
- **Source library missing/empty but the index is non-empty** →
  `missing_library` state; the UI warns that updates are paused and the index
  may be stale, but generation **continues** on the preserved index. The copy
  never claims generation is paused.

An infrastructure failure is never presented downstream as "no relevant evidence
found". The sidebar also reads the manifest `status` and `failed_documents_total`
and shows a concise partial-success warning (a count only — no raw exception text
or filesystem paths).

## Explicit rebuild and manifest invalidation

Explicit rebuild (`chroma_client.rebuild_index_dir`) is the only destructive
index operation and is never invoked automatically. `index_manifest.json` is part
of the recognized generated-index artifact set, so a rebuild removes the stale
manifest along with the index (never leaving a manifest describing a wiped
index). Existing protections remain: rebuild refuses filesystem/drive roots, the
home directory, and the capability-library directory or any parent of it;
unrelated files are preserved; every source document is preserved.

## Known contradiction (not resolved in this task)

The capability library is currently tracked in the repository while
documentation elsewhere states that source documents and outputs were removed
from the public repo. This tracked-library vs. documentation contradiction is
flagged here and intentionally left unresolved in Phase 2A.
