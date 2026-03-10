#!/usr/bin/env python3
import json
import sys
from pathlib import Path

def emit(parse_status, schema_status, semantic_status, errors, warnings=None):
    return {
        "parse_status": parse_status,
        "schema_status": schema_status,
        "semantic_status": semantic_status,
        "errors": errors,
        "warnings": warnings or []
    }

def fail(parse_status, schema_status, semantic_status, errors):
    print(json.dumps(emit(parse_status, schema_status, semantic_status, errors), indent=2))
    sys.exit(1)

def main():
    if len(sys.argv) != 4:
        print("usage: ri_validate_json.py <artifact.json> <schema.json> <artifact_type>", file=sys.stderr)
        sys.exit(2)

    artifact_path = Path(sys.argv[1])
    schema_path = Path(sys.argv[2])
    expected_type = sys.argv[3]

    try:
        artifact = json.loads(artifact_path.read_text())
    except Exception as e:
        fail("fail_parse", "fail_schema", "fail_semantic", [f"parse error: {e}"])

    try:
        schema = json.loads(schema_path.read_text())
    except Exception as e:
        fail("pass", "fail_schema", "fail_semantic", [f"schema load error: {e}"])

    required = schema.get("required", [])
    missing = [k for k in required if k not in artifact]
    if missing:
        fail("pass", "fail_schema", "fail_semantic", [f"missing required fields: {missing}"])

    if artifact.get("artifact_type") != expected_type:
        fail("pass", "fail_schema", "fail_semantic", [f"artifact_type must be {expected_type}"])

    if expected_type in ("creator_discovery_signal", "competitor_discovery_signal", "workflow_candidate", "competitor_analysis"):
        evidence = artifact.get("evidence", [])
        if not isinstance(evidence, list) or len(evidence) == 0:
            fail("pass", "pass", "fail_semantic", ["evidence must be a non-empty list"])

    if expected_type == "workflow_candidate":
        if not artifact.get("source_artifact_id"):
            fail("pass", "pass", "fail_semantic", ["source_artifact_id required"])
        if not isinstance(artifact.get("steps", []), list) or len(artifact.get("steps", [])) == 0:
            fail("pass", "pass", "fail_semantic", ["steps must be a non-empty list"])

    elif expected_type == "competitor_analysis":
        if not artifact.get("source_artifact_id"):
            fail("pass", "pass", "fail_semantic", ["source_artifact_id required"])
        if not isinstance(artifact.get("feature_map", []), list) or len(artifact.get("feature_map", [])) == 0:
            fail("pass", "pass", "fail_semantic", ["feature_map must be a non-empty list"])

    elif expected_type == "ranked_opportunity":
        source_ids = artifact.get("source_artifact_ids", [])
        if not isinstance(source_ids, list) or len(source_ids) == 0:
            fail("pass", "pass", "fail_semantic", ["source_artifact_ids must be a non-empty list"])
        for field in ("severity_score", "frequency_score", "strategic_fit_score", "revenue_potential_score", "overall_score"):
            if not isinstance(artifact.get(field), (int, float)):
                fail("pass", "pass", "fail_semantic", [f"{field} must be numeric"])

    elif expected_type == "feature_spec":
        if not artifact.get("source_artifact_id"):
            fail("pass", "pass", "fail_semantic", ["source_artifact_id required"])
        if not isinstance(artifact.get("acceptance_criteria", []), list) or len(artifact.get("acceptance_criteria", [])) == 0:
            fail("pass", "pass", "fail_semantic", ["acceptance_criteria must be a non-empty list"])

    print(json.dumps(emit("pass", "pass", "pass", []), indent=2))

if __name__ == "__main__":
    main()
