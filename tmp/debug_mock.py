"""Debug script for testing mock behavior."""

from unittest.mock import MagicMock, patch

import pandas as pd

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

# Test mapping directly first
print("Testing _map_simplicity_row directly:")
row = df.iloc[0]
print(f"Row index: {row.index.tolist()}")
try:
    mapped = _map_simplicity_row(row)
    print(f"Mapped: {mapped}")
except Exception as e:
    print(f"Mapping failed: {e}")

print("\nTesting process_simplicity_frame:")
mock_conn = MagicMock()

# Add detailed logging
import logging

logging.basicConfig(level=logging.DEBUG)

with patch("backend.workers.ingest_processor._log_invalid_row") as mock_log:
    try:
        result = process_simplicity_frame(df, mock_conn, batch_id="test")
        print(f"Result: {result}")
        print(f"cursor called: {mock_conn.cursor.called}")
        print(f"commit called: {mock_conn.commit.called}")
        print(f"_log_invalid_row called: {mock_log.called}")
        if mock_log.called:
            print(f"_log_invalid_row args: {mock_log.call_args}")
    except Exception as e:
        print(f"Exception: {e}")
        import traceback

        traceback.print_exc()
