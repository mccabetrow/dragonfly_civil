"""File watcher for ingesting CSV data into Supabase."""

import argparse
import hashlib
import json
import logging
import math
import os
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
import time

import pandas as pd
import yaml

from src.db_upload_safe import (
    ChunkUploadError,
    upsert_public_judgments,
    upsert_public_judgments_chunked,
)
from src.logging_setup import configure_logging
from src.telemetry import log_run_start, log_run_ok, log_run_error
from src.settings import get_settings as get_app_settings
from workers.queue_client import QueueClient, QueueRpcNotFound

configure_logging()
logger = logging.getLogger(__name__)

DATA_IN_DIR = Path("data_in")
DATA_PROCESSED_DIR = Path("data_processed")
DATA_ERROR_DIR = Path("data_error")
RUN_DIR = Path("run")
STATE_DIR = Path("state")
LOCKFILE_PATH = RUN_DIR / "judgment_watcher.lock"
MANIFEST_PATH = STATE_DIR / "manifest.jsonl"
SCHEMA_MAP_PATH = Path("config/schema_map.yaml")
POLL_INTERVAL_SECONDS = 2


PROCESSED_HASHES: set[str] = set()
_MANIFEST_LOADED = False
SCHEMA_MAP: dict[str, list[str]] = {}
SCHEMA_DEFAULTS: dict[str, object] = {}
_SCHEMA_LOADED = False


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Watch a directory for CSV files and load them into Supabase."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and normalize files, preview the first row, and exit without uploading or moving files.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Process the current queue of files one time, then exit instead of continuing to poll.",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=float(POLL_INTERVAL_SECONDS),
        help="Polling interval in seconds when watching for files (default: 2).",
    )
    return parser.parse_args()


allowed = {
    "source",
    "case_number",
    "status",
    "filing_court",
    "filing_date",
    "judgment_amount",
}
REQUIRED_COLUMN = "case_number"
OPTIONAL_DEFAULTS = {
    "source": "csv",
    "status": "ingested",
    "filing_court": None,
    "filing_date": None,
    "judgment_amount": None,
}
COLUMN_ORDER = [
    "case_number",
    "source",
    "status",
    "filing_court",
    "filing_date",
    "judgment_amount",
]


def _ensure_directories() -> None:
    for directory in (DATA_IN_DIR, DATA_PROCESSED_DIR, DATA_ERROR_DIR, RUN_DIR, STATE_DIR):
        directory.mkdir(parents=True, exist_ok=True)


def _load_schema_map() -> None:
    global SCHEMA_MAP, SCHEMA_DEFAULTS, _SCHEMA_LOADED
    if _SCHEMA_LOADED:
        return

    if not SCHEMA_MAP_PATH.exists():
        SCHEMA_MAP = {}
        SCHEMA_DEFAULTS = {}
        _SCHEMA_LOADED = True
        return

    with SCHEMA_MAP_PATH.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}

    columns = data.get("columns", {}) if isinstance(data, dict) else {}
    defaults = data.get("defaults", {}) if isinstance(data, dict) else {}

    normalized_columns: dict[str, list[str]] = {}
    for target, aliases in columns.items():
        if not isinstance(target, str):
            continue
        if isinstance(aliases, list):
            normalized_columns[target] = [alias.lower() for alias in aliases if isinstance(alias, str)]
        elif isinstance(aliases, str):
            normalized_columns[target] = [aliases.lower()]

    SCHEMA_MAP = normalized_columns
    SCHEMA_DEFAULTS = {k: v for k, v in defaults.items() if isinstance(k, str)} if isinstance(defaults, dict) else {}
    _SCHEMA_LOADED = True


def compute_sha256(path: Path) -> str:
    sha256 = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def _ensure_manifest_initialized() -> None:
    global PROCESSED_HASHES, _MANIFEST_LOADED
    if _MANIFEST_LOADED:
        return

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    if not MANIFEST_PATH.exists():
        MANIFEST_PATH.touch()
        PROCESSED_HASHES = set()
        _MANIFEST_LOADED = True
        return

    hashes: set[str] = set()
    try:
        with MANIFEST_PATH.open("r", encoding="utf-8") as manifest_file:
            for line in manifest_file:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                sha_value = record.get("sha256")
                if isinstance(sha_value, str):
                    hashes.add(sha_value)
    except OSError:
        hashes = set()

    PROCESSED_HASHES = hashes
    _MANIFEST_LOADED = True


def _append_manifest(sha256_hash: str, filename: str) -> None:
    _ensure_manifest_initialized()
    record = {
        "sha256": sha256_hash,
        "filename": filename,
        "processed_at": datetime.now(timezone.utc).isoformat(),
    }
    with MANIFEST_PATH.open("a", encoding="utf-8") as manifest_file:
        manifest_file.write(json.dumps(record) + "\n")
    PROCESSED_HASHES.add(sha256_hash)


def _move_file(file_path: Path, destination_dir: Path) -> Path:
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / file_path.name
    if destination.exists():
        destination.unlink()
    return file_path.replace(destination)


def _write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial_path = path.with_suffix(path.suffix + ".partial")
    try:
        partial_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        partial_path.replace(path)
    finally:
        if partial_path.exists():
            partial_path.unlink(missing_ok=True)


def _handle_chunk_failure(
    file_path: Path,
    file_hash: str,
    chunk_error: ChunkUploadError,
    run_id: str | None,
    run_details: dict[str, object],
    total_rows: int,
    log_extra: dict[str, object] | None = None,
) -> None:
    extra: dict[str, object] = dict(log_extra) if log_extra else {}
    extra.setdefault("run_id", run_id or "-")
    extra.setdefault("file", file_path.name)

    destination = _move_file(file_path, DATA_ERROR_DIR)
    logger.info("Moved file to %s after chunk failure", destination, extra=extra)

    error_info = {
        "message": str(chunk_error.original_exception),
        "type": chunk_error.original_exception.__class__.__name__,
    }

    error_payload = {
        "file": destination.name,
        "sha256": file_hash,
        "total_rows": total_rows,
        "failed_chunk_size": len(chunk_error.chunk),
        "failed_chunk_preview": chunk_error.chunk[:5],
        "error": error_info,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    err_path = destination.with_name(f"{destination.name}.err.json")
    _write_json_atomic(err_path, error_payload)
    logger.info("Wrote chunk failure report to %s", err_path, extra=extra)

    if run_id:
        telemetry_details = {
            **run_details,
            "row_count": total_rows,
            "failed_chunk_size": len(chunk_error.chunk),
        }
        log_run_error(run_id, error_info, telemetry_details)


def _pid_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True

    if os.name == "nt":
        try:
            import ctypes

            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if handle:
                kernel32.CloseHandle(handle)
                return True
            return False
        except Exception:
            return True

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except Exception:
        return True
    else:
        return True


def _acquire_lock() -> bool:
    LOCKFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    if LOCKFILE_PATH.exists():
        try:
            existing_pid = int(LOCKFILE_PATH.read_text().strip())
        except ValueError:
            existing_pid = None

        if existing_pid and _pid_is_alive(existing_pid):
            logger.warning(
                "Watcher already running with PID %s; exiting.",
                existing_pid,
            )
            return False

        try:
            LOCKFILE_PATH.unlink(missing_ok=True)
        except OSError:
            logger.warning("Could not remove stale lockfile at %s", LOCKFILE_PATH)
            return False

    LOCKFILE_PATH.write_text(str(os.getpid()))
    return True


def _release_lock() -> None:
    try:
        if not LOCKFILE_PATH.exists():
            return
        try:
            recorded_pid = LOCKFILE_PATH.read_text().strip()
        except OSError:
            recorded_pid = ""
        if recorded_pid and recorded_pid != str(os.getpid()):
            return
        LOCKFILE_PATH.unlink(missing_ok=True)
    except Exception:
        logger.debug("Failed to remove lockfile", exc_info=True)


def _normalize_dataframe(df: pd.DataFrame) -> list[dict]:
    _load_schema_map()
    frame = df.copy()
    frame.columns = [col.strip() for col in frame.columns]
    frame = frame.dropna(how="all")

    defaults = {**OPTIONAL_DEFAULTS, **SCHEMA_DEFAULTS}

    header_map: dict[str, str] = {}
    claimed_targets: set[str] = set()
    for original in frame.columns:
        alias_lower = original.lower()
        for target, aliases in SCHEMA_MAP.items():
            if target in claimed_targets:
                continue
            if alias_lower in aliases and target in allowed:
                header_map[original] = target
                claimed_targets.add(target)
                break

    mapped_columns = {original: header_map.get(original, original) for original in frame.columns}
    frame = frame.rename(columns=mapped_columns)

    allowed_columns_present = [col for col in frame.columns if col in allowed]
    if REQUIRED_COLUMN not in allowed_columns_present:
        return []

    selected_columns = [REQUIRED_COLUMN] + [col for col in defaults if col in allowed_columns_present]
    frame = frame[selected_columns]

    for column, default in defaults.items():
        if column not in frame.columns:
            frame[column] = default

    ordered_existing_columns = [col for col in COLUMN_ORDER if col in frame.columns]
    frame = frame[ordered_existing_columns]

    records: list[dict] = []
    for index, row in frame.iterrows():
        case_value = row.get(REQUIRED_COLUMN)
        if _is_missing(case_value):
            logger.warning("Skipping row without case_number (index=%s).", index)
            continue

        record: dict = {}
        for column in COLUMN_ORDER:
            if column not in allowed:
                continue
            value = row.get(column)
            normalized_value = _normalize_value(column, value)
            if normalized_value is None and column in defaults:
                normalized_value = defaults[column]
            if normalized_value is not None:
                record[column] = normalized_value

        records.append(record)

    return records


def _normalize_value(column: str, value):
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, str):
        cleaned = value.strip()
        if cleaned.lower() in {"", "nan", "none", "null"}:
            return None

        if column == "filing_date":
            try:
                parsed = pd.to_datetime(cleaned, errors="raise")
                return parsed.strftime("%Y-%m-%d")
            except Exception:
                return None

        if column == "judgment_amount":
            normalized = cleaned.replace("$", "").replace(",", "").replace(" ", "")
            if normalized.startswith("(") and normalized.endswith(")"):
                normalized = f"-{normalized[1:-1]}"
            try:
                decimal_value = Decimal(normalized)
            except (InvalidOperation, ValueError):
                return None
            try:
                quantized = decimal_value.quantize(Decimal("0.01"))
            except InvalidOperation:
                return None
            return format(quantized, "f")

        return cleaned
    return value


def _is_missing(value) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned.lower() in {"", "nan", "none", "null"}
    return False


def _queue_rpc_endpoint(endpoint: str) -> str:
    try:
        settings = get_app_settings()
        base_url = settings.supabase_url.rstrip("/")
    except Exception:
        return f"/rest/v1/rpc/{endpoint}"
    return f"{base_url}/rest/v1/rpc/{endpoint}"


def process_file(file_path: Path, *, dry_run: bool = False) -> int:
    file_name = file_path.name
    log_extra: dict[str, object] = {"run_id": "-", "file": file_name}
    logger.info("Processing new file: %s", file_name, extra=log_extra)

    if dry_run:
        logger.info(
            "Dry-run mode active; no Supabase upserts or file moves will occur.",
            extra=log_extra,
        )
        try:
            try:
                dataframe = pd.read_csv(file_path, dtype=str, keep_default_na=False)
            except Exception:
                dataframe = pd.read_csv(file_path, dtype=str)

            dataframe = dataframe.replace({"": None})
            records = _normalize_dataframe(dataframe)

            if not records:
                logger.info("Dry-run: no valid data found in file.", extra=log_extra)
                return 0

            preview_keys = list(records[0])[:6]
            preview = {key: records[0].get(key) for key in preview_keys}
            logger.info(
                "Dry-run: %s valid records detected. First row preview: %s",
                len(records),
                preview,
                extra=log_extra,
            )
        except Exception:
            logger.exception("Dry-run preview failed for %s", file_name, extra=log_extra)
        return 0

    run_id: str | None = None
    run_details: dict[str, object] = {"file": file_name}
    records: list[dict] | None = None

    try:
        _ensure_manifest_initialized()
        file_hash = compute_sha256(file_path)
        run_details["sha256"] = file_hash
        run_id = log_run_start("csv_ingest", run_details)
        log_extra["run_id"] = run_id or "-"

        if file_hash in PROCESSED_HASHES:
            logger.info(
                "Already processed (hash=%s); moving to processed.",
                file_hash,
                extra=log_extra,
            )
            destination = _move_file(file_path, DATA_PROCESSED_DIR)
            logger.info("Moved file to %s", destination, extra=log_extra)
            if run_id:
                log_run_ok(
                    run_id,
                    {
                        **run_details,
                        "row_count": 0,
                        "skipped": True,
                        "reason": "duplicate_hash",
                    },
                )
            return 0

        try:
            dataframe = pd.read_csv(file_path, dtype=str, keep_default_na=False)
        except Exception:
            dataframe = pd.read_csv(file_path, dtype=str)

        dataframe = dataframe.replace({"": None})
        records = _normalize_dataframe(dataframe)

        if not records:
            logger.info(
                "No valid data found in file. Moving to processed.",
                extra=log_extra,
            )
            destination = _move_file(file_path, DATA_PROCESSED_DIR)
            logger.info("Moved file to %s", destination, extra=log_extra)
            if run_id:
                log_run_ok(
                    run_id,
                    {
                        **run_details,
                        "row_count": 0,
                        "skipped": False,
                        "reason": "no_valid_rows",
                    },
                )
            return 0

        logger.info(
            "Found %s valid records. Uploading to Supabase...",
            len(records),
            extra=log_extra,
        )
        preview_keys = list(records[0])[:6]
        preview = {key: records[0].get(key) for key in preview_keys}
        logger.info("First row preview: %s", preview, extra=log_extra)
        try:
            if len(records) > 500:
                logger.info(
                    "Uploading in chunks of 500 to avoid overloading PostgREST",
                    extra=log_extra,
                )
                effective_count, returned_rows, status_code = upsert_public_judgments_chunked(records)
            else:
                effective_count, returned_rows, status_code = upsert_public_judgments(records)
        except ChunkUploadError as chunk_exc:
            _handle_chunk_failure(
                file_path,
                file_hash,
                chunk_exc,
                run_id,
                run_details,
                len(records),
                log_extra,
            )
            return 1
        logger.info(
            "Upload successful! Effective count: %s | Returned rows: %s | Status: %s",
            effective_count,
            len(returned_rows),
            status_code,
            extra=log_extra,
        )

        case_numbers = {
            str(row.get("case_number")).strip()
            for row in (returned_rows or [])
            if isinstance(row, dict) and row.get("case_number")
        }
        queue_errors = False
        queue_rpc_missing = False
        if case_numbers:
            rpc_base_url: str | None = None
            try:
                with QueueClient() as queue_client:
                    rpc_base_url = queue_client.rpc_base_url
                    for case_number in case_numbers:
                        idempotency_key = f"csv:{case_number}"
                        try:
                            queue_client.enqueue(
                                "enrich",
                                {"case_number": case_number},
                                idempotency_key,
                            )
                            logger.debug(
                                "Enqueued enrich job with kind=%s idempotency_key=%s",
                                "enrich",
                                idempotency_key,
                                extra=log_extra,
                            )
                        except QueueRpcNotFound:
                            queue_errors = True
                            queue_rpc_missing = True
                            rpc_url = f"{queue_client.rpc_base_url}/queue_job"
                            logger.error(
                                "Supabase queue RPC missing at %s; apply latest migrations before ingesting.",
                                rpc_url,
                                extra=log_extra,
                            )
                            break
                        except Exception as exc:
                            queue_errors = True
                            logger.warning(
                                "Failed to enqueue enrich job for case %s: %s",
                                case_number,
                                exc,
                                extra=log_extra,
                            )
            except QueueRpcNotFound:
                queue_errors = True
                queue_rpc_missing = True
                rpc_url = f"{rpc_base_url or _queue_rpc_endpoint('queue_job')}"
                logger.error(
                    "Supabase queue RPC missing at %s; apply latest migrations before ingesting.",
                    rpc_url,
                    extra=log_extra,
                )
            except Exception:
                queue_errors = True
                logger.exception(
                    "Failed to enqueue enrich jobs for uploaded cases",
                    extra=log_extra,
                )
        _append_manifest(file_hash, file_name)
        destination = _move_file(file_path, DATA_PROCESSED_DIR)
        logger.info("Moved file to %s", destination, extra=log_extra)
        if run_id:
            telemetry_details: dict[str, object] = {
                **run_details,
                "row_count": len(records),
                "skipped": False,
            }
            if queue_errors:
                telemetry_details["queue_errors"] = True
            if queue_rpc_missing:
                telemetry_details["queue_rpc_missing"] = True
            log_run_ok(
                run_id,
                telemetry_details,
                status="ok_with_queue_errors" if queue_errors else "ok",
            )
        if queue_rpc_missing:
            return 1
        return 0

    except Exception as exc:
        logger.exception("Upload failed while processing %s", file_name, extra=log_extra)
        error_info = {
            "message": str(exc),
            "type": exc.__class__.__name__,
        }
        if file_path.exists():
            destination = _move_file(file_path, DATA_ERROR_DIR)
            logger.info("Moved problematic file to %s", destination, extra=log_extra)
            error_payload = {
                "file": destination.name,
                "sha256": run_details.get("sha256"),
                "row_count": len(records) if records is not None else 0,
                "error": error_info,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            err_path = destination.with_name(f"{destination.name}.err.json")
            _write_json_atomic(err_path, error_payload)
            logger.info("Wrote failure report to %s", err_path, extra=log_extra)
        if run_id:
            error_details: dict[str, object] = {**run_details}
            if records is not None:
                error_details["row_count"] = len(records)
            log_run_error(run_id, error_info, error_details)
        return 1


def main() -> int:
    args = _parse_args()
    _ensure_directories()
    _ensure_manifest_initialized()
    if not _acquire_lock():
        return 0

    poll_interval = args.interval if args.interval > 0 else float(POLL_INTERVAL_SECONDS)
    if args.interval <= 0:
        logger.warning(
            "Polling interval must be positive; defaulting to %s seconds.",
            POLL_INTERVAL_SECONDS,
        )
    run_once = args.dry_run or args.once

    logger.info("Starting data ingestor")
    logger.info(
        "Mode -> dry_run=%s, once=%s, interval=%.2fs",
        args.dry_run,
        run_once,
        poll_interval,
    )
    logger.info("Watching for files in: %s", DATA_IN_DIR)

    exit_code = 0
    try:
        while True:
            csv_files = sorted(DATA_IN_DIR.glob("*.csv"))
            if not csv_files:
                if run_once:
                    logger.info("No files to process; exiting (--once/--dry-run).")
                    break
                time.sleep(poll_interval)
                continue

            for csv_path in csv_files:
                file_result = process_file(csv_path, dry_run=args.dry_run)
                if file_result:
                    exit_code = file_result
                    break

            if exit_code:
                logger.error("Detected ingest errors; exiting with code %s", exit_code)
                break

            if args.dry_run:
                logger.info("Dry-run complete; exiting without modifying files.")
                break

            if run_once:
                logger.info("Processed current queue; exiting (--once).")
                break

            logger.info("All files processed. Waiting for new files...")
            time.sleep(poll_interval)
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        _release_lock()

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
