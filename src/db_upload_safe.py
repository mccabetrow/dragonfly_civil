from __future__ import annotations

import logging
from collections.abc import Iterable, Iterator
from typing import Dict, List, Tuple, TypeVar

from .logging_setup import configure_logging
from .supabase_client import create_supabase_client
from tenacity import Retrying, retry_if_exception, stop_after_attempt, wait_exponential

configure_logging()
logger = logging.getLogger(__name__)

T = TypeVar("T")
TRANSIENT_STATUS_CODES = {"429", "500", "502", "503", "504"}


class ChunkUploadError(RuntimeError):
    """Raised when a specific chunk fails to upload after retries."""

    def __init__(self, chunk: List[Dict], original_exception: Exception):
        message = f"Chunk upload failed: {original_exception}"
        super().__init__(message)
        self.chunk = chunk
        self.original_exception = original_exception


def chunked(iterable: Iterable[T], size: int) -> Iterator[List[T]]:
    if size <= 0:
        raise ValueError("chunk size must be positive")

    buffer: List[T] = []
    for item in iterable:
        buffer.append(item)
        if len(buffer) == size:
            yield buffer.copy()
            buffer.clear()

    if buffer:
        yield buffer.copy()


def _should_retry(exception: BaseException) -> bool:
    if not isinstance(exception, RuntimeError):
        return False

    message = str(exception)
    return any(f"status={code}" in message for code in TRANSIENT_STATUS_CODES)


def _resolve_status_code(response, data):
    status = getattr(response, "status_code", None)
    if status is not None:
        return status

    request = getattr(response, "_request", None)
    if request is not None:
        request_status = getattr(request, "status_code", None)
        if request_status is not None:
            logger.debug("Resolved status_code from response._request.status_code=%s", request_status)
            return request_status
        request_response = getattr(request, "response", None)
        if request_response is not None:
            nested_status = getattr(request_response, "status_code", None)
            if nested_status is not None:
                logger.debug(
                    "Resolved status_code from response._request.response.status_code=%s",
                    nested_status,
                )
                return nested_status

    raw_response = getattr(response, "response", None)
    if raw_response is not None:
        raw_status = getattr(raw_response, "status_code", None)
        if raw_status is not None:
            logger.debug("Resolved status_code from response.response.status_code=%s", raw_status)
            return raw_status

    http_response = getattr(response, "http_response", None)
    if http_response is not None:
        http_status = getattr(http_response, "status_code", None)
        if http_status is not None:
            logger.debug(
                "Resolved status_code from response.http_response.status_code=%s",
                http_status,
            )
            return http_status

    if isinstance(data, list):
        logger.debug(
            "Response missing status_code; assuming 200 due to list payload from Supabase client."
        )
        return 200

    raise RuntimeError("Mutation returned no status and non-list data; probable client mismatch.")


def upsert_public_judgments(rows: List[Dict]) -> Tuple[int, List[Dict], int]:
    if not rows:
        return 0, [], 200

    normalized_rows = []
    for row in rows:
        mapped = dict(row)
        if "source" in mapped and "source_file" not in mapped:
            mapped["source_file"] = mapped.pop("source")
        normalized_rows.append(mapped)

    preview_keys = list(normalized_rows[0])[:6]
    preview = {key: normalized_rows[0].get(key) for key in preview_keys}
    logger.info("First row preview: %s", preview)

    client = create_supabase_client()

    response = (
        client
        .table("judgments")
        .upsert(
            normalized_rows,
            on_conflict="case_number",
            returning="representation",  # type: ignore[arg-type]
            count="exact",  # type: ignore[arg-type]
        )
        .execute()
    )

    data = getattr(response, "data", None)
    count_header = getattr(response, "count", None)
    error = getattr(response, "error", None)
    content_range = None
    headers = getattr(response, "headers", None)
    if isinstance(headers, dict):
        content_range = headers.get("Content-Range") or headers.get("content-range")
    if content_range is None:
        content_range = getattr(response, "content_range", None)

    try:
        status_code = _resolve_status_code(response, data)
    except RuntimeError:
        logger.error("Unable to determine status_code for response: %s", response)
        raise

    if content_range:
        logger.debug("Server Content-Range header: %s", content_range)

    if error is not None or status_code >= 400:
        logger.error("Upload failed (status=%s). Full response: %s", status_code, response)
        raise RuntimeError(f"Upload failed (status={status_code}). Full response: {response}")

    rows_returned = len(data or [])
    effective_count = count_header if isinstance(count_header, int) else rows_returned

    logger.info(
        "Status code: %s | Rows returned: %s | Count header: %s",
        status_code,
        rows_returned,
        count_header,
    )

    return effective_count, (data or []), status_code


def upsert_public_judgments_chunked(
    rows: Iterable[Dict],
    *,
    chunk_size: int = 500,
    max_retries: int = 3,
) -> Tuple[int, List[Dict], int]:
    rows_list = list(rows)
    if not rows_list:
        return 0, [], 200

    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if max_retries < 1:
        raise ValueError("max_retries must be at least 1")

    retryer = Retrying(
        stop=stop_after_attempt(max_retries),
        wait=wait_exponential(multiplier=0.1, min=0.1, max=5),
        retry=retry_if_exception(_should_retry),
        reraise=True,
    )

    total_effective = 0
    aggregated_data: List[Dict] = []
    last_status = 200

    for chunk in chunked(rows_list, chunk_size):
        try:
            effective_count, data, status_code = retryer(upsert_public_judgments, chunk)
        except Exception as exc:  # pragma: no cover - propagated to caller
            raise ChunkUploadError(chunk, exc) from exc
        total_effective += int(effective_count or 0)
        aggregated_data.extend(data or [])
        last_status = status_code

    return total_effective, aggregated_data, last_status
