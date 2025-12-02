import json
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from etl.src.importers.simplicity_plaintiffs import run_simplicity_import

header = (
    "LeadID,LeadSource,Court,IndexNumber,JudgmentDate,JudgmentAmount,"
    "County,State,PlaintiffName,PlaintiffAddress,Phone,Email,BestContactMethod"
)
judgment_number = f"DEBUG-{uuid.uuid4().hex[:8].upper()}"
csv_rows = [
    header,
    (
        f"{judgment_number},Import,Bronx Supreme Court,{judgment_number},04/01/2024,25000.00,"
        'Bronx,NY,Debug Run LLC,"789 Grand Concourse, Bronx, NY",(917)555-3300,'
        "debug.run@example.com,Phone"
    ),
]


def main() -> None:
    tmp_dir = Path("tmp")
    tmp_dir.mkdir(exist_ok=True)
    csv_path = tmp_dir / "debug_import.csv"
    csv_path.write_text("\n".join(csv_rows), encoding="utf-8")
    result = run_simplicity_import(
        str(csv_path),
        batch_name="tmp-debug",
        dry_run=False,
        source_reference="tmp-debug",
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
