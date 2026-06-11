# KIRO System Map — GovRisk Capability Statement Generator

Complete inventory of every Python file in the project.

---

## app.py

**Size:** 26,897 bytes  
**Description:** Single-page Streamlit UI that orchestrates the full generation pipeline.

| Function | Parameters | Purpose |
|---|---|---|
| `_api_key_is_missing` | `key` | Return True if the API key is missing or empty. |
| `_can_generate` | `api_key_missing, tor_data, doc_count` | Return True only when all preconditions for generation are met. |
| `_normalize_filter_values` | `values, normalize_map, valid_options` | Map extracted values to the closest matching option using normalize_map, then keep only values that exist in valid_options. |
| `_normalize_funder` | `funder_str` | Match a funder string against `_FUNDER_NORMALIZE` using substring matching. |
| `update_progress` | `step_index, status` | *(no docstring)* Update a progress step status in session state. |

**Constants:** `ALL_SECTIONS`, `DEFAULTS`, `_FUNDER_NORMALIZE`, `_GEO_NORMALIZE`, `_THEMATIC_NORMALIZE`

---

## tor_extractor.py

**Size:** 7,838 bytes  
**Description:** Extracts structured requirements from a ToR document (.docx or .pdf) using the Claude API.

| Function | Parameters | Purpose |
|---|---|---|
| `_error_state` | `filename, message` | Return a well-formed error-state dict. |
| `_extract_text_docx` | `file_bytes` | Extract all text from a .docx file, including table cells. |
| `_extract_text_pdf` | `file_bytes` | Extract all text from a .pdf file using pdfplumber. |
| `_truncate_text` | `text` | Truncate text to at most 15,000 characters. |
| `_call_claude` | `client, user_prompt` | Make a single Claude API call and return the raw text response. |
| `_strip_markdown_fences` | `text` | *(no docstring)* Strip markdown fences and extract JSON object from response. |
| `_fill_defaults` | `data, filename` | Ensure all required keys are present in data. |
| `extract_tor` | `file_bytes, filename` | Extract structured requirements from a ToR document. |

**Constants:** `SYSTEM_PROMPT`, `USER_PROMPT_TEMPLATE`, `_REQUIRED_KEYS`

---

## capability_indexer.py

**Size:** 11,375 bytes  
**Description:** Scans the capability library, chunks documents, and stores them in ChromaDB with metadata.

| Function | Parameters | Purpose |
|---|---|---|
| `_extract_docx` | `filepath` | Extract text from a .docx file. |
| `_extract_pdf` | `filepath, filename` | Extract text from a .pdf file using pdfplumber. |
| `chunk_text` | `text, page_number` | Split text into chunks of at most MAX_TOKENS_PER_CHUNK tokens (words). |
| `detect_tags` | `text` | Detect geography and thematic tags in text by keyword matching. |
| `index_library` | `force_reindex` | Scan CAPABILITY_LIBRARY_PATH for .docx and .pdf files, chunk them, and store in ChromaDB. |

---

## capability_retriever.py

**Size:** 9,590 bytes  
**Description:** Queries ChromaDB with semantic search and metadata filters to return ranked capability chunks.

| Function | Parameters | Purpose |
|---|---|---|
| `_build_query_string` | `tor_data` | Concatenate thematic_areas, key_requirements, and geography from tor_data into a query string. |
| `_parse_json_list` | `value` | Parse a JSON string back to a list; return [] on failure. |
| `_none_if_empty_str` | `value` | Return None if value is an empty string or None, else return value. |
| `_none_if_zero` | `value` | Return None if value is 0 or None, else return value. |
| `_chunk_satisfies_filters` | `metadata, filters` | Check whether a chunk's metadata satisfies the active filters (OR logic between geography and thematic_areas). |
| `retrieve_chunks` | `tor_data, filters, top_k` | Retrieve relevant capability chunks from ChromaDB. |

---

## draft_generator.py

**Size:** 13,767 bytes  
**Description:** Generates the structured capability statement draft via the Claude API, with citation enforcement and schema validation.

| Function | Parameters | Purpose |
|---|---|---|
| `_strip_markdown_fences` | `text` | *(no docstring)* Strip markdown fences and extract JSON object from response. |
| `_build_context_block` | `retrieved_chunks` | Task 5.2: Build a context string from at most 20 chunks. |
| `_build_tor_summary` | `tor_data` | Build the TOR summary string for the user prompt. |
| `_error_state` | `message` | Return a well-formed error-state dict. |
| `_call_claude` | `client, system, user_prompt` | Make a single Claude API call and return the raw text response. |
| `_derive_confidence` | `interpretation_log` | Task 5.7: Derive overall confidence from interpretation log entries. |
| `_validate_log_entry` | `entry` | Task 5.6: Ensure all required keys exist in an interpretation log entry. |
| `_validate_and_normalise` | `data, sections_to_include, retrieved_chunks` | Task 5.5 + 5.6 + 5.7: Validate and normalise the parsed GeneratedDraft dict. |
| `generate_draft` | `tor_data, retrieved_chunks, sections_to_include, output_language` | Generate a capability statement draft using the Claude API. |

**Constants:** `ALL_SECTIONS`, `SYSTEM_PROMPT`, `_JSON_SCHEMA`, `_USER_PROMPT_TEMPLATE`

---

## citation_tagger.py

**Size:** 3,078 bytes  
**Description:** Strips inline `[REF:filename:page_N]` tags from draft text and builds per-paragraph citation footnotes.

| Function | Parameters | Purpose |
|---|---|---|
| `format_citation` | `filename, page` | Return the formatted display string for a citation. |
| `_process_paragraph` | `paragraph` | Process a single paragraph: extract citations, clean text. |
| `tag_citations` | `draft_sections` | Process all text sections from a generated draft, stripping inline REF tags. |

**Constants:** `CLEAN_PATTERN`, `REF_PATTERN`

---

## output_formatter.py

**Size:** 9,587 bytes  
**Description:** Writes the capability statement as a formatted .docx file using python-docx.

| Function | Parameters | Purpose |
|---|---|---|
| `_sanitize` | `text` | Remove XML-incompatible control characters from a string. |
| `_add_heading` | `doc, text` | Add a bold 14pt Calibri section heading paragraph. |
| `_add_body_text` | `doc, text` | Add body text paragraphs (split on `\n\n`), 11pt Calibri, no bold. |
| `_add_citation_line` | `doc, citation_text` | Add an italic gray 9pt Calibri citation line. |
| `_add_country_table` | `doc, country_table` | Render country_table as a Word table with 4 columns (Country, Project Name, Year, Donor). |
| `_add_horizontal_rule` | `doc` | Add a horizontal rule paragraph. |
| `_add_interpretation_log` | `doc, interpretation_log` | Add the interpretation log section with a horizontal rule separator. |
| `_add_citations_section` | `doc, citation_result` | Add the Source Citations section from citation_result. |
| `write_output` | `generated_draft, citation_result, output_language, sections_to_include, output_path` | Write the capability statement as a formatted .docx file. |

**Constants:** `BODY_SIZE`, `CITATION_COLOR`, `CITATION_SIZE`, `FONT_NAME`, `HEADING_SIZE`, `INTERP_LOG_SIZE`, `MARGIN`, `SUBHEADING_SIZE`, `_CONTROL_CHAR_PATTERN`, `_REF_STRIP_PATTERN`

---

## config.py

**Size:** 925 bytes  
**Description:** Single source of truth for all application constants, paths, model names, and filter option lists.

| Function | Parameters | Purpose |
|---|---|---|
| *(no functions)* | — | Import-only module. |

**Constants:** `ANTHROPIC_API_KEY`, `CAPABILITY_LIBRARY_PATH`, `CHROMA_DB_PATH`, `CHUNK_OVERLAP_TOKENS`, `FUNDER_OPTIONS`, `GEOGRAPHY_OPTIONS`, `MAX_RETRIEVAL_RESULTS`, `MAX_TOKENS_PER_CHUNK`, `MODEL_NAME`, `OUTPUT_PATH`, `THEMATIC_OPTIONS`

---

## tests/test_app.py

**Size:** 5,795 bytes  
**Description:** Unit tests for app.py logic functions (API key guard, generation guards, progress steps, download logic).

| Function | Parameters | Purpose |
|---|---|---|
| `test_app_module_importable` | — | app.py can be imported without raising (mocking streamlit). |
| `test_api_key_guard_logic` | — | API key guard correctly identifies missing/empty keys. |
| `test_empty_chromadb_guard_logic` | — | Generation is blocked when doc_count == 0. |
| `test_no_file_uploaded_guard` | — | Generation is blocked when tor_data is None. |
| `test_update_library_calls_index_library` | — | Update Library button logic calls index_library. |
| `test_progress_steps_structure` | — | Progress steps list has exactly 5 entries with required keys. |
| `test_interpretation_log_confidence_colors` | — | Confidence level maps to correct color indicator. |
| `test_download_only_after_generation` | — | Download button condition: both generated_draft and output_file_path must be set. |
| `_should_show_download` | `generated_draft, output_file_path` | *(no docstring)* Helper: returns True only when both values are set. |

---

## tests/test_capability_indexer.py

**Size:** 9,415 bytes  
**Description:** Unit and property-based tests for capability_indexer.py (chunking, keyword detection, idempotence, schema).

| Function | Parameters | Purpose |
|---|---|---|
| `test_pdfplumber_failure_is_caught_and_skipped` | `tmp_path, caplog` | Requirement 2.9: pdfplumber failure logs warning and skips file without crash. |
| `test_p1_chunk_size_invariant` | `text` | P1: Every chunk has token count ≤ MAX_TOKENS_PER_CHUNK. |
| `test_p2_chunk_overlap_invariant` | `text` | P2: Consecutive chunk overlap is ≤ CHUNK_OVERLAP_TOKENS. |
| `test_p3_keyword_detection` | `keyword` | P3: If keyword present in text, it appears in detected tags. |
| `test_p4_indexing_idempotence` | `tmp_path` | P4: Indexing same document twice without force_reindex produces same chunk count. |
| `test_p5_summary_accuracy` | `tmp_path` | P5: IndexingSummary counts match actual processed/skipped counts. |
| `test_p21_chunk_schema_conformance` | `tmp_path` | P21: All stored chunks have required metadata fields with correct types. |

---

## tests/test_capability_retriever.py

**Size:** 9,633 bytes  
**Description:** Unit and property-based tests for capability_retriever.py (count bound, score ordering, deduplication, filter logic).

| Function | Parameters | Purpose |
|---|---|---|
| `seeded_chroma` | `tmp_path` | Creates a temp ChromaDB with 30 test chunks having varied metadata. |
| `test_empty_chromadb_returns_empty_result` | `tmp_path` | Requirement 4.6: If ChromaDB contains no documents, retriever returns empty result. |
| `_seed_chroma` | `chroma_path` | Seed a ChromaDB at chroma_path with 30 varied test chunks. |
| `test_p7_result_count_bound` | `tmp_path, top_k` | P7: Retriever returns at most MAX_RETRIEVAL_RESULTS chunks. |
| `test_p8_relevance_scores_non_increasing` | `tmp_path, query_text` | P8: Chunks are ordered by relevance score descending (non-increasing). |
| `test_p9_no_duplicate_source_page_pairs` | `tmp_path, query_text` | P9: No two returned chunks share the same (source_file, page_number). |
| `test_p10_filter_logic` | `seeded_chroma, geography_value` | P10: All returned chunks satisfy the active geography filter. |

---

## tests/test_citation_tagger.py

**Size:** 8,133 bytes  
**Description:** Unit and property-based tests for citation_tagger.py (REF tag parsing, deduplication, formatting, robustness).

| Function | Parameters | Purpose |
|---|---|---|
| `test_ref_tags_removed_from_text` | — | REF tags are stripped from the output text. |
| `test_citations_extracted_correctly` | — | Filename and page number are extracted correctly from a REF tag. |
| `test_duplicate_citations_deduplicated` | — | Same REF tag appearing twice in one paragraph yields one citation. |
| `test_citation_format_string` | — | format_citation returns the expected display string. |
| `test_no_ref_tags_returns_empty_citations` | — | A paragraph with no REF tags produces an empty citations list. |
| `test_empty_paragraphs_skipped` | — | Paragraphs that are empty after cleaning REF tags are not included. |
| `test_non_string_sections_skipped` | — | country_table list value is not processed and does not appear in paragraphs. |
| `test_multiple_paragraphs_split_correctly` | — | Text separated by double newline produces multiple paragraph entries. |
| `test_tag_citations_never_raises` | — | tag_citations must not raise for None, empty dict, or malformed input. |
| `test_p12_no_ref_tags_in_output` | `text_with_ref` | P12: After tag_citations, no [REF:...] patterns remain in any paragraph text. |
| `test_p13_duplicate_citations_deduplicated` | `filename, page` | P13: Duplicate [REF:filename:page_N] tags in same paragraph → one citation. |
| `test_p14_citation_format` | `filename, page` | P14: format_citation produces exactly 'Source: filename, p.N'. |
| `test_p11_complement_no_ref_tags_empty_citations` | `text_without_refs` | P11 complement: paragraphs with no REF tags have empty citations list. |

---

## tests/test_config.py

**Size:** 1,704 bytes  
**Description:** Smoke tests verifying all config.py constants match the spec values.

| Function | Parameters | Purpose |
|---|---|---|
| `test_model_name` | — | *(no docstring)* Asserts MODEL_NAME == "claude-sonnet-4-5". |
| `test_max_tokens_per_chunk` | — | *(no docstring)* Asserts MAX_TOKENS_PER_CHUNK == 500. |
| `test_chunk_overlap_tokens` | — | *(no docstring)* Asserts CHUNK_OVERLAP_TOKENS == 50. |
| `test_max_retrieval_results` | — | *(no docstring)* Asserts MAX_RETRIEVAL_RESULTS == 20. |
| `test_geography_options_count` | — | *(no docstring)* Asserts len(GEOGRAPHY_OPTIONS) == 9. |
| `test_geography_options_contents` | — | *(no docstring)* Asserts GEOGRAPHY_OPTIONS matches expected list. |
| `test_thematic_options_count` | — | *(no docstring)* Asserts len(THEMATIC_OPTIONS) == 10. |
| `test_thematic_options_contents` | — | *(no docstring)* Asserts THEMATIC_OPTIONS matches expected list. |
| `test_funder_options_count` | — | *(no docstring)* Asserts len(FUNDER_OPTIONS) == 6. |
| `test_funder_options_contents` | — | *(no docstring)* Asserts FUNDER_OPTIONS matches expected list. |
| `test_paths_defined` | — | *(no docstring)* Asserts path constants match expected values. |

---

## tests/test_draft_generator.py

**Size:** 15,879 bytes  
**Description:** Unit and property-based tests for draft_generator.py (API call params, prompts, retry logic, schema, PBT properties).

| Function | Parameters | Purpose |
|---|---|---|
| `_make_tor_data` | — | *(no docstring)* Helper: returns a minimal valid TorData dict. |
| `_make_chunks` | `n` | *(no docstring)* Helper: returns a list of n test chunk dicts. |
| `_make_valid_draft_json` | — | *(no docstring)* Helper: returns a valid GeneratedDraft JSON string. |
| `_make_mock_client` | `response_text` | Return a mock Anthropic client that returns the given text. |
| `test_claude_api_called_with_max_tokens_16000` | — | Requirement 5.2: Claude API must be called with max_tokens=16000. |
| `test_system_prompt_contains_required_instructions` | — | Requirement 5.3: System prompt must contain all required instructions. |
| `test_system_prompt_passed_to_claude` | — | System prompt is passed to the Claude API call. |
| `test_non_json_response_triggers_retry_then_returns_error` | — | Requirement 5.8: Non-JSON Claude response triggers exactly one retry. |
| `test_non_json_first_attempt_valid_second_succeeds` | — | First attempt returns non-JSON, second attempt returns valid JSON — should succeed. |
| `test_generate_draft_never_raises_on_bad_input` | — | generate_draft must always return a dict, never raise. |
| `test_generate_draft_returns_error_dict_on_api_failure` | — | When the API raises an exception, an error dict is returned. |
| `test_missing_section_keys_filled_with_empty_string` | — | Task 5.5: Missing section keys are added with empty string value. |
| `test_context_block_empty_chunks_returns_fallback` | — | _build_context_block returns fallback string when chunks list is empty. |
| `test_p11_ref_tag_in_every_section` | `sections` | P11: Every section string that has content contains at least one REF tag. |
| `test_p17_recency_ordering` | `projects` | P17: Projects sorted by year descending, stable for equal years. |
| `test_p20_generated_draft_json_roundtrip` | `draft` | P20: Serialising a GeneratedDraft dict to JSON and deserialising it produces equal object. |
| `test_p22_interpretation_log_completeness` | `log_entries` | P22: All interpretation_log entries have all required fields. |
| `test_p23_context_block_chunk_cap` | `num_chunks` | P23: Context block uses at most 20 chunks regardless of input size. |
| `capture_call` | — | *(no docstring)* Side-effect helper used in mock setup. |

---

## tests/test_output_formatter.py

**Size:** 13,944 bytes  
**Description:** Unit and property-based tests for output_formatter.py (file writing, heading order, styles, table structure, filename format).

| Function | Parameters | Purpose |
|---|---|---|
| `_make_minimal_draft` | — | *(no docstring)* Helper: returns a minimal GeneratedDraft dict. |
| `_make_minimal_citation_result` | — | *(no docstring)* Helper: returns a minimal citation_result dict. |
| `test_output_file_written_to_output_path` | `tmp_path` | Output file is written to the specified output_path and path is returned. |
| `test_section_headings_in_correct_order` | `tmp_path` | Section headings appear in the document in the specified order. |
| `test_document_styles_match_spec` | `tmp_path` | Body text is 11pt, citation runs are 9pt italic, margins are 2.5cm. |
| `test_no_ref_tags_in_output_document` | `tmp_path` | No [REF:...] tags appear in the written document paragraphs. |
| `test_p15_filename_format` | `dt` | P15: Output filename matches GovRisk_CapabilityStatement_{YYYY-MM-DD}_{HH-MM}.docx. |
| `test_p16_country_table_structure` | `tmp_path, country_table_data` | P16: Word table has exactly 4 columns and 1 header row + N data rows. |
| `test_p18_project_experience_order_preserved` | `tmp_path, project_texts` | P18: Project experience entries appear in the document in the same order provided. |

---

## tests/test_tor_extractor.py

**Size:** 9,160 bytes  
**Description:** Unit and property-based tests for tor_extractor.py (file type guards, JSON retry, truncation, round-trip).

| Function | Parameters | Purpose |
|---|---|---|
| `make_minimal_docx` | `text` | *(no docstring)* Helper: returns bytes of a minimal valid .docx file. |
| `test_unsupported_file_type_returns_error_dict` | — | Requirement 3.9: Non-.docx/.pdf file returns error dict with LOW confidence. |
| `test_unsupported_file_type_no_extension_returns_error_dict` | — | Files with no extension also return error dict. |
| `test_non_json_response_triggers_retry_then_returns_error` | — | Requirement 3.7: Non-JSON Claude response triggers exactly one retry. |
| `test_system_prompt_contains_required_instruction` | — | Requirement 3.5: System prompt instructs Claude to respond only with valid JSON. |
| `test_p6_text_truncation` | `length, seed_char` | P6: For any text longer than 15,000 chars, the truncation logic produces exactly 15,000 characters. |
| `test_p19_tor_data_json_roundtrip` | `tor_data` | P19: Serialising a TorData dict to JSON and deserialising it produces equal object. |
| `test_source_file_always_overridden_by_filename` | — | The source_file field in the returned dict must always equal the filename argument. |
| `test_missing_keys_filled_with_defaults` | — | If Claude returns JSON missing some keys, defaults are filled in. |
| `test_error_state_source_file_matches_filename` | — | Error state dict always has source_file equal to the filename argument. |
| `capture_call` | — | *(no docstring)* Side-effect helper used in mock setup. |
