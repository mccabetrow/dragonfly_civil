import base64
import json
import os
from pathlib import Path

try:
    from dotenv import load_dotenv  # type: ignore

    load_dotenv()
except Exception:  # pragma: no cover
    pass

ref = os.getenv("SUPABASE_PROJECT_REF", "").strip()
key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()


def decode_jwt(token: str) -> tuple[dict, dict]:
    try:
        header_b64, payload_b64, _ = token.split(".")
    except ValueError:
        return {}, {}

    def _decode(segment: str) -> dict:
        padded = segment + "=" * (-len(segment) % 4)
        try:
            raw = base64.urlsafe_b64decode(padded.encode("utf-8"))
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {}

    return _decode(header_b64), _decode(payload_b64)


header, payload = decode_jwt(key)
print(f"REF: {ref}")
print(f"KEY_LEN: {len(key)}")
print(f"JWT hdr: {header}")
print(f"JWT pay: {payload}")
if Path(".env").exists():
    print(f".env present at {Path('.env').resolve()}")

if not ref or not key:
    raise SystemExit("Missing REF or SERVICE KEY")

iss = str(payload.get("iss", ""))
payload_ref = str(payload.get("ref", ""))
if ref not in iss and payload_ref != ref:
    raise SystemExit(
        f"Issue: service key 'iss' does not contain project ref '{ref}'. Copy fresh keys for this project."
    )

print("validate_key: OK", flush=True)
