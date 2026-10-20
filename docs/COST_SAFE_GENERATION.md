# Cost-safe AI generation

This note describes the paid-request contract introduced after the October 2026
demo rehearsal exposed duplicate actions, long blocking calls, and invisible
automatic retries.

## User contract

The capability-statement flow now has three separate, explicit decisions:

1. **Analyze ToR with AI** — one paid structured-extraction request.
2. **Confirm evidence selection** — local UI action; no paid request.
3. **Generate Capability Statement** — one paid drafting request.

There is no automatic retry after a timeout, provider error, or invalid JSON.
The UI reports the failure and the user decides whether to retry.
After a successful call, the UI displays the provider-reported input and output
token counts. It does not invent a currency estimate; billing remains the
provider's source of truth.

Successful extraction and generation responses are keyed to the exact inputs
and stored atomically under `output/.ai_response_cache/` by default. A rerun,
reconnect, or repeated click with identical inputs reuses that response and
does not call the API. Failed responses are not cached. Concurrent identical
requests are rejected while the first is in flight.

The cache is operational protection, not durable records management. Streamlit
Community Cloud may remove it when the app container restarts. Generated Word
documents and approved client outputs remain the records users should retain.

## API boundaries

- SDK automatic retries: disabled (`max_retries=0`).
- Default request timeout: 90 seconds.
- ToR extraction model: `claude-haiku-4-5`.
- ToR maximum output: 3,000 tokens.
- Draft model: `claude-sonnet-4-5`.
- Draft maximum output: 8,000 tokens.
- ToR paragraphs are extracted locally and are no longer echoed back by the
  model, reducing paid output while preserving source-map paragraph numbers.

These defaults are configurable with `EXTRACTION_MODEL_NAME`,
`GENERATION_MODEL_NAME`, `ANTHROPIC_TIMEOUT_SECONDS`,
`EXTRACTION_MAX_TOKENS`, `GENERATION_MAX_TOKENS`, and
`AI_RESPONSE_CACHE_PATH`. Numeric limits are bounded in `config.py` so a typo
cannot silently create an extreme token allowance.

## Controlled production check

Do not click multiple actions during this check.

1. Record the Claude credit balance and open the Streamlit app in one tab.
2. Upload the demo ToR. Confirm that upload alone sends no AI request.
3. Click **Analyze ToR with AI** once. Wait for completion. Record the balance.
4. Navigate or refresh, upload the identical file, and click Analyze again.
   Confirm the UI says the saved analysis was reused and the balance does not
   change for a second request.
5. Confirm the evidence selection. Confirm this action does not change the
   balance.
6. Click **Generate Capability Statement** once. Wait for the draft review
   panel. Record the balance.
7. Repeat with identical ToR, evidence, sections, and language. Confirm the UI
   reports reuse and no second draft request is charged.
8. Download the document only after reviewing the draft. Downloading and Word
   formatting are local operations and must not call the AI API.

If a step times out or reports malformed output, stop and capture the friendly
error plus Streamlit logs. A retry is always an explicit user decision.
