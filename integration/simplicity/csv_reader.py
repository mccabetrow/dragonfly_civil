from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterator

import pandas as pd


def read_csv(path: str) -> Iterator[Dict[str, str]]:
    """Yield rows from a CSV file as dict[str,str].

    Uses pandas.read_csv(dtype=str, keep_default_na=False) so empty cells are
    empty strings (not NaN). Raises FileNotFoundError if path missing.
    """
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"CSV not found: {p}")
    # keep_default_na=False keeps empty cells as empty strings
    df = pd.read_csv(p, dtype=str, keep_default_na=False)
    for record in df.to_dict(orient="records"):
        # ensure all values are strings (pandas may return numpy types)
        yield {k: (v if v is not None else "") for k, v in record.items()}
