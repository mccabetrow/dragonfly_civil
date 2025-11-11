import os
import sys

from src.config.api_surface import REF
from src.db.supabase_client import COMMON, postgrest


def _mask_headers(headers: dict[str, str]) -> dict[str, str]:
    masked = {}
    for key, value in headers.items():
        if key.lower() in {"authorization", "apikey"} and value:
            masked[key] = value[:6] + "..."
        else:
            masked[key] = value
    return masked


def _print_failure(path: str, params: dict[str, str], headers: dict[str, str], response) -> None:
    request_headers = headers or {}
    merged = {**COMMON, **request_headers}
    masked_headers = _mask_headers({k: str(v) for k, v in merged.items()})
    print("doctor: request failed")
    if response is not None and response.request is not None:
        print(f"  URL: {response.request.url}")
    else:
        print(f"  URL: {path}")
    print("  Headers:")
    for key, value in masked_headers.items():
        print(f"    {key}: {value}")
    if params:
        print(f"  Params: {params}")
    if response is not None:
        print(f"  Status: {response.status_code}")
        print(f"  Body: {response.text[:500]}")


def main() -> int:
    with postgrest(timeout=20) as client:
        path = "/v_cases"
        params = {"select": "case_id", "limit": 1}
        response = client.get(path, params=params)
        if response.status_code == 401:
            raise SystemExit(
                "401 Invalid API key. Re-copy the SERVICE ROLE key for project "
                f"{REF} and run scripts\\load_env.ps1 again."
            )
        try:
            response.raise_for_status()
        except Exception:
            _print_failure(path, params, {}, response)
            raise
        print("doctor: v_cases reachable")

        payload = {
            "payload": {
                "index_no": "TEST-" + os.urandom(3).hex(),
                "court": "NYC Civil",
                "county": "Kings",
                "principal_amt": 123,
                "status": "new",
                "source": "doctor",
            }
        }
        insert_response = client.post("/rpc/insert_case", json=payload)
        try:
            insert_response.raise_for_status()
        except Exception:
            _print_failure("/rpc/insert_case", {}, {}, insert_response)
            raise
        print("doctor: insert_case RPC succeeded")

        content_type = insert_response.headers.get("content-type", "")
        case_id = insert_response.json() if content_type.startswith("application/json") else None
        if isinstance(case_id, list):
            case_id = case_id[0]

        if case_id:
            enrichment_headers = {
                **COMMON,
                "Content-Profile": "enrichment",
                "Accept-Profile": "enrichment",
            }
            body = [
                {
                    "case_id": case_id,
                    "identity_score": 80,
                    "contactability_score": 70,
                    "asset_score": 60,
                    "recency_amount_score": 50,
                    "adverse_penalty": 0,
                }
            ]
            collectability_response = client.post(
                "/enrichment.collectability",
                params={"on_conflict": "case_id"},
                headers=enrichment_headers,
                json=body,
            )
            try:
                collectability_response.raise_for_status()
            except Exception:
                _print_failure(
                    "/enrichment.collectability",
                    {"on_conflict": "case_id"},
                    enrichment_headers,
                    collectability_response,
                )
                raise
            print(
                "POST enrichment.collectability:",
                collectability_response.status_code,
                collectability_response.text[:200],
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
