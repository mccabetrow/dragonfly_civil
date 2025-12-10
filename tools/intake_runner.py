from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, ContextManager, Dict, Iterable, Mapping, Sequence

import click
import psycopg
from psycopg.types.json import Jsonb

from etl.src.importers.jbi_900 import run_jbi_900_import
from etl.src.importers.simplicity_plaintiffs import run_simplicity_import
from src.supabase_client import get_supabase_db_url, get_supabase_env

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SourceSpec:
    name: str
    importer: Callable[[str, str, bool], dict[str, object]]
    default_subdir: str
    file_glob: str
    env_var: str
    description: str

    def resolve_path(self, override: str | None = None) -> Path:
        candidate = override or os.getenv(self.env_var)
        if not candidate:
            candidate = str(Path("data_in") / self.default_subdir)
        return Path(candidate).expanduser()


SOURCE_SPECS: Dict[str, SourceSpec] = {
    "simplicity": SourceSpec(
        name="simplicity",
        importer=run_simplicity_import,
        default_subdir="simplicity",
        file_glob="*.csv",
        env_var="INTAKE_SIMPLICITY_PATH",
        description="Simplicity plaintiff exports",
    ),
    "jbi_900": SourceSpec(
        name="jbi_900",
        importer=run_jbi_900_import,
        default_subdir="jbi_900",
        file_glob="*.csv",
        env_var="INTAKE_JBI900_PATH",
        description="JBI 900 intake exports",
    ),
}

BATCH_SAFE_RE = re.compile(r"[^a-zA-Z0-9]+")
DEFAULT_INTERVAL_SECONDS = 300


class DatabaseIntakeRepository:
    def __init__(self, env: str) -> None:
        self.env = env
        db_url = get_supabase_db_url(env)
        self.conn = psycopg.connect(db_url, autocommit=False, connect_timeout=10)

    def __enter__(self) -> DatabaseIntakeRepository:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001 - context protocol
        try:
            if exc:
                self.conn.rollback()
        finally:
            self.conn.close()

    def fetch_seen_files(self, source: str) -> set[str]:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                select file_name
                from public.intake_files
                where source = %s
                """,
                (source,),
            )
            return {row[0] for row in cur.fetchall()}

    def record_result(
        self,
        *,
        source: str,
        file_name: str,
        batch_name: str,
        status: str,
        import_run_id: str | None,
        metadata: Mapping[str, object] | None,
        error_message: str | None,
    ) -> None:
        payload = Jsonb(dict(metadata or {}))
        with self.conn.cursor() as cur:
            cur.execute(
                """
                insert into public.intake_files (
                    source, file_name, batch_name, status, processed_at, import_run_id, metadata, error_message
                ) values (
                    %s, %s, %s, %s, timezone('utc', now()), %s, %s, %s
                )
                on conflict (source, file_name) do update
                set batch_name = excluded.batch_name,
                    status = excluded.status,
                    processed_at = excluded.processed_at,
                    import_run_id = excluded.import_run_id,
                    metadata = excluded.metadata,
                    error_message = excluded.error_message,
                    updated_at = timezone('utc', now())
                """,
                (
                    source,
                    file_name,
                    batch_name,
                    status,
                    import_run_id,
                    payload,
                    error_message,
                ),
            )
        self.conn.commit()


class IntakeRunner:
    def __init__(
        self,
        *,
        target_env: str,
        sources: Sequence[SourceSpec],
        dry_run: bool,
        once: bool,
        interval_seconds: int,
        path_overrides: Mapping[str, str] | None = None,
        repo_factory: Callable[[str], ContextManager[DatabaseIntakeRepository]] | None = None,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        self.env = target_env
        self.sources = list(sources)
        self.dry_run = dry_run
        self.once = once
        self.interval_seconds = max(5, interval_seconds)
        self.path_overrides = dict(path_overrides or {})
        self.repo_factory = repo_factory or (lambda env: DatabaseIntakeRepository(env))
        self.now_fn = now_fn or (lambda: datetime.now(timezone.utc))

    def run(self) -> None:
        while True:
            processed = self.process_once()
            if self.once:
                break
            if processed == 0:
                logger.debug(
                    "No new intake files discovered; sleeping %ss",
                    self.interval_seconds,
                )
            time.sleep(self.interval_seconds)

    def process_once(self) -> int:
        processed = 0
        with self.repo_factory(self.env) as repo:
            for spec in self.sources:
                processed += self._process_source(repo, spec)
        return processed

    def _process_source(self, repo: DatabaseIntakeRepository, spec: SourceSpec) -> int:
        directory = spec.resolve_path(self.path_overrides.get(spec.name))
        directory.mkdir(parents=True, exist_ok=True)
        files = sorted(p for p in directory.glob(spec.file_glob) if p.is_file())
        if not files:
            logger.debug("[%s] No files under %s", spec.name, directory)
            return 0

        seen_files = repo.fetch_seen_files(spec.name)
        processed = 0
        for file_path in files:
            if file_path.name in seen_files:
                continue
            self._handle_file(repo, spec, file_path)
            processed += 1
        return processed

    def _handle_file(
        self,
        repo: DatabaseIntakeRepository,
        spec: SourceSpec,
        file_path: Path,
    ) -> None:
        batch_name = derive_batch_name(spec.name, file_path.name, now=self.now_fn())
        logger.info("[%s] Processing %s as batch %s", spec.name, file_path, batch_name)
        if self.dry_run:
            spec.importer(str(file_path), batch_name, True)
            logger.info("[%s] Dry-run complete for %s", spec.name, file_path.name)
            return

        metadata: Dict[str, object] = {
            "runner": {
                "source": spec.name,
                "file_name": file_path.name,
                "batch_name": batch_name,
            }
        }
        import_run_id: str | None = None
        status = "completed"
        error_message: str | None = None
        try:
            result = spec.importer(str(file_path), batch_name, False)
            import_run_value = result.get("import_run_id") if isinstance(result, dict) else None
            import_run_id = str(import_run_value) if isinstance(import_run_value, str) else None
            summary = None
            counts: Dict[str, object | None] = {
                "row_count": None,
                "insert_count": None,
                "error_count": None,
            }
            if isinstance(result, Mapping):
                metadata_value = result.get("metadata")
                if isinstance(metadata_value, Mapping):
                    summary = metadata_value.get("summary")
                counts["row_count"] = result.get("row_count")
                counts["insert_count"] = result.get("insert_count")
                counts["error_count"] = result.get("error_count")
            metadata["import_summary"] = summary
            metadata["counts"] = counts
        except Exception as exc:  # noqa: BLE001
            status = "failed"
            error_message = str(exc)
            metadata["error"] = error_message
            logger.exception("[%s] Intake failed for %s", spec.name, file_path.name)
        finally:
            repo.record_result(
                source=spec.name,
                file_name=file_path.name,
                batch_name=batch_name,
                status=status,
                import_run_id=import_run_id,
                metadata=metadata,
                error_message=error_message,
            )


def derive_batch_name(source: str, file_name: str, *, now: datetime | None = None) -> str:
    timestamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%d%H%M")
    stem = BATCH_SAFE_RE.sub("-", Path(file_name).stem).strip("-") or "intake"
    batch = f"{timestamp}-{source}-{stem}"[:80]
    return batch


def _parse_path_overrides(values: Sequence[str]) -> Dict[str, str]:
    overrides: Dict[str, str] = {}
    for item in values:
        if "=" not in item:
            raise click.BadParameter(
                "Path overrides must be in the form source=PATH (e.g. simplicity=C:/drop)"
            )
        name, path_value = item.split("=", 1)
        name = name.strip().lower()
        if name not in SOURCE_SPECS:
            raise click.BadParameter(f"Unknown source '{name}' in --path override")
        overrides[name] = path_value.strip()
    return overrides


@click.group()
def cli() -> None:
    """Automation helpers for intake pipelines."""


@cli.command("run")
@click.option(
    "--source",
    "sources",
    type=click.Choice(sorted(SOURCE_SPECS.keys())),
    multiple=True,
    help="Restrict to one or more sources. Defaults to all.",
)
@click.option(
    "--env",
    "requested_env",
    type=click.Choice(["dev", "prod"]),
    default=None,
    help="Supabase environment to target (defaults to SUPABASE_MODE).",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Parse files without writing status or running imports with --commit.",
)
@click.option(
    "--once/--watch",
    "once",
    default=False,
    help="Process available files once (default watches continuously).",
)
@click.option(
    "--interval",
    "interval_seconds",
    type=int,
    default=DEFAULT_INTERVAL_SECONDS,
    show_default=True,
    help="Seconds to sleep between scans when watching.",
)
@click.option(
    "--path",
    "path_overrides",
    multiple=True,
    help="Override source directories (format: source=PATH).",
)
def run_command(
    sources: Sequence[str],
    requested_env: str | None,
    dry_run: bool,
    once: bool,
    interval_seconds: int,
    path_overrides: Sequence[str],
) -> None:
    env = requested_env or get_supabase_env()
    selected = [SOURCE_SPECS[name] for name in (sources or SOURCE_SPECS.keys())]
    overrides = _parse_path_overrides(path_overrides)
    runner = IntakeRunner(
        target_env=env,
        sources=selected,
        dry_run=dry_run,
        once=once,
        interval_seconds=interval_seconds,
        path_overrides=overrides,
    )
    runner.run()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s %(message)s")
    cli(obj={})


if __name__ == "__main__":
    main()
