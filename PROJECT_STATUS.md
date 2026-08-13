# GovRisk AI Platform - Project Status
Last updated: 2026-06-26

## TOOL 1: Capability Statement Generator
Location: C:\Users\jage2\OneDrive\Desktop\ITenlace\2026\proposal-tool\proposal_tool
Branch: v1.3-dev (ACTIVE)
Git tags: v1.0, v1.1, v1.2-stable

### Activate
cd "C:\Users\jage2\OneDrive\Desktop\ITenlace\2026\proposal-tool\proposal_tool"
venv\Scripts\activate
streamlit run app.py

### Stack
Python 3.12, Streamlit, ChromaDB, Claude API claude-sonnet-4-5,
python-docx, pdfplumber, python-dotenv

### Working Features (v1.2-stable)
- Full capability statement generation from NOFO PDF/DOCX
- ToR extraction with filter auto-population (Geography, Thematic, Funder)
- Condensed mode (8-10 pages) with proper Word table and citations
- 914 chunks across 15 documents in ChromaDB (govrisk_capabilities)
- OR logic retrieval - 20 chunks per generation
- Download working - absolute path resolved
- HIGH confidence outputs
- 74+ tests passing

### Known Bugs (carried into v1.3)
- Country table aggregated format (not individual rows yet)
- Dropdown collapses on manual selection (Streamlit behavior)

## v1.3 BUILD TRACK
Started: 2026-06-26
Branch: v1.3-dev
Status: IN PROGRESS

### Component sequence
1. discovery_panel.py - Step 2.5 Interactive Discovery Panel [IN PROGRESS]
2. draft_generator.py - [EVIDENCE NEEDED] brackets
3. tor_extractor.py - deliverables[] field
4. output_formatter.py - country table individual rows
5. capability_retriever.py - geography priority scoring
6. capability_library_global/ - second ChromaDB [BLOCKED: waiting Dom]

### Component 1 gate
- [ ] discovery_panel.py created in Kiro
- [ ] 7 unit tests passing
- [ ] 1 property test passing
- [ ] Full pytest suite still green (74+ tests)
- [ ] Committed to v1.3-dev

## MARK'S v1.3 REQUIREMENTS
1. Interactive Discovery Panel (Step 2.5)
   - Checklist of projects found - Mark selects which to include
   - Geography priority selector
   - Thematic areas and outcomes to emphasise
   - Output: capability statement + prompt export (.txt) for ChatGPT
2. No hallucination - [EVIDENCE NEEDED: x] brackets where gaps exist
3. NOFO deliverables extracted and mapped explicitly to evidence
4. Geography priority: exact country -> LAC -> global supplement
5. Second library: capability_library_global/ for non-LAC NOFOs
6. Cross-search between libraries based on NOFO geography
7. Incremental library: add documents per opportunity, not all at once

## TOOL 2: Opportunity Scraper
Location: C:\Users\jage2\OneDrive\Desktop\ITenlace\2026\govrisk-scraper
Stack: Python, BeautifulSoup, Google Sheets, Claude API
Working: UNDP, World Bank, Grants.gov
Stubs: IADB, OECD
Devex: blocked by Cloudflare - workaround via email alerts
Bugs: duplicate rows, loose Spanish keyword filtering

## TOOL 3: Slack Indexer (PLANNED)
Build inside proposal_tool
Slack Pro confirmed by Dom
Pilot: PECEL Mexico channel JSON export
No urgency - following GovRisk pace

## PEOPLE
- Mark Willcock - GovRisk founder, project sponsor
- Dom - portal credentials, sending Tajikistan documents
- Anna - operations manager
- Armando Elizalde - IT consultant

## COMMERCIAL
- Four scenarios sent to Dom
- Rate: London minimum wage as starting point
- Mark replied positively
- Call with Dom and Anna pending
- IP ownership: Armando retains, GovRisk has licence

## GIT BRANCHES
master        <- v1.0 original POC
dev           <- v1.2 work in progress
v1.2-stable   <- last stable demo version
v1.3-dev      <- CURRENT active branch

## NEXT SESSION
Paste PROJECT_STATUS.md and SYSTEM_MAP.md and say:
"You are my IT consulting board. Pick up where we left off."

## SESSION 2026-08-04
- Meeting with Mark — full debrief completed
- Deployed to govrisk-captool.streamlit.app
- Tool 1 sidebar link added
- Meeting minutes produced — in Google Drive
- Phase scope documents produced — in Google Drive
- Timesheet submitted to Anna — 75 hrs / £825
- MASTER_CONTEXT.md created

## IMMEDIATE NEXT PRIORITIES
1. Fix Tool 1 keyword filters — broaden, show by week
2. Add scraper trigger button to app
3. Step 2.5 ranked priority for geography and themes
4. ToR summary card after Step 1.5
5. Rename projects to documents in Step 2.5
6. Test Recoll with real GovRisk documents
7. claude-sonnet-4-5 → claude-sonnet-5 in config.py