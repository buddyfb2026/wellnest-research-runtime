"""WEL-42 producer: export approved, publishable rule candidates as a versioned meal-detail payload.

This is the only path by which research content may reach the app. It is deliberately narrow:

  * Only RULE candidates are exportable. Free-text model prose is never publishable (see
    candidates.py) and is additionally rejected here, so no arbitrary model wording can reach a card.
  * A candidate must be `state='approved'` AND `state_set_by` a named human AND `publishable=1`.
    This module never sets any of those; it only reads them. Approval by itself is not enough.
  * The rule must still be registered in rules.py at the exact version recorded on the candidate.
    A rule that was edited or withdrawn stops exporting rather than exporting stale wording.
  * Applicability is an exact, reviewer-registered mapping from rule_id to one meal template name
    plus the ingredient tokens that template must contain. It is NOT keyword matching over recipe
    text: a rule with no entry in MEAL_APPLICABILITY cannot be attached to any meal.
  * Every displayed string is either fixed rule text or a whole sentence quoted from the evidence.

Household data never enters this module. It reads the research database only; nothing about a
household is an input, so nothing about a household can be written back.
"""
import hashlib
import json
import sqlite3
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from .rules import RULES, SupportRule, match_rules

MEAL_EXPORT_PAYLOAD_VERSION = 1
MEAL_EXPORT_CAPABILITY = "weekly_meal_plan"


@dataclass(frozen=True)
class MealApplicability:
    """Exact applicability. Both conditions must hold against the meal the app already selected.

    `template_name` must equal the meal's name exactly. `required_ingredients` must all appear
    exactly in that meal's ingredient list. Applicability can only ever *narrow* where a detail may
    attach; it can never cause a meal to be chosen, reordered, or substituted, and it is evaluated
    after household constraints have already picked the week's meals.
    """
    template_name: str
    required_ingredients: Tuple[str, ...]


# rule_id -> applicability. An entry is added only after the rule's support sentence has been read in
# real retrieved evidence and the guidance confirmed correct for that exact template.
MEAL_APPLICABILITY: Dict[str, MealApplicability] = {
    # CDC: "Rinse fresh fruits and vegetables under running water." The app's only template whose
    # ingredient list is explicit fresh produce is the sheet-pan dish; broccoli and carrots must both
    # be present, so the guidance cannot drift onto a meal it was not reviewed against.
    "rinse_fresh_produce_under_running_water": MealApplicability(
        template_name="Sheet-pan chicken and vegetables",
        required_ingredients=("broccoli", "carrots"),
    ),
}


def _rule_index(rules: Tuple[SupportRule, ...]) -> Dict[Tuple[str, int], SupportRule]:
    return {(r.rule_id, r.version): r for r in rules}


def _reject(reasons: List[str], detail: str) -> None:
    reasons.append(detail)


def build_meal_detail(
    row: sqlite3.Row,
    applicability: Dict[str, MealApplicability],
    rule_index: Dict[Tuple[str, int], SupportRule],
    allow_fixture_evidence: bool = False,
) -> Tuple[Optional[Dict[str, Any]], List[str]]:
    """Return (detail, rejection_reasons). A detail is returned only when every gate passes."""
    reasons: List[str] = []

    state = row["state"]
    set_by = row["state_set_by"] or ""
    if state != "approved":
        _reject(reasons, "state_not_approved: %s" % state)
    if not set_by.startswith("human:"):
        _reject(reasons, "not_human_approved: state_set_by=%r" % set_by)
    if int(row["publishable"] or 0) != 1:
        _reject(reasons, "not_publishable")

    raw_validation = row["validation"]
    if not raw_validation:
        _reject(reasons, "unvalidated_legacy_candidate: no validation record")
        return None, reasons
    try:
        validation = json.loads(raw_validation)
    except (ValueError, TypeError):
        _reject(reasons, "malformed_validation: not JSON")
        return None, reasons
    if not isinstance(validation, dict):
        _reject(reasons, "malformed_validation: not an object")
        return None, reasons

    if validation.get("kind") != "rule":
        _reject(reasons, "not_a_rule_candidate: kind=%r" % validation.get("kind"))
        return None, reasons
    if validation.get("model_inference"):
        _reject(reasons, "model_inference_not_exportable")

    rule_id = validation.get("rule_id")
    rule_version = validation.get("rule_version")
    if not isinstance(rule_id, str) or not isinstance(rule_version, int) or isinstance(rule_version, bool):
        _reject(reasons, "malformed_validation: rule identity missing or wrong type")
        return None, reasons

    rule = rule_index.get((rule_id, rule_version))
    if rule is None:
        _reject(reasons, "rule_not_registered_at_version: %s@%s" % (rule_id, rule_version))

    applies = applicability.get(rule_id)
    if applies is None:
        _reject(reasons, "no_registered_meal_applicability: %s" % rule_id)

    # The recorded support quote is not trusted. Re-derive it from the stored evidence text: the
    # registered rule's sentence must still occur, as a whole sentence, in evidence whose text still
    # hashes to the recorded content hash. A quote copied from a different article, or invented
    # outright, cannot survive this even if the candidate row says 'approved'.
    support_quote = validation.get("support_quote")
    if not isinstance(support_quote, str) or not support_quote.strip():
        _reject(reasons, "missing_support_quote")

    evidence_text = row["evidence_text"]
    if evidence_text is None:
        _reject(reasons, "missing_evidence_text: cannot verify support against the source")
    elif not (row["content_hash"] or "").strip():
        pass  # already reported as a missing evidence field below
    else:
        actual_hash = hashlib.sha256(evidence_text.encode("utf-8")).hexdigest()
        if actual_hash != row["content_hash"]:
            _reject(reasons, "evidence_text_hash_mismatch: stored text does not match content_hash")
        elif rule is not None:
            matches = match_rules(evidence_text, (rule,))
            if not matches:
                _reject(reasons, "support_not_present_in_evidence: %s has no support sentence in "
                                 "evidence %s" % (rule.rule_id, row["evidence_id"]))
            elif matches[0].support_quote != support_quote:
                _reject(reasons, "support_quote_does_not_match_evidence")

    # Fixture evidence is test scaffolding. It must never reach a household through the normal path.
    if (row["content_kind"] or "") != "live" and not allow_fixture_evidence:
        _reject(reasons, "non_live_evidence: content_kind=%r is not publishable" % row["content_kind"])

    for column in ("content_hash", "source_url", "attribution", "fetched_at"):
        if not (row[column] or "").strip():
            _reject(reasons, "missing_evidence_field: %s" % column)

    injection_flags = row["injection_flags"] or "[]"
    try:
        if json.loads(injection_flags):
            _reject(reasons, "source_embedded_instructions_flagged")
    except (ValueError, TypeError):
        _reject(reasons, "malformed_injection_flags")

    if reasons:
        return None, reasons

    assert rule is not None and applies is not None
    return {
        "detail_id": row["dedupe_key"],
        "candidate": {
            "candidate_id": int(row["id"]),
            "state": state,
            "state_set_by": set_by,
            "publishable": 1,
            "rule_id": rule_id,
            "rule_version": rule_version,
        },
        "applicability": {
            "kind": "meal_template",
            "template_name": applies.template_name,
            "required_ingredients": list(applies.required_ingredients),
        },
        "guidance": {
            # Fixed reviewer-authored rule text, plus the whole evidence sentence that supports it.
            "text": rule.action,
            "supporting_passage": support_quote,
        },
        "evidence": {
            "evidence_id": str(row["evidence_id"]),
            "revision": int(row["version_no"]),
            "content_hash": row["content_hash"],
            "source_url": row["source_url"],
            "attribution": row["attribution"],
            "checked_at": row["fetched_at"],
            "published_at": row["published_at"],
        },
    }, []


_EXPORT_SQL = """
    SELECT c.id, c.dedupe_key, c.evidence_id, c.state, c.state_set_by, c.publishable, c.validation,
           e.url AS source_url, e.content_hash, e.version_no, e.fetched_at, e.published_at,
           e.attribution, e.injection_flags, e.content_kind, t.text AS evidence_text
      FROM candidates c
      JOIN evidence e ON e.id = c.evidence_id
      LEFT JOIN evidence_text t ON t.evidence_id = e.id
     ORDER BY c.id
"""


def export_meal_details(
    conn: sqlite3.Connection,
    applicability: Dict[str, MealApplicability] = MEAL_APPLICABILITY,
    rules: Tuple[SupportRule, ...] = RULES,
    generated_at: Optional[str] = None,
    allow_fixture_evidence: bool = False,
) -> Dict[str, Any]:
    """Build the versioned payload the app consumes. Deterministic; ordered by candidate id.

    Candidates that fail any gate are omitted from `details` and listed in `omitted` with a reason,
    so a reviewer can see why something did not publish instead of it silently vanishing.
    """
    conn.row_factory = sqlite3.Row
    rule_index = _rule_index(rules)
    details: List[Dict[str, Any]] = []
    omitted: List[Dict[str, Any]] = []

    for row in conn.execute(_EXPORT_SQL):
        detail, reasons = build_meal_detail(row, applicability, rule_index, allow_fixture_evidence)
        if detail is not None:
            details.append(detail)
        else:
            omitted.append({"candidate_id": int(row["id"]), "reasons": reasons})

    payload: Dict[str, Any] = {
        "payload_version": MEAL_EXPORT_PAYLOAD_VERSION,
        "capability": MEAL_EXPORT_CAPABILITY,
        "details": details,
        "omitted": omitted,
    }
    if allow_fixture_evidence:
        # Self-identifying: the consumer refuses any payload carrying this key, so a snapshot built
        # with the test-only escape hatch can never be bundled and quietly published.
        payload["_test_only_fixture_evidence"] = True
    if generated_at is not None:
        payload["generated_at"] = generated_at
    return payload
