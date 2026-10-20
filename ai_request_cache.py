"""Cost-safe, reconnect-tolerant cache for paid AI operations.

Only successful structured results are cached.  Cache filenames are SHA-256
digests, so document names and prompt text never appear in the filesystem path.
The cache lives under ``output/`` by default, which is already ignored by Git.
It is intentionally a response cache, not a source-of-truth document store.
"""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
import os
import tempfile
import threading
from typing import Callable

from config import OUTPUT_PATH


CACHE_SCHEMA_VERSION = 1
DEFAULT_CACHE_DIR = os.getenv(
    "AI_RESPONSE_CACHE_PATH",
    os.path.join(OUTPUT_PATH, ".ai_response_cache"),
)

_locks_guard = threading.Lock()
_request_locks: dict[str, threading.Lock] = {}


class RequestInProgressError(RuntimeError):
    """Raised when an identical paid request is already running."""


def safe_ai_error(exc: Exception, action: str, timeout_seconds: int) -> str:
    """Map provider exceptions to actionable text without exposing raw details."""
    name = type(exc).__name__.lower()
    status = getattr(exc, "status_code", None)
    if "timeout" in name:
        return (
            f"{action} timed out after {timeout_seconds} seconds. "
            "No automatic retry was made."
        )
    if status in (401, 403) or "authentication" in name or "permission" in name:
        return f"{action} was not authorised. Check the configured API key."
    if status == 429 or "ratelimit" in name or "rate_limit" in name:
        return (
            f"{action} was stopped by the provider limit or credit balance. "
            "No automatic retry was made."
        )
    if isinstance(status, int) and status >= 500:
        return (
            f"{action} could not complete because the AI provider was unavailable. "
            "No automatic retry was made."
        )
    if "connection" in name:
        return (
            f"{action} could not connect to the AI provider. "
            "No automatic retry was made."
        )
    return f"{action} failed. No automatic retry was made."


def response_usage(response: object, model: str) -> dict:
    """Return only provider-reported integer token counts, when available."""
    usage = getattr(response, "usage", None)
    input_tokens = getattr(usage, "input_tokens", None)
    output_tokens = getattr(usage, "output_tokens", None)
    result = {"model": model}
    if isinstance(input_tokens, int) and not isinstance(input_tokens, bool):
        result["input_tokens"] = input_tokens
    if isinstance(output_tokens, int) and not isinstance(output_tokens, bool):
        result["output_tokens"] = output_tokens
    return result


def request_fingerprint(operation: str, payload: object) -> str:
    """Return a deterministic digest without logging or storing raw inputs."""
    canonical = json.dumps(
        {
            "cache_schema": CACHE_SCHEMA_VERSION,
            "operation": operation,
            "payload": payload,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _cache_file(operation: str, fingerprint: str, cache_dir: str) -> str:
    safe_operation = "".join(
        char if char.isalnum() or char in "-_" else "_" for char in operation
    )
    return os.path.join(cache_dir, f"{safe_operation}-{fingerprint}.json")


def _load_success(operation: str, fingerprint: str, cache_dir: str) -> dict | None:
    path = _cache_file(operation, fingerprint, cache_dir)
    try:
        with open(path, encoding="utf-8") as handle:
            envelope = json.load(handle)
        if (
            envelope.get("cache_schema") == CACHE_SCHEMA_VERSION
            and envelope.get("operation") == operation
            and envelope.get("fingerprint") == fingerprint
            and isinstance(envelope.get("result"), dict)
            and "error" not in envelope["result"]
        ):
            return envelope["result"]
    except (OSError, ValueError, TypeError):
        return None
    return None


def _save_success(
    operation: str,
    fingerprint: str,
    result: dict,
    cache_dir: str,
) -> None:
    if not isinstance(result, dict) or "error" in result:
        return
    os.makedirs(cache_dir, exist_ok=True)
    envelope = {
        "cache_schema": CACHE_SCHEMA_VERSION,
        "operation": operation,
        "fingerprint": fingerprint,
        "result": result,
    }
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=cache_dir,
            prefix=".ai-cache-",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_path = handle.name
            json.dump(envelope, handle, ensure_ascii=False, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, _cache_file(operation, fingerprint, cache_dir))
    except OSError:
        # A cache problem must not turn a successful paid response into failure.
        if temp_path:
            try:
                os.unlink(temp_path)
            except OSError:
                pass


@contextmanager
def _single_flight(fingerprint: str):
    with _locks_guard:
        lock = _request_locks.setdefault(fingerprint, threading.Lock())
    if not lock.acquire(blocking=False):
        raise RequestInProgressError(
            "An identical AI request is already running. Wait for it to finish; "
            "no second request was sent."
        )
    try:
        yield
    finally:
        lock.release()


def run_cached_json(
    operation: str,
    payload: object,
    producer: Callable[[], dict],
    *,
    cache_dir: str | None = None,
) -> tuple[dict, bool]:
    """Run at most one identical paid operation and cache successful JSON.

    Returns ``(result, cache_hit)``.  Failed results are never cached, allowing
    the user to make a deliberate retry after correcting the cause.
    """
    target_dir = cache_dir or DEFAULT_CACHE_DIR
    fingerprint = request_fingerprint(operation, payload)
    cached = _load_success(operation, fingerprint, target_dir)
    if cached is not None:
        return deepcopy(cached), True

    with _single_flight(fingerprint):
        # Another request may have completed between the first read and lock.
        cached = _load_success(operation, fingerprint, target_dir)
        if cached is not None:
            return deepcopy(cached), True
        result = producer()
        _save_success(operation, fingerprint, result, target_dir)
        return result, False
