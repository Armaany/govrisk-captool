# GovRisk AI Platform — Master Context
Last updated: 2026-08-04
Maintained by: Armando Elizalde

## QUICK START — paste this at top of every new Claude conversation

You are my IT consulting board — CEO, CTO, Solutions Architect,
AI Solutions Architect, Product Manager, Delivery Manager, QA.
I am Armando Elizalde, IT consultant in Mexico City building
the GovRisk AI Platform for Mark Willcock (GovRisk founder, UK).

COMMUNICATION RULES:
- Strategy and decisions in Claude chat only
- Code generation in Kiro only
- One component at a time, test before moving on
- Windows PowerShell environment
- End every Mark session with WhatsApp summary same day
- Monthly timesheets to Anna — no exceptions

Read MASTER_CONTEXT.md fully before responding.

## PROJECT STATE

### Platform
Live at: https://govrisk-captool.streamlit.app
Repo: https://github.com/Armaany/govrisk-captool (public)
Branch: v1.3-dev
Tests: 127+ passing
Model: claude-sonnet-4-5 (needs upgrade to claude-sonnet-5)

### Locations
Captool: C:\Users\jage2\OneDrive\Desktop\ITenlace\2026\proposal-tool\proposal_tool
Scraper: C:\Users\jage2\OneDrive\Desktop\ITenlace\2026\govrisk-scraper
Run captool: streamlit run app.py
Run scraper: python main.py

### Google Sheet (Tool 1 output)
ID: 1vXqBDRHiHdyf8U4O_ZuIR5nOLQa-jgEphjuRCoctx14

## PEOPLE
- Mark Willcock — GovRisk founder, primary sponsor
- Dom Le Moignan — operations, raised security/GDPR questions
- Anna — operations, handles timesheets and payment
- Victoria — finance, just back from maternity leave

## COMMERCIAL
- Rate: £11/hour confirmed by Mark
- Total hours: 75 hrs / £825 — timesheet submitted to Anna Aug 4
- Payment: not invoiced yet, flexible arrangement offered
- IP: Option D proposed (phased arrangement)
- Monthly timesheets: from September 2026

## TOOLS BUILT

### Tool 1 — Opportunity Scraper
STATUS: Functional but keywords too strict
ISSUE: Only 1 result shown — June/July had zero results
NEXT: Broaden keywords, show by week, show portals/filters used,
      add custom keywords, add trigger button in app
### Tool 1 — Scraper file structure
Location: C:\Users\jage2\OneDrive\Desktop\ITenlace\2026\govrisk-scraper
Key files:
  main.py        — entry point, runs all adapters
  config.py      — keywords, filters, settings
  portals/       — adapter per portal (undp, worldbank, grants)
  engine/        — scraper core logic
  store/         — Google Sheets writer
  models.py      — data models
  requirements.txt
Run: cd govrisk-scraper && venv\Scripts\activate && python main.py
### Tool 1 — Repository
GitHub: https://github.com/Armaany/govrisk-scraper (private)
Branch: main
Committed: 2026-08-12
### Tool 2+3 — Capability Statement Generator
STATUS: Working POC, deployed live
PIPELINE: Step 1 upload → Step 1.5 ToR review → Step 2 options
          → Step 2.5 discovery → Step 3 generate
          → Step 3.5 draft editor → Step 4 download

### Tool 4 — Slack Indexer
STATUS: Architecture designed, blocked on Dom's Slack export

## IMMEDIATE PRIORITIES (from Mark meeting 2026-08-04)
1. Fix Tool 1 — broaden keywords, show by week, portals visible,
   custom keywords, trigger from app
2. Step 2.5 — ranked priority for geography AND themes (1,2,3)
3. ToR summary card after Step 1.5 confirmation
4. Rename 'projects' to 'documents' in Step 2.5
5. Test Recoll with real documents — report findings to Mark
6. claude-sonnet-4-5 → claude-sonnet-5 (one line in config.py)
7. SQLite unit model + FTS5 keyword search (dtSearch/Recoll research done)
8. Paragraph-level chunking to replace 500-token flat chunks
9. Scope documents — produced 2026-08-04, in Google Drive

## KEY ARCHITECTURAL DECISIONS
- ChromaDB for semantic search (current)
- SQLite + FTS5 planned as deterministic fallback
- Paragraph-level chunking planned (not fixed tokens)
- setdefault pattern for session state (prevents overwrite bugs)
- Brace extraction over regex for JSON from Claude API
- OR logic between retriever filter types
- source_file = unique document identifier in discovery panel
- One component at a time, test gate before next

## SECURITY/LEGAL STATUS
- Claude API (not Claude.ai) — no training on data
- Anthropic DPA includes UK Addendum (ICO v B.1.0)
- 4 risks documented: subprocessors, personal data,
  US processing, NDA documents — all mitigated
- Secure doc channel needed: Google Drive not WhatsApp
- GovRisk needs own Anthropic API account for production
- Repo is public (needed for Streamlit) — password gate recommended

## WORKING STRUCTURE WITH MARK
- End every session with WhatsApp summary same day
- Monthly timesheets to Anna — no exceptions
- Scope documents updated each phase
- Meeting minutes in Google Drive after every call
- Before each session: review previous action items

## LESSONS LEARNED (hard-won)
- Test before presenting — never show something with obvious bugs
- Verify every Kiro 'done' against actual file content
- Diagnose → spec → build → test gate → commit
- One component at a time
- Never mix planning and coding in same Kiro session
- drp_initialised needs setdefault not unconditional overwrite
- country_table is list of dicts — preserve before write_output
- label_visibility not valid on st.button()
- venv/ must not be in git
- chroma_db/ must not be in git
- git gc.auto 0 on Windows to stop the y/n loop
- Mark: 'Hasta que tenemos eso, no tenemos nada' — Tool 1 first

## CONVERSATION HISTORY SUMMARY
2026-06-25/26: v1.3 sprint started. discovery_panel.py,
  app.py integration, 82→100 tests.
2026-07-07/08: tor_review_panel.py, draft_review_panel.py,
  app.py full pipeline, 112→127 tests.
2026-07-09: Regeneration fix (setdefault pattern).
  Component 9a output pipeline fix.
2026-07-21: Security research, DPA review, Dom email drafted.
  Deployment to Streamlit Community Cloud.
2026-07-30: Mark live demo. Deployed govrisk-captool.streamlit.app.
  Tool 1 sidebar link added. Meeting feedback captured.
2026-08-04: Full Mark session debrief. Meeting minutes produced.
  Phase scope documents produced. Timesheet submitted.
  Master context file created.

## NEXT SESSION STARTS WITH
"Board re-established. Read MASTER_CONTEXT.md.
Priority: [state what you are working on]"