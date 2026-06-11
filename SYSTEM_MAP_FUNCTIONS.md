
=== app.py (26897 bytes) ===
  def _api_key_is_missing(key)
      purpose: Return True if the API key is missing or empty.
  def _can_generate(api_key_missing, tor_data, doc_count)
      purpose: Return True only when all preconditions for generation are met.
  def _normalize_filter_values(values, normalize_map, valid_options)
      purpose: Map extracted values to the closest matching option using normalize_ma
  def _normalize_funder(funder_str)
      purpose: Match a funder string against _FUNDER_NORMALIZE using substring matchi
  def update_progress(step_index, status)
      purpose: no docstring
  CONSTANTS: ALL_SECTIONS, DEFAULTS, _FUNDER_NORMALIZE, _GEO_NORMALIZE, _THEMATIC_NORMALIZE

=== tor_extractor.py (7838 bytes) ===
  def _error_state(filename, message)
      purpose: Return a well-formed error-state dict.
  def _extract_text_docx(file_bytes)
      purpose: Extract all text from a .docx file, including table cells.
  def _extract_text_pdf(file_bytes)
      purpose: Extract all text from a .pdf file using pdfplumber.
  def _truncate_text(text)
      purpose: Truncate text to at most 15,000 characters.
  def _call_claude(client, user_prompt)
      purpose: Make a single Claude API call and return the raw text response.
  def _strip_markdown_fences(text)
      purpose: no docstring
  def _fill_defaults(data, filename)
      purpose: Ensure all required keys are present in data.
  def extract_tor(file_bytes, filename)
      purpose: Extract structured requirements from a ToR document.
  CONSTANTS: SYSTEM_PROMPT, USER_PROMPT_TEMPLATE, _REQUIRED_KEYS

=== capability_indexer.py (11375 bytes) ===
  def _extract_docx(filepath)
      purpose: Extract text from a .docx file.
  def _extract_pdf(filepath, filename)
      purpose: Extract text from a .pdf file using pdfplumber.
  def chunk_text(text, page_number)
      purpose: Split text into chunks of at most MAX_TOKENS_PER_CHUNK tokens (words),
  def detect_tags(text)
      purpose: Detect geography and thematic tags in text by keyword matching.
  def index_library(force_reindex)
      purpose: Scan CAPABILITY_LIBRARY_PATH for .docx and .pdf files, chunk them,

=== capability_retriever.py (9590 bytes) ===
  def _build_query_string(tor_data)
      purpose: Concatenate thematic_areas, key_requirements, and geography from tor_d
  def _parse_json_list(value)
      purpose: Parse a JSON string back to a list; return [] on failure.
  def _none_if_empty_str(value)
      purpose: Return None if value is an empty string or None, else return value.
  def _none_if_zero(value)
      purpose: Return None if value is 0 or None, else return value.
  def _chunk_satisfies_filters(metadata, filters)
      purpose: Check whether a chunk's metadata satisfies the active filters.
  def retrieve_chunks(tor_data, filters, top_k)
      purpose: Retrieve relevant capability chunks from ChromaDB.

=== draft_generator.py (13767 bytes) ===
  def _strip_markdown_fences(text)
      purpose: no docstring
  def _build_context_block(retrieved_chunks)
      purpose:     Task 5.2: Build a context string from at most 20 chunks.
  def _build_tor_summary(tor_data)
      purpose: Build the TOR summary string for the user prompt.
  def _error_state(message)
      purpose: Return a well-formed error-state dict.
  def _call_claude(client, system, user_prompt)
      purpose: Make a single Claude API call and return the raw text response.
  def _derive_confidence(interpretation_log)
      purpose: Task 5.7: Derive overall confidence from interpretation log entries.
  def _validate_log_entry(entry)
      purpose: Task 5.6: Ensure all required keys exist in an interpretation log entr
  def _validate_and_normalise(data, sections_to_include, retrieved_chunks)
      purpose: Task 5.5 + 5.6 + 5.7: Validate and normalise the parsed GeneratedDraft
  def generate_draft(tor_data, retrieved_chunks, sections_to_include, output_language)
      purpose: Generate a capability statement draft using the Claude API.
  CONSTANTS: ALL_SECTIONS, SYSTEM_PROMPT, _JSON_SCHEMA, _USER_PROMPT_TEMPLATE

=== citation_tagger.py (3078 bytes) ===
  def format_citation(filename, page)
      purpose: Return the formatted display string for a citation.
  def _process_paragraph(paragraph)
      purpose: Process a single paragraph: extract citations, clean text.
  def tag_citations(draft_sections)
      purpose: Process all text sections from a generated draft, stripping inline REF
  CONSTANTS: CLEAN_PATTERN, REF_PATTERN

=== output_formatter.py (9587 bytes) ===
  def _sanitize(text)
      purpose: Remove XML-incompatible control characters from a string.
  def _add_heading(doc, text)
      purpose: Add a bold 14pt Calibri section heading paragraph.
  def _add_body_text(doc, text)
      purpose: Add body text paragraphs (split on \n\n), 11pt Calibri, no bold.
  def _add_citation_line(doc, citation_text)
      purpose: Add an italic gray 9pt Calibri citation line.
  def _add_country_table(doc, country_table)
      purpose: Render country_table as a Word table with 5 columns.
  def _add_horizontal_rule(doc)
      purpose: Add a horizontal rule paragraph.
  def _add_interpretation_log(doc, interpretation_log)
      purpose: Add the interpretation log section with a horizontal rule separator.
  def _add_citations_section(doc, citation_result)
      purpose: Add the Source Citations section from citation_result.
  def write_output(generated_draft, citation_result, output_language, sections_to_include, output_path)
      purpose: Write the capability statement as a formatted .docx file.
  CONSTANTS: BODY_SIZE, CITATION_COLOR, CITATION_SIZE, FONT_NAME, HEADING_SIZE, INTERP_LOG_SIZE, MARGIN, SUBHEADING_SIZE, _CONTROL_CHAR_PATTERN, _REF_STRIP_PATTERN

=== config.py (925 bytes) ===
  CONSTANTS: ANTHROPIC_API_KEY, CAPABILITY_LIBRARY_PATH, CHROMA_DB_PATH, CHUNK_OVERLAP_TOKENS, FUNDER_OPTIONS, GEOGRAPHY_OPTIONS, MAX_RETRIEVAL_RESULTS, MAX_TOKENS_PER_CHUNK, MODEL_NAME, OUTPUT_PATH, THEMATIC_OPTIONS

=== tests/test_app.py (5795 bytes) ===
  def test_app_module_importable()
      purpose: app.py can be imported without raising (mocking streamlit).
  def test_api_key_guard_logic()
      purpose: API key guard correctly identifies missing/empty keys.
  def test_empty_chromadb_guard_logic()
      purpose: Generation is blocked when doc_count == 0.
  def test_no_file_uploaded_guard()
      purpose: Generation is blocked when tor_data is None.
  def test_update_library_calls_index_library()
      purpose: Update Library button logic calls index_library.
  def test_progress_steps_structure()
      purpose: Progress steps list has exactly 5 entries with required keys.
  def test_interpretation_log_confidence_colors()
      purpose: Confidence level maps to correct color indicator.
  def test_download_only_after_generation()
      purpose: Download button condition: both generated_draft and output_file_path m
  def _should_show_download(generated_draft, output_file_path)
      purpose: no docstring

=== tests/test_capability_indexer.py (9415 bytes) ===
  def test_pdfplumber_failure_is_caught_and_skipped(tmp_path, caplog)
      purpose: Requirement 2.9: pdfplumber failure logs warning and skips file withou
  def test_p1_chunk_size_invariant(text)
      purpose: P1: Every chunk has token count ≤ MAX_TOKENS_PER_CHUNK
  def test_p2_chunk_overlap_invariant(text)
      purpose: P2: Consecutive chunk overlap is ≤ CHUNK_OVERLAP_TOKENS
  def test_p3_keyword_detection(keyword)
      purpose: P3: If keyword present in text, it appears in detected tags
  def test_p4_indexing_idempotence(tmp_path)
      purpose: P4: Indexing same document twice without force_reindex produces same c
  def test_p5_summary_accuracy(tmp_path)
      purpose: P5: IndexingSummary counts match actual processed/skipped counts
  def test_p21_chunk_schema_conformance(tmp_path)
      purpose: P21: All stored chunks have required metadata fields with correct type

=== tests/test_capability_retriever.py (9633 bytes) ===
  def seeded_chroma(tmp_path)
      purpose: Creates a temp ChromaDB with 30 test chunks having varied metadata.
  def test_empty_chromadb_returns_empty_result(tmp_path)
      purpose: Requirement 4.6: If ChromaDB contains no documents, retriever returns 
  def _seed_chroma(chroma_path)
      purpose: Seed a ChromaDB at chroma_path with 30 varied test chunks.
  def test_p7_result_count_bound(tmp_path, top_k)
      purpose: P7: Retriever returns at most MAX_RETRIEVAL_RESULTS chunks.
  def test_p8_relevance_scores_non_increasing(tmp_path, query_text)
      purpose: P8: Chunks are ordered by relevance score descending (non-increasing).
  def test_p9_no_duplicate_source_page_pairs(tmp_path, query_text)
      purpose: P9: No two returned chunks share the same (source_file, page_number).
  def test_p10_filter_logic(seeded_chroma, geography_value)
      purpose: P10: All returned chunks satisfy the active geography filter.

=== tests/test_citation_tagger.py (8133 bytes) ===
  def test_ref_tags_removed_from_text()
      purpose: REF tags are stripped from the output text.
  def test_citations_extracted_correctly()
      purpose: Filename and page number are extracted correctly from a REF tag.
  def test_duplicate_citations_deduplicated()
      purpose: Same REF tag appearing twice in one paragraph yields one citation.
  def test_citation_format_string()
      purpose: format_citation returns the expected display string.
  def test_no_ref_tags_returns_empty_citations()
      purpose: A paragraph with no REF tags produces an empty citations list.
  def test_empty_paragraphs_skipped()
      purpose: Paragraphs that are empty after cleaning REF tags are not included.
  def test_non_string_sections_skipped()
      purpose: country_table list value is not processed and does not appear in parag
  def test_multiple_paragraphs_split_correctly()
      purpose: Text separated by double newline produces multiple paragraph entries.
  def test_tag_citations_never_raises()
      purpose: tag_citations must not raise for None, empty dict, or malformed input.
  def test_p12_no_ref_tags_in_output(text_with_ref)
      purpose: P12: After tag_citations, no [REF:...] patterns remain in any paragrap
  def test_p13_duplicate_citations_deduplicated(filename, page)
      purpose: P13: Duplicate [REF:filename:page_N] tags in same paragraph → one cita
  def test_p14_citation_format(filename, page)
      purpose: P14: format_citation produces exactly 'Source: filename, p.N'.
  def test_p11_complement_no_ref_tags_empty_citations(text_without_refs)
      purpose: P11 complement: paragraphs with no REF tags have empty citations list.

=== tests/test_config.py (1704 bytes) ===
  def test_model_name()
      purpose: no docstring
  def test_max_tokens_per_chunk()
      purpose: no docstring
  def test_chunk_overlap_tokens()
      purpose: no docstring
  def test_max_retrieval_results()
      purpose: no docstring
  def test_geography_options_count()
      purpose: no docstring
  def test_geography_options_contents()
      purpose: no docstring
  def test_thematic_options_count()
      purpose: no docstring
  def test_thematic_options_contents()
      purpose: no docstring
  def test_funder_options_count()
      purpose: no docstring
  def test_funder_options_contents()
      purpose: no docstring
  def test_paths_defined()
      purpose: no docstring

=== tests/test_draft_generator.py (15879 bytes) ===
  def _make_tor_data()
      purpose: no docstring
  def _make_chunks(n)
      purpose: no docstring
  def _make_valid_draft_json()
      purpose: no docstring
  def _make_mock_client(response_text)
      purpose: Return a mock Anthropic client that returns the given text.
  def test_claude_api_called_with_max_tokens_16000()
      purpose: Requirement 5.2: Claude API must be called with max_tokens=16000.
  def test_system_prompt_contains_required_instructions()
      purpose: Requirement 5.3: System prompt must contain all required instructions.
  def test_system_prompt_passed_to_claude()
      purpose: System prompt is passed to the Claude API call.
  def test_non_json_response_triggers_retry_then_returns_error()
      purpose: Requirement 5.8: Non-JSON Claude response triggers exactly one retry;
  def test_non_json_first_attempt_valid_second_succeeds()
      purpose: First attempt returns non-JSON, second attempt returns valid JSON — sh
  def test_generate_draft_never_raises_on_bad_input()
      purpose: generate_draft must always return a dict, never raise.
  def test_generate_draft_returns_error_dict_on_api_failure()
      purpose: When the API raises an exception, an error dict is returned.
  def test_missing_section_keys_filled_with_empty_string()
      purpose: Task 5.5: Missing section keys are added with empty string value.
  def test_context_block_empty_chunks_returns_fallback()
      purpose: _build_context_block returns fallback string when chunks list is empty
  def test_p11_ref_tag_in_every_section(sections)
      purpose: P11: Every section string that has content contains at least one REF t
  def test_p17_recency_ordering(projects)
      purpose: P17: Projects sorted by year descending, stable for equal years.
  def test_p20_generated_draft_json_roundtrip(draft)
      purpose: P20: Serialising a GeneratedDraft dict to JSON and deserialising it pr
  def test_p22_interpretation_log_completeness(log_entries)
      purpose: P22: All interpretation_log entries have all required fields.
  def test_p23_context_block_chunk_cap(num_chunks)
      purpose: P23: Context block uses at most 20 chunks regardless of input size.
  def capture_call()
      purpose: no docstring

=== tests/test_output_formatter.py (13944 bytes) ===
  def _make_minimal_draft()
      purpose: no docstring
  def _make_minimal_citation_result()
      purpose: no docstring
  def test_output_file_written_to_output_path(tmp_path)
      purpose: Output file is written to the specified output_path and path is return
  def test_section_headings_in_correct_order(tmp_path)
      purpose: Section headings appear in the document in the specified order.
  def test_document_styles_match_spec(tmp_path)
      purpose: Body text is 11pt, citation runs are 9pt italic, margins are 2.5cm.
  def test_no_ref_tags_in_output_document(tmp_path)
      purpose: No [REF:...] tags appear in the written document paragraphs.
  def test_p15_filename_format(dt)
      purpose: P15: Output filename matches GovRisk_CapabilityStatement_{YYYY-MM-DD}_
  def test_p16_country_table_structure(tmp_path, country_table_data)
      purpose: P16: Word table has exactly 5 columns and 1 header row + N data rows.
  def test_p18_project_experience_order_preserved(tmp_path, project_texts)
      purpose: P18: Project experience entries appear in the document in the same ord

=== tests/test_tor_extractor.py (9160 bytes) ===
  def make_minimal_docx(text)
      purpose: no docstring
  def test_unsupported_file_type_returns_error_dict()
      purpose: Requirement 3.9: Non-.docx/.pdf file returns error dict with LOW confi
  def test_unsupported_file_type_no_extension_returns_error_dict()
      purpose: Files with no extension also return error dict.
  def test_non_json_response_triggers_retry_then_returns_error()
      purpose: Requirement 3.7: Non-JSON Claude response triggers exactly one retry;
  def test_system_prompt_contains_required_instruction()
      purpose: Requirement 3.5: System prompt instructs Claude to respond only with v
  def test_p6_text_truncation(length, seed_char)
      purpose: P6: For any text longer than 15,000 chars, the truncation logic produc
  def test_p19_tor_data_json_roundtrip(tor_data)
      purpose: P19: Serialising a TorData dict to JSON and deserialising it produces
  def test_source_file_always_overridden_by_filename()
      purpose: The source_file field in the returned dict must always equal the filen
  def test_missing_keys_filled_with_defaults()
      purpose: If Claude returns JSON missing some keys, defaults are filled in.
  def test_error_state_source_file_matches_filename()
      purpose: Error state dict always has source_file equal to the filename argument
  def capture_call()
      purpose: no docstring