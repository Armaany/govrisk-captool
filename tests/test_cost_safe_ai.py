"""Regression tests for cost-safe paid AI operations."""

import ast
import io
import json
import os
from pathlib import Path
import sys
import threading
from unittest.mock import ANY, MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import ai_workflows
import pytest
from ai_request_cache import RequestInProgressError, run_cached_json, safe_ai_error
from config import (
    EXTRACTION_TIMEOUT_SECONDS,
    EXTRACTION_MAX_TOKENS,
    EXTRACTION_MODEL_NAME,
    GENERATION_TIMEOUT_SECONDS,
    GENERATION_MAX_TOKENS,
    GENERATION_MODEL_NAME,
)
from draft_generator import generate_draft
from tor_extractor import extract_tor


ROOT = Path(__file__).resolve().parents[1]


def _response(text: str):
    response = MagicMock()
    response.content = [MagicMock(text=text)]
    return response


def _draft_result():
    return {
        "sections": {"opening_statement": "Evidence [REF:a.pdf:page_1]"},
        "interpretation_log": [],
        "summary": {},
    }


def _minimal_docx() -> bytes:
    from docx import Document

    document = Document()
    document.add_paragraph("Test ToR content about AML/CFT in Mexico.")
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def test_same_tor_file_reuses_success_without_second_producer_call(tmp_path):
    expected = {"title": "Test", "source_file": "tor.pdf"}
    producer = MagicMock(return_value=expected)
    with patch("ai_workflows.extract_tor", producer):
        first, first_hit = ai_workflows.extract_tor_cached(
            b"same bytes", "tor.pdf", cache_dir=str(tmp_path)
        )
        second, second_hit = ai_workflows.extract_tor_cached(
            b"same bytes", "tor.pdf", cache_dir=str(tmp_path)
        )
    assert first == second == expected
    assert first_hit is False
    assert second_hit is True
    producer.assert_called_once()


def test_failed_result_is_not_cached(tmp_path):
    producer = MagicMock(side_effect=[{"error": "failed"}, {"title": "recovered"}])
    payload = {"same": True}
    first, first_hit = run_cached_json(
        "test-operation", payload, producer, cache_dir=str(tmp_path)
    )
    second, second_hit = run_cached_json(
        "test-operation", payload, producer, cache_dir=str(tmp_path)
    )
    assert first == {"error": "failed"}
    assert second == {"title": "recovered"}
    assert first_hit is second_hit is False
    assert producer.call_count == 2


def test_same_generation_inputs_reuse_success(tmp_path):
    expected = _draft_result()
    producer = MagicMock(return_value=expected)
    tor = {"title": "Test"}
    chunks = [{"chunk_id": "1", "text": "Evidence"}]
    with patch("ai_workflows.generate_draft", producer):
        first, first_hit = ai_workflows.generate_draft_cached(
            tor, chunks, cache_dir=str(tmp_path)
        )
        second, second_hit = ai_workflows.generate_draft_cached(
            tor, chunks, cache_dir=str(tmp_path)
        )
    assert first == second == expected
    assert first_hit is False
    assert second_hit is True
    producer.assert_called_once()


def test_changed_generation_input_gets_distinct_request(tmp_path):
    producer = MagicMock(return_value=_draft_result())
    with patch("ai_workflows.generate_draft", producer):
        ai_workflows.generate_draft_cached(
            {"title": "A"}, [{"text": "one"}], cache_dir=str(tmp_path)
        )
        ai_workflows.generate_draft_cached(
            {"title": "B"}, [{"text": "one"}], cache_dir=str(tmp_path)
        )
    assert producer.call_count == 2


def test_identical_concurrent_request_is_not_sent_twice(tmp_path):
    started = threading.Event()
    release = threading.Event()

    def slow_producer():
        started.set()
        assert release.wait(timeout=2)
        return {"ok": True}

    first_result = []
    thread = threading.Thread(
        target=lambda: first_result.append(
            run_cached_json(
                "concurrent", {"same": True}, slow_producer, cache_dir=str(tmp_path)
            )
        )
    )
    thread.start()
    assert started.wait(timeout=2)
    try:
        with pytest.raises(RequestInProgressError):
            run_cached_json(
                "concurrent",
                {"same": True},
                lambda: {"should_not_run": True},
                cache_dir=str(tmp_path),
            )
    finally:
        release.set()
        thread.join(timeout=2)
    assert first_result == [({"ok": True}, False)]


def test_extraction_client_has_timeout_no_sdk_retries_and_small_model():
    client = MagicMock()
    provider_response = _response(json.dumps({"title": "Test"}))
    provider_response.usage.input_tokens = 321
    provider_response.usage.output_tokens = 123
    client.messages.create.return_value = provider_response
    with patch("tor_extractor.anthropic.Anthropic", return_value=client) as factory:
        result = extract_tor(_minimal_docx(), "test.docx")
    assert "error" not in result
    factory.assert_called_once_with(
        api_key=ANY,
        timeout=EXTRACTION_TIMEOUT_SECONDS,
        max_retries=0,
    )
    kwargs = client.messages.create.call_args.kwargs
    assert kwargs["model"] == EXTRACTION_MODEL_NAME
    assert kwargs["max_tokens"] == EXTRACTION_MAX_TOKENS
    assert '"paragraphs": List' not in kwargs["messages"][0]["content"]
    assert result["_ai_usage"] == {
        "model": EXTRACTION_MODEL_NAME,
        "input_tokens": 321,
        "output_tokens": 123,
    }


def test_generation_client_has_timeout_no_sdk_retries_and_bounded_output():
    client = MagicMock()
    client.messages.create.return_value = _response(json.dumps(_draft_result()))
    with patch("draft_generator.anthropic.Anthropic", return_value=client) as factory:
        result = generate_draft(
            {"title": "Test", "geography": [], "thematic_areas": [], "key_requirements": []},
            [{"text": "Evidence", "source_file": "a.pdf", "page_number": 1}],
        )
    assert "error" not in result
    assert factory.call_args.kwargs["timeout"] == GENERATION_TIMEOUT_SECONDS
    assert factory.call_args.kwargs["max_retries"] == 0
    kwargs = client.messages.create.call_args.kwargs
    assert kwargs["model"] == GENERATION_MODEL_NAME
    assert kwargs["max_tokens"] == GENERATION_MAX_TOKENS


def test_safe_error_does_not_render_provider_exception_text():
    secret = "sk-ant-SECRET-SENTINEL"
    message = safe_ai_error(Exception(f"request failed with {secret}"), "Draft", 90)
    assert secret not in message
    assert "No automatic retry" in message


def test_app_has_one_paid_generation_button_and_no_auto_trigger():
    app_source = (ROOT / "app.py").read_text(encoding="utf-8")
    discovery_source = (ROOT / "discovery_panel.py").read_text(encoding="utf-8")
    ast.parse(app_source)
    ast.parse(discovery_source)
    combined = app_source + "\n" + discovery_source
    assert combined.count('"🚀 Generate Capability Statement"') == 1
    assert "drp_trigger_generate" not in app_source
    assert "✅ Confirm evidence selection" in discovery_source


def test_usage_notice_reports_tokens_without_estimating_money():
    from app import _usage_notice

    notice = _usage_notice(
        "Completed.",
        {
            "_ai_usage": {
                "model": "test-model",
                "input_tokens": 1200,
                "output_tokens": 300,
            }
        },
    )
    assert notice == "Completed. (test-model · 1,200 input tokens · 300 output tokens)"
    assert "$" not in notice


def test_tor_analysis_requires_explicit_button():
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    assert '"Analyze ToR with AI"' in source
    assert "if analyze_clicked:" in source
    assert "extract_tor_cached" in source

