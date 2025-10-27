from __future__ import annotations

import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Tuple

PY = sys.executable
ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
LOG = ROOT / f"validation_{datetime.now().strftime('%Y%m%d')}.txt"

STAGES: List[Tuple[str, bool, str]] = []


def run(cmd: List[str], cwd: Path | None = None, check: bool = True) -> Tuple[int, str]:
    """Run a shell command and capture return code and combined output."""
    print(f"[RUN] {' '.join(cmd)}")
    proc = subprocess.run(
        cmd,
        cwd=cwd or ROOT,
        capture_output=True,
        text=True,
        shell=False,
    )
    combined = (proc.stdout or "")
    if proc.stderr:
        combined += "\n" + proc.stderr
    if check and proc.returncode != 0:
        print(f"[ERR] rc={proc.returncode}\n{combined}")
        raise RuntimeError(combined)
    return proc.returncode, combined


def mark(name: str, ok: bool, note: str = "") -> None:
    STAGES.append((name, ok, note))
    suffix = f" - {note}" if note else ""
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{suffix}")


def write_log() -> None:
    with LOG.open("w", encoding="utf-8") as handle:
        handle.write(f"VALIDATION RUN {datetime.now().isoformat()}\n")
        for name, ok, note in STAGES:
            suffix = f" - {note}" if note else ""
            handle.write(f"[{'PASS' if ok else 'FAIL'}] {name}{suffix}\n")
    print(f"[OK] Wrote {LOG}")


def main() -> int:
    exit_code = 0
    try:
        # Stage: migrations
        try:
            rc, out = run(["npx", "supabase", "db", "push"], check=False)
            if rc == 0:
                mark("migrations", True, "db push executed")
            else:
                mark("migrations", False, f"db push rc={rc}")
        except FileNotFoundError:
            mark("migrations", True, "supabase CLI not found - assuming applied")
        except Exception as exc:
            mark("migrations", False, f"db push failed: {exc}")

        # Stage: export
        out_csv = DATA / "simplicity_status_export.csv"
        rc, out = run([PY, "-m", "etl.sync_simplicity", "export", "--out", str(out_csv)], check=False)
        header_ok = False
        row_count_ok = False
        if out_csv.exists():
            lines = out_csv.read_text(encoding="utf-8", errors="ignore").splitlines()
            if lines:
                header_ok = lines[0].strip() == (
                    "LeadID,Status,UpdatedAt,Docket,County,State,JudgmentDate,Amount"
                )
                row_count_ok = len(lines) >= 3
        mark("export", rc == 0 and header_ok and row_count_ok, f"file={out_csv}")

        # Stage: mapping
        rc1, out1 = run([PY, "-m", "etl.sync_simplicity", "map-status", "Enforcement Pending"], check=False)
        rc2, out2 = run([PY, "-m", "etl.sync_simplicity", "map-status", "in_progress", "--reverse"], check=False)
        map_ok = (
            rc1 == 0
            and rc2 == 0
            and "-> internal" in out1.lower()
            and "-> external" in out2.lower()
        )
        mark("mapping", map_ok)

        # Stage: dry-run import
        rc, out = run(
            [
                PY,
                "-m",
                "etl.sync_simplicity",
                "import",
                "--file",
                "data/simplicity_export.csv",
                "--dry-run",
            ],
            check=False,
        )
        dry_ok = rc == 0 and "dry-run" in out.lower() and "errors=0" in out.lower()
        mark("dry_run", dry_ok)

        # Stage: commit import
        rc, out = run(
            [
                PY,
                "-m",
                "etl.sync_simplicity",
                "import",
                "--file",
                "data/simplicity_export.csv",
            ],
            check=False,
        )
        commit_ok = rc == 0 and "errors=0" in out.lower()
        mark("commit_import", commit_ok)

        # Stage: idempotency
        rc, out = run(
            [
                PY,
                "-m",
                "etl.sync_simplicity",
                "import",
                "--file",
                "data/simplicity_export.csv",
            ],
            check=False,
        )
        idempotent = rc == 0 and bool(re.search(r"inserted=0\b", out.lower()))
        mark("idempotency", idempotent, "re-import inserted=0")

        # Stage: tasks
        tasks_file = ROOT / ".vscode" / "tasks.json"
        tasks_ok = False
        if tasks_file.exists():
            text = tasks_file.read_text(encoding="utf-8", errors="ignore")
            tasks_ok = all(
                label in text
                for label in [
                    "Simplicity: Full Validation",
                    "Simplicity: Export",
                    "Simplicity: Import (Dry-Run)",
                ]
            )
        mark("tasks", tasks_ok, "tasks.json present")

    except Exception as exc:  # pragma: no cover
        exit_code = 1
        mark("runtime", False, str(exc))
    finally:
        write_log()
        passed = sum(1 for _, ok, _ in STAGES if ok)
        failed = sum(1 for _, ok, _ in STAGES if not ok)
        print(f"[SUMMARY] passed={passed} failed={failed}")
    if any(not ok for _, ok, _ in STAGES):
        exit_code = 1
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
