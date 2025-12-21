"""Upload test CSV to Supabase Storage."""

import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Set up environment
os.environ.setdefault("SUPABASE_MODE", "dev")

from src.supabase_client import create_supabase_client

client = create_supabase_client()

# Upload the test file
local_path = Path("data_in/simplicity_sample.csv")
storage_path = "data_in/simplicity_sample.csv"

print(f"Uploading {local_path} to storage...")

try:
    with open(local_path, "rb") as f:
        content = f.read()

    # Upload to intake bucket
    result = client.storage.from_("intake").upload(
        storage_path, content, file_options={"content-type": "text/csv", "upsert": "true"}
    )
    print(f"✅ Uploaded to intake/{storage_path}")
    print(f"   Result: {result}")
except Exception as e:
    print(f"❌ Upload failed: {e}")
    # Try to list buckets to see what's available
    try:
        buckets = client.storage.list_buckets()
        print(f"   Available buckets: {[b.name for b in buckets]}")
    except Exception as e2:
        print(f"   Could not list buckets: {e2}")
