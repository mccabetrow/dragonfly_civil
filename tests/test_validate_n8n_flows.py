from pathlib import Path

from tools import validate_n8n_flows


def test_detects_missing_rpc(tmp_path):
    flow_fixture = Path("tests/data/flows")
    references = validate_n8n_flows.collect_flow_references(flow_fixture)
    assert references, "Expected references to be collected from fixture"

    relations = {"demo_table"}
    rpcs = {"queue_job"}

    findings = validate_n8n_flows.evaluate_references(references, relations, rpcs)
    missing = [ref for ref, exists in findings if not exists]

    assert any(ref.name == "missing_rpc" for ref in missing)
    assert any(ref.normalized_name == "demo_table" and exists for ref, exists in findings)


def test_public_schema_relations_normalize_to_table_name():
    flow_fixture = Path("tests/data/flows")
    references = validate_n8n_flows.collect_flow_references(flow_fixture)
    relations = {"demo_table"}
    rpcs = set()

    findings = validate_n8n_flows.evaluate_references(references, relations, rpcs)

    assert any(ref.name == "public.demo_table" and exists for ref, exists in findings), (
        "Expected public.demo_table reference to resolve via normalization"
    )
