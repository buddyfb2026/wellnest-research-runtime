"""Offline, shadow-only WEL-53 recipe eligibility evaluation.

This module produces review artifacts only.  It has no store, publication,
worker, fetch, model, or scheduler integration.
"""
import argparse
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from . import recipe_schema, recipes
from .config import REPO_ROOT
from .extract import scan_for_instructions

POLICY_VERSION = "wel53_recipe_eligibility_v1"
EVALUATOR_VERSION = "wel53_shadow_v1"
CORPUS_VERSION = 1
EVAL_DIR = REPO_ROOT / "eval" / "wel53"
DEV_CASES = EVAL_DIR / "dev_cases.json"
HOLDOUT_CASES = EVAL_DIR / "holdout_cases.json"
POLICY = EVAL_DIR / "policy-v1.md"
DEPENDENCIES = (
    "research/extract.py",
    "research/recipe_schema.py",
    "research/recipes.py",
)
FROZEN_FILES = (
    "research/shadow_eligibility.py",
    "eval/wel53/policy-v1.md",
    "eval/wel53/dev_cases.json",
    "eval/wel53/holdout_cases.json",
    "eval/wel48/fixtures/operating-recipe-literals.json",
) + DEPENDENCIES
DISPOSITIONS = ("shadow_eligible", "shadow_hold")
REASONS = {
    "schema_invalid", "content_not_usable", "not_complete", "unknown_fields_present",
    "required_scalar_unknown", "required_literal_unbound", "has_conflicts",
    "support_not_in_evidence", "unsupported_claim", "source_embedded_instructions_flagged",
    "fingerprint_drift", "not_current_observation", "registry_effective_denied",
    "surface_source_mismatch", "missing_rights_basis", "invalid_approval",
}
SCALAR_PATHS = (
    ("servings",),
    ("times", "prep_time"),
    ("times", "cook_time"),
    ("times", "total_time"),
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _atomic_write(path: Path, data: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    except BaseException:
        try:
            os.unlink(name)
        except FileNotFoundError:
            pass
        raise


def _load(path: Path) -> Any:
    return json.loads(Path(path).read_text())


def _human(value: Any) -> bool:
    return isinstance(value, str) and value.startswith("human:") and bool(value[6:].strip())


def _dependency_hash() -> str:
    values = {rel: sha256_file(REPO_ROOT / rel) for rel in DEPENDENCIES}
    return _sha(recipes.canonical_json(values))


def load_cases(split: Optional[str] = None) -> List[Dict[str, Any]]:
    dev = _load(DEV_CASES)
    holdout = _load(HOLDOUT_CASES)
    if dev.get("corpus_version") != CORPUS_VERSION or holdout.get("corpus_version") != CORPUS_VERSION:
        raise ValueError("corpus_version_mismatch")
    rows = list(dev.get("cases", []))
    if split != "dev":
        rows += list(holdout.get("cases", []))
    return rows


def _evidence(case: Dict[str, Any]) -> str:
    if isinstance(case.get("evidence_text"), str):
        return case["evidence_text"]
    ref = case.get("evidence_ref")
    if not isinstance(ref, dict):
        raise ValueError("missing_evidence")
    path = REPO_ROOT / str(ref.get("path", ""))
    if not path.is_file() or sha256_file(path) != ref.get("sha256"):
        raise ValueError("evidence_ref_drift")
    values = _load(path)
    try:
        value = values[ref["index"]]["text"]
    except (KeyError, IndexError, TypeError):
        raise ValueError("invalid_evidence_ref")
    if not isinstance(value, str):
        raise ValueError("invalid_evidence_ref")
    return value


def manifest() -> Dict[str, Any]:
    cases = load_cases()
    for case in cases:
        expected = case.get("expected", {})
        if not _human(case.get("reviewed_by")):
            raise ValueError("unreviewed_case:%s" % case.get("case_id"))
        if expected.get("disposition") not in DISPOSITIONS:
            raise ValueError("unknown_expected_disposition:%s" % case.get("case_id"))
        if not isinstance(expected.get("reasons"), list) or any(r not in REASONS for r in expected["reasons"]):
            raise ValueError("unknown_expected_reason:%s" % case.get("case_id"))
        _evidence(case)
    files = {rel: sha256_file(REPO_ROOT / rel) for rel in FROZEN_FILES}
    return {
        "policy_version": POLICY_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "corpus_version": CORPUS_VERSION,
        "files": files,
        "dependencies": sorted(DEPENDENCIES),
        "gate_dependency_hash": _dependency_hash(),
        "dev_case_count": 6,
        "holdout_case_count": 6,
        "budget": {"model_calls": 0, "network_requests": 0},
    }


def check_manifest(path: Path) -> List[str]:
    value = _load(path)
    drift = []
    for rel, digest in value.get("files", {}).items():
        target = REPO_ROOT / rel
        if not target.is_file() or sha256_file(target) != digest:
            drift.append(rel)
    return sorted(drift)


def _manifest_valid(value: Dict[str, Any]) -> bool:
    return (
        value.get("policy_version") == POLICY_VERSION
        and value.get("evaluator_version") == EVALUATOR_VERSION
        and value.get("corpus_version") == CORPUS_VERSION
        and sorted(value.get("dependencies", [])) == sorted(DEPENDENCIES)
        and value.get("gate_dependency_hash") == _dependency_hash()
        and set(value.get("dependencies", [])) <= set(value.get("files", {}))
        and set(value.get("files", {})) == set(FROZEN_FILES)
        and value.get("dev_case_count") == 6
        and value.get("holdout_case_count") == 6
        and value.get("budget") == {"model_calls": 0, "network_requests": 0}
    )


def _slot(document: Dict[str, Any], path: Tuple[str, ...]) -> Any:
    value: Any = document
    for key in path:
        if not isinstance(value, dict) or key not in value:
            return None
        value = value[key]
    return value


def _slot_path(path: Tuple[str, ...]) -> str:
    return ".".join(path)


def _required_slots(document: Dict[str, Any]) -> Iterable[Tuple[str, Any]]:
    yield "name", document.get("name")
    yield "servings", document.get("servings")
    times = document.get("times") if isinstance(document.get("times"), dict) else {}
    for name in ("prep_time", "cook_time", "total_time"):
        yield "times.%s" % name, times.get(name)
    ingredients = document.get("ingredients") if isinstance(document.get("ingredients"), list) else []
    steps = document.get("steps") if isinstance(document.get("steps"), list) else []
    for index, value in enumerate(ingredients):
        yield "ingredients[%d]" % index, value
    for index, value in enumerate(steps):
        yield "steps[%d]" % index, value


def _declared_unknown(slot: Any) -> bool:
    return isinstance(slot, dict) and slot.get("support") == "unknown"


def bound_literal(slot: Any, evidence_text: str) -> Optional[Tuple[str, int, int]]:
    if not isinstance(slot, dict):
        return None
    source = slot
    if slot.get("support") == "source_normalized" and slot.get("value") is not None:
        source = slot.get("source")
    elif slot.get("support") != "source_literal":
        return None
    if not isinstance(source, dict) or source.get("support") != "source_literal":
        return None
    literal, span = source.get("value"), source.get("span")
    if not isinstance(literal, str) or not literal.strip() or not isinstance(span, dict):
        return None
    start, end = span.get("start"), span.get("end")
    if type(start) is not int or type(end) is not int or not (0 <= start < end <= len(evidence_text)):
        return None
    return literal, start, end


def _container_shape(document: Any) -> bool:
    if not isinstance(document, dict):
        return False
    return (
        all(isinstance(document.get(key), dict) for key in ("name", "servings", "times", "evidence", "provenance"))
        and isinstance(document.get("ingredients"), list) and bool(document["ingredients"])
        and isinstance(document.get("steps"), list) and bool(document["steps"])
        and isinstance(document.get("unknown_fields"), list)
        and all(isinstance(x, dict) for x in document["unknown_fields"])
        and isinstance(document.get("conflicts"), list)
        and all(isinstance(x, dict) for x in document["conflicts"])
    )


def evaluate_case(case: Dict[str, Any], gate_dependency_hash: Optional[str] = None) -> Tuple[str, Dict[str, Any]]:
    document = case.get("document")
    evidence_text = _evidence(case)
    reasons: List[str] = []
    unsupported: List[str] = []
    unbound: List[str] = []
    computed = _sha(recipes.canonical_json(document))

    if not _container_shape(document) or recipe_schema.validate(document):
        reasons = ["schema_invalid"]
    else:
        if not recipe_schema.cooking_content_usable(document):
            reasons.append("content_not_usable")
        if document.get("completeness") != "complete":
            reasons.append("not_complete")
        if document.get("unknown_fields") != []:
            reasons.append("unknown_fields_present")
        if any(_declared_unknown(_slot(document, path)) for path in SCALAR_PATHS):
            reasons.append("required_scalar_unknown")
        for path, slot in _required_slots(document):
            if not _declared_unknown(slot) and bound_literal(slot, evidence_text) is None:
                unbound.append(path)
        if unbound:
            reasons.append("required_literal_unbound")
        if document.get("conflicts") != []:
            reasons.append("has_conflicts")
        observed = case.get("observed") if isinstance(case.get("observed"), dict) else {}
        supported = _sha(evidence_text) == observed.get("content_hash")
        for _path, slot in _required_slots(document):
            bound = bound_literal(slot, evidence_text)
            if bound is not None and evidence_text[bound[1]:bound[2]] != bound[0]:
                supported = False
        if not supported:
            reasons.append("support_not_in_evidence")
        allowed = set(recipe_schema.PORTABLE_SHAPE["required"]) | {"schema_version"}
        unsupported = sorted(set(document) - allowed)
        if unsupported:
            reasons.append("unsupported_claim")
        if scan_for_instructions(evidence_text):
            reasons.append("source_embedded_instructions_flagged")
        if computed != case.get("content_fingerprint"):
            reasons.append("fingerprint_drift")
        provenance = document.get("provenance", {})
        if (provenance.get("content_hash") != observed.get("content_hash")
                or provenance.get("manifest_hash") != observed.get("manifest_hash")):
            reasons.append("not_current_observation")
        surface = case.get("surface") if isinstance(case.get("surface"), dict) else {}
        if surface.get("roster_status") != "retain" or surface.get("access_status") != "permitted":
            reasons.append("registry_effective_denied")
        source_url, surface_url = document.get("evidence", {}).get("source_url"), surface.get("url")
        if (not isinstance(source_url, str) or not source_url or not isinstance(surface_url, str)
                or not surface_url or surface_url != source_url):
            reasons.append("surface_source_mismatch")
        review = surface.get("rights_review") if isinstance(surface.get("rights_review"), dict) else {}
        if not isinstance(review.get("basis"), str) or not review["basis"].strip() or not _human(review.get("reviewed_by")):
            reasons.append("missing_rights_basis")
        approval = case.get("approval")
        if approval is not None and (not isinstance(approval, dict) or not _human(approval.get("acted_by"))
                                     or approval.get("content_fingerprint") != case.get("content_fingerprint")):
            reasons.append("invalid_approval")

    reasons = sorted(set(reasons))
    if any(reason not in REASONS for reason in reasons):
        raise ValueError("unknown_reason")
    disposition = "shadow_eligible" if not reasons else "shadow_hold"
    dependency_hash = gate_dependency_hash or _dependency_hash()
    surface = case.get("surface")
    approval = case.get("approval") if "approval" in case else None
    context_hash = _sha(recipes.canonical_json({"surface": surface, "approval": approval}))
    provenance = document.get("provenance", {}) if isinstance(document, dict) else {}
    observed = case.get("observed", {})
    recipe_key = document.get("identity", {}).get("recipe_key", "") if isinstance(document, dict) else ""
    components = [
        POLICY_VERSION, EVALUATOR_VERSION, recipe_schema.SCHEMA_HASH, dependency_hash,
        recipe_key, computed, provenance.get("manifest_hash", ""), observed.get("content_hash", ""),
        observed.get("manifest_hash", ""), context_hash,
    ]
    decision_key = _sha("wel53|" + "|".join(components))
    row = {
        "policy_version": POLICY_VERSION, "evaluator_version": EVALUATOR_VERSION,
        "schema_hash": recipe_schema.SCHEMA_HASH, "gate_dependency_hash": dependency_hash,
        "recipe_key": recipe_key, "computed_fingerprint": computed,
        "document_manifest_hash": provenance.get("manifest_hash"),
        "observed_content_hash": observed.get("content_hash"),
        "observed_manifest_hash": observed.get("manifest_hash"), "context_hash": context_hash,
        "claimed_content_fingerprint": case.get("content_fingerprint"),
        "case_id": case.get("case_id"), "split": case.get("split"),
        "label_kind": case.get("label_kind"), "disposition": disposition,
        "reasons": reasons, "expected": case.get("expected"),
        "unsupported_claims": unsupported, "unbound_slots": sorted(unbound),
    }
    return decision_key, row


def run(split: str, manifest_value: Dict[str, Any]) -> Dict[str, Any]:
    rows: Dict[str, Any] = {}
    for case in load_cases(split):
        key, row = evaluate_case(case, manifest_value["gate_dependency_hash"])
        if key in rows:
            raise ValueError("duplicate_decision_key")
        rows[key] = row
    return {"manifest": {k: manifest_value[k] for k in ("policy_version", "evaluator_version", "corpus_version", "gate_dependency_hash")},
            "decisions": rows}


def _corrections(path: Path, rows: Dict[str, Any]) -> Dict[str, Any]:
    values = _load(path)
    if not isinstance(values, list):
        raise ValueError("malformed_corrections")
    mapped, orphans, revoked = {}, 0, 0
    for value in values:
        if (not isinstance(value, dict) or value.get("corrected_disposition") not in DISPOSITIONS
                or not _human(value.get("corrected_by")) or not isinstance(value.get("reason"), str)
                or not value["reason"].strip() or not isinstance(value.get("corrected_at"), str)
                or not value["corrected_at"].strip()):
            raise ValueError("malformed_corrections")
        key = value.get("decision_key")
        if key not in rows:
            orphans += 1
            continue
        mapped[key] = value
        if rows[key]["disposition"] == "shadow_eligible" and value["corrected_disposition"] == "shadow_hold":
            revoked += 1
    return {"corrections": mapped, "orphan_corrections": orphans, "revoked_eligible": revoked}


def render_markdown(value: Dict[str, Any], correction_report: Dict[str, Any]) -> str:
    rows = list(value["decisions"].values())
    lines = ["# WEL-53 shadow eligibility report", "",
             "Manifest gate dependency hash: `%s`." % value["manifest"]["gate_dependency_hash"], "",
             "Corrections: %d matched; revoked eligible: %d; orphan corrections: %d." % (
                 len(correction_report["corrections"]), correction_report["revoked_eligible"],
                 correction_report["orphan_corrections"]), ""]
    for split in ("dev", "holdout"):
        lines += ["## %s — fixture/saved-evidence reading; not evidence of live improvement" % split.title(), "",
                  "| case | kind | shadow | expected | reasons | correction |", "|---|---|---|---|---|---|"]
        for row in sorted((r for r in rows if r["split"] == split), key=lambda r: r["case_id"]):
            correction = correction_report["corrections"].get(next(k for k, v in value["decisions"].items() if v is row))
            lines.append("| %s | %s | %s | %s | %s | %s |" % (
                row["case_id"], row["label_kind"], row["disposition"], row["expected"]["disposition"],
                ", ".join(row["reasons"]) or "none",
                correction["corrected_disposition"] if correction else "none"))
        lines.append("")
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="research.shadow_eligibility")
    subs = parser.add_subparsers(dest="command", required=True)
    freeze = subs.add_parser("freeze"); freeze.add_argument("--out", required=True)
    for command in ("dev", "holdout"):
        sub = subs.add_parser(command); sub.add_argument("--manifest", required=True); sub.add_argument("--out", required=True)
        if command == "holdout":
            sub.add_argument("--corrections", required=True); sub.add_argument("--md", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "freeze":
            value = manifest()
            _atomic_write(Path(args.out), json.dumps(value, indent=2, sort_keys=True) + "\n")
            return 0
        manifest_value = _load(Path(args.manifest))
        drift = check_manifest(Path(args.manifest))
        if drift or not _manifest_valid(manifest_value):
            print("manifest drift or version skew; evaluation refused: %s" % ", ".join(drift), file=sys.stderr)
            return 2
        value = run(args.command, manifest_value)
        _atomic_write(Path(args.out), json.dumps(value, indent=2, sort_keys=True) + "\n")
        if args.command == "holdout":
            report = _corrections(Path(args.corrections), value["decisions"])
            _atomic_write(Path(args.md), render_markdown(value, report))
        return 0
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print("evaluation refused: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
