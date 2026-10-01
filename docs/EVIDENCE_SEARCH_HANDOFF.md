# Evidence Search and Workspace Handoff

## Repository state

- Repository: `govrisk-captool`
- Feature branch: `feature/evidence-search-workspaces`
- Baseline: `v1.3-dev` at `7aa0c79e2a0d71fc14672323e9786659b01a4319`
- Worktree: `govrisk-captool-evidence-studio`
- The baseline checkout and deployed workflow must remain unchanged until this
  branch passes its review and test gates.

## Objective

Add a second Tool 2 workflow that can search a selected evidence library from a
free-form request and export a source-traceable evidence catalogue. Preserve the
existing Terms of Reference (ToR) to capability-statement workflow.

The target sources are:

1. The existing local capability-library folder.
2. Session-scoped uploads.
3. A read-only Google Drive folder in a later bounded step.

Source documents and credentials must never be committed to Git.

## Current Tool 2 flow

1. `config.CAPABILITY_LIBRARY_PATH` identifies one local folder.
2. `capability_indexer.index_library()` lists top-level `.docx` and `.pdf`
   files, hashes them, extracts text, chunks it, and writes embeddings to the
   global `govrisk_capabilities` Chroma collection.
3. The manifest records incremental-index state beside the active Chroma index.
4. `capability_retriever.retrieve_chunks()` builds a query from ToR thematic
   areas, key requirements, and geography, then performs vector retrieval.
5. The discovery panel lets the user select evidence.
6. The selected chunks are sent to the capability-statement generator.

Known limitations relevant to this feature:

- Only one global source library and one global collection are assumed.
- Switching the existing indexer directly to another folder could interpret
  the previous library's documents as deleted.
- Retrieval is vector-only and optimised for ToR generation, not exhaustive
  evidence inventory.
- DOCX page numbers are approximated every 40 paragraphs and must not be
  described as verified page citations.
- `project_name`, `year`, `donor`, and `country` metadata are currently mostly
  empty, while geography and thematic filter options are GovRisk/LATAM-specific.

## Approved architecture

```text
Local folder -----+
Session uploads --+--> DocumentSource interface
Google Drive -----+             |
                                v
                       Evidence workspace
                                |
                                v
                     Incremental index service
                                |
                                v
                  Isolated Chroma collection + manifest
                                |
                    Shared retrieval service
                     /                    \
              ToR query              Free-form query
                  |                         |
        Capability statement        Evidence extraction
                                            |
                                   Quote/chunk verification
                                            |
                                  Evidence catalogue export
```

## Non-negotiable invariants

- Every workspace has a stable `library_id`.
- Every source document has a stable source identity. Google Drive uses its file
  ID; filenames are display values only.
- Chunk identity includes the workspace and source identity.
- Synchronisation and removal are scoped to one workspace only.
- A missing, unreadable, or empty source never deletes a valid index.
- Source files are read-only and are never modified or deleted.
- The existing `govrisk_capabilities` workflow remains compatible until an
  explicit migration is approved.
- Every exported factual claim carries a source identifier, chunk identifier,
  and supporting quotation.
- A quotation is accepted only if it occurs in the cited chunk after documented
  normalisation. Failed verification becomes `needs_review`; it is never silently
  treated as confirmed evidence.
- Approximate DOCX pages are not presented as verified page locations.

## Prompt placement

The feature uses separate prompts with separate authority:

1. **Search-plan prompt (before retrieval):** converts a free-form user request
   into validated search facets. It does not produce project facts.
2. **Evidence-extraction prompt (after retrieval):** receives only retrieved
   evidence packets and returns structured facts with exact supporting quotes.
3. **Catalogue rendering:** deterministic DOCX/XLSX generation from verified
   records; formatting does not require another LLM call.

Prompt templates belong in version-controlled files under `prompts/`, not inside
Streamlit widget code.

## First implementation slice

Build and prove the Evidence Search MVP against the existing local library before
adding Google Drive:

1. Introduce a `DocumentSource` contract and a local-folder implementation.
2. Add workspace identity and collection/manifest namespacing without changing
   the current default workflow.
3. Refactor retrieval into a query-text core plus ToR and free-form wrappers.
4. Add structured evidence packets containing `library_id`, `source_id`,
   `source_file`, `chunk_id`, locator type/value, and exact text.
5. Add evidence extraction and deterministic quote-in-chunk verification.
6. Add an Evidence Search UI mode and DOCX evidence-catalogue export.
7. Reproduce the India/Asia/SOC evidence request as an acceptance fixture.

Only after this passes should session uploads and Google Drive be added.

## Acceptance scenario

Request:

> Find all projects demonstrating experience in India and wider Asia, serious
> organised crime, fraud, narcotics, and institutional or community-facing
> resilience. Include all relevant projects rather than a shortlist. Include
> dates, clients, statistics, and results only where supported by source
> evidence.

The result must distinguish direct geographic experience from transferable
thematic experience, expose source references and exact evidence quotes, flag
missing or contradictory information, and never invent unsupported facts.

## Review gates

1. Architecture/code review: workspace isolation, deletion safety, evidence
   verification, and backward compatibility.
2. Product review: workflow copy, catalogue structure, gaps and qualifications.
3. Clean-worktree test run and manual Streamlit rehearsal.
4. No merge or deployment without explicit approval.

## Resume instructions

Open the worktree and inspect this document first. Confirm branch and base with:

```powershell
git branch --show-current
git rev-parse HEAD
git status --short
```

Continue from the first implementation slice. Do not restart the architecture
discussion from chat history and do not modify the original `v1.3-dev` checkout.
