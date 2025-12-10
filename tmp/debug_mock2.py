"""Debug script for testing mock behavior."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import logging first
import logging
from unittest.mock import MagicMock, patch

import pandas as pd

logging.basicConfig(level=logging.DEBUG, format="%(name)s - %(levelname)s - %(message)s")

from backend.workers.ingest_processor import _map_simplicity_row, process_simplicity_frame

# Create a simple valid DataFrame
df = pd.DataFrame(
    [
        {
            "Case Number": "12345",
            "Plaintiff": "A",
            "Defendant": "B",
            "Judgment Amount": "1000",
            "Filing Date": "01/01/2024",
            "County": "NY",
        }
    ]
)

print("Testing _map_simplicity_row directly:")
row = df.iloc[0]
try:
    mapped = _map_simplicity_row(row)
    print(f"Mapped: {mapped}")
except Exception as e:
    print(f"Mapping failed: {e}")

print("\nTesting manual mock flow:")
mock_conn = MagicMock()
cm = mock_conn.cursor()
print(f"cursor() type: {type(cm)}")
with cm as cur:
    print(f"cur type: {type(cur)}")
    cur.execute("SQL", {})
    print(f"execute called on cur: {cur.execute.called}")
mock_conn.commit()
print(f"commit called: {mock_conn.commit.called}")

print("\nTesting process_simplicity_frame:")
mock_conn2 = MagicMock()

with patch("backend.workers.ingest_processor._log_invalid_row") as mock_log:
    result = process_simplicity_frame(df, mock_conn2, batch_id="test")
    print(f"Result: {result}")
    print(f"cursor called: {mock_conn2.cursor.called}")
    print(f"cursor call count: {mock_conn2.cursor.call_count}")
    print(f"commit called: {mock_conn2.commit.called}")
    print(f"_log_invalid_row called: {mock_log.called}")
