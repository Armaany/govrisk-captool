# GovRisk AI Platform — Project Status
Last updated: 2026-06-11

## TOOL 1: Capability Statement Generator
Location: C:\Users\jage2\OneDrive\Desktop\ITenlace\2026\proposal-tool\proposal_tool
Branch: v1.2-stable (DEMO VERSION — use this)
Git tags: v1.0, v1.1, v1.2-stable

### Activate
cd "C:\Users\jage2\OneDrive\Desktop\ITenlace\2026\proposal-tool\proposal_tool"
venv\Scripts\activate
streamlit run app.py

### Stack
Python 3.12, Streamlit, ChromaDB, Claude API claude-sonnet-4-5,
python-docx, pdfplumber, python-dotenv

### Working Features
- Full capability statement generation from NOFO PDF/DOCX
- ToR extraction with filter auto-population (Geography, Thematic, Funder)
- Condensed mode (8-10 pages) with proper Word table and citations
- 914 chunks across 15 documents in ChromaDB (govrisk_capabilities)
- OR logic retrieval — 20 chunks per generation
- Download working — absolute path resolved
- HIGH confidence outputs
- 74+ tests passing

### Files and Functions
app.py — Streamlit UI, full pipeline
  _normalize_filter_values() — maps extracted values to options
  _normalize_funder() — funder string normalization
  _GEO_NORMALIZE, _THEMATIC_NORMALIZE, _FUNDER_NORMALIZE — mapping dicts

tor_extractor.py — extracts JSON from ToR PDF/DOCX
  extract_tor(file_bytes, filename) → tor_data dict
  _extract_text_pdf() — try/finally pattern (not context manager)
  _strip_markdown_fences() — brace extraction approach

capability_indexer.py — indexes library into ChromaDB
  index_library(force_reindex=False) → summary dict
  detect_tags() — case-insensitive keyword detection

capability_retriever.py — queries ChromaDB
  retrieve_chunks(tor_data, filters) → chunks list
  _chunk_satisfies_filters() — OR logic between filter types

draft_generator.py — generates via Claude API
  generate_draft(tor_data, chunks, sections, language) → draft dict
  max_tokens=16000
  _strip_markdown_fences() — brace extraction

citation_tagger.py — strips REF tags
  tag_citations(text) → paragraphs with citations

output_formatter.py — writes Word doc
  write_output(draft, citations, language, sections) → absolute path

config.py — constants
  MODEL_NAME = claude-sonnet-4-5
  OUTPUT_PATH, CAPABILITY_LIBRARY_PATH, CHROMA_DB_PATH

### Known Bugs
- Country table aggregated format (not individual rows yet)
- Dropdown collapses on manual selection (Streamlit behavior, v1.3)

### ChromaDB
Collection: govrisk_capabilities
Chunks: 914, Documents: 15
Metadata: source_file, page_number, geography, thematic_areas, doc_type

## TOOL 2: Opportunity Scraper
Location: C:\Users\jage2\OneDrive\Desktop\ITenlace\2026\govrisk-scraper
Stack: Python, BeautifulSoup, Google Sheets, Claude API
Working: UNDP, World Bank, Grants.gov
Stubs: IADB, OECD
Devex: blocked by Cloudflare — workaround via email alerts
Bugs: duplicate rows, loose Spanish keyword filtering

## TOOL 3: Slack Indexer (PLANNED)
Build inside proposal_tool
Slack Pro confirmed by Dom
Pilot: PECEL Mexico channel JSON export
No urgency — following GovRisk pace

## PEOPLE
- Mark Willcock — GovRisk founder, project sponsor
- Dom — portal credentials, sending Tajikistan documents
- Anna — operations manager
- Armando Elizalde — IT consultant

## COMMERCIAL
- Four scenarios sent to Dom
- Rate: London minimum wage as starting point
- Mark replied positively
- Call with Dom and Anna pending
- IP ownership: Armando retains, GovRisk has licence

## MARK'S v1.3 REQUIREMENTS
1. Interactive Discovery Panel (Step 2.5)
   - Checklist of projects found — Mark selects which to include
   - Geography priority selector
   - Thematic areas and outcomes to emphasise
   - Output: capability statement + prompt export (.txt) for ChatGPT
2. No hallucination — [EVIDENCE NEEDED: x] brackets where gaps exist
3. NOFO deliverables extracted and mapped explicitly to evidence
4. Geography priority: exact country → LAC → global supplement
5. Second library: capability_library_global/ for non-LAC NOFOs
6. Cross-search between libraries based on NOFO geography
7. Incremental library: add documents per opportunity, not all at once

## ACTIVE WAITING
- Dom sending Tajikistan capability documents
- Dom/Anna to export PECEL Mexico Slack channel
- Mark to provide project outcomes per opportunity

## EMAILS SENT
- Demo minutes to Mark, Dom, Anna ✅
- Mark replied positively ✅
- Commercial scenarios sent to Dom ✅
- Slack Pro confirmed by Dom ✅
- Tajikistan test requested by Dom ✅

## NEXT SESSION PRIORITIES
1. Build Step 2.5 — Interactive Discovery Panel
2. Fix country table individual rows
3. Add [EVIDENCE NEEDED] to generation prompt
4. Extract NOFO deliverables in tor_extractor
5. Create capability_library_global/ + second ChromaDB collection
6. Fix Scraper deduplication bug