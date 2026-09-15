"""WEL-42 producer: export approved, publishable rule candidates as a versioned meal-detail payload.

This is the only path by which research content may reach the app. It is deliberately narrow:

  * Only RULE candidates are exportable. Free-text model prose is never publishable (see
    candidates.py) and is additionally rejected here, so no arbitrary model wording can reach a card.
  * A candidate must be `state='approved'` AND `state_set_by` a named human AND `publishable=1`.
    This module never sets any of those; it only reads them. Approval by itself is not enough.
  * The rule must still be registered in rules.py at the exact version recorded on the candidate.
    A rule that was edited or withdrawn stops exporting rather than exporting stale wording.
  * What is published is a whole reviewed GUIDE from research/meal_guides.py — approval covers the
    guide as one unit. A rule with no guide cannot be attached to any meal.
  * Applicability is exact and reviewer-registered: one meal template name plus the ingredient
    tokens that template must contain. It is NOT keyword matching over recipe text.
  * Every displayed string is reviewer-written paraphrase, and each is bound to an `anchor` that is
    re-verified here as a whole sentence in evidence still matching its recorded content hash.

Household data never enters this module. It reads the research database only; nothing about a
household is an input, so nothing about a household can be written back.
"""
import hashlib
import json
import sqlite3
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from .meal_guides import MEAL_GUIDES, MealGuide
from .rules import RULES, SupportRule, match_rules, normalize_sentence, sentence_units

MEAL_EXPORT_PAYLOAD_VERSION = 1
MEAL_EXPORT_CAPABILITY = "weekly_meal_plan"


def _evidence_index(conn: sqlite3.Connection) -> Dict[str, sqlite3.Row]:
    """url -> evidence row (with text), newest revision wins."""
    rows = conn.execute(
        """SELECT e.*, t.text AS evidence_text
             FROM evidence e LEFT JOIN evidence_text t ON t.evidence_id = e.id
            ORDER BY e.version_no"""
    )
    return {row["url"]: row for row in rows}


def verify_guide_sources(
    guide: MealGuide,
    evidence_by_url: Dict[str, sqlite3.Row],
    allow_fixture_evidence: bool,
) -> Tuple[Dict[str, sqlite3.Row], List[str]]:
    """Every source a guide cites must be present, live, intact and actually contain each anchor.

    This is the whole safety story for a multi-line guide: a paraphrase is only publishable while the
    sentence it was written from is still in the source, and the source still hashes to what was
    recorded. One loop, checked per item — not a registry per step.
    """
    reasons: List[str] = []
    used: Dict[str, sqlite3.Row] = {}

    for url in guide.source_urls:
        row = evidence_by_url.get(url)
        if row is None:
            reasons.append("guide_source_missing: no stored evidence for %s" % url)
            continue
        text = row["evidence_text"]
        if text is None:
            reasons.append("guide_source_has_no_text: %s" % url)
            continue
        if hashlib.sha256(text.encode("utf-8")).hexdigest() != row["content_hash"]:
            reasons.append("guide_source_hash_mismatch: %s" % url)
            continue
        if (row["content_kind"] or "") != "live" and not allow_fixture_evidence:
            reasons.append("guide_source_not_live: %s" % url)
            continue
        try:
            if json.loads(row["injection_flags"] or "[]"):
                reasons.append("guide_source_instructions_flagged: %s" % url)
                continue
        except (ValueError, TypeError):
            reasons.append("guide_source_malformed_injection_flags: %s" % url)
            continue
        used[url] = row

    for item in guide.items:
        row = used.get(item.source_url)
        if row is None:
            continue  # its source already produced a reason
        units = {normalize_sentence(o): o for _, o in sentence_units(row["evidence_text"])}
        # Ingredient lines contain abbreviations such as "15oz."; preserve the whole line
        # as an exact anchor rather than accepting only the sentence splitter's fragment.
        units.update({normalize_sentence(line): line for line in row["evidence_text"].splitlines()
                      if line.strip()})
        if normalize_sentence(item.anchor) not in units:
            reasons.append("guide_anchor_not_in_evidence: %r not a whole sentence or complete line in %s"
                           % (item.text[:60], item.source_url))

    return used, reasons


def _evidence_payload(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "evidence_id": str(row["id"]),
        "title": row["title"],
        "revision": int(row["version_no"]),
        "content_hash": row["content_hash"],
        "source_url": row["url"],
        "attribution": row["attribution"],
        "checked_at": row["fetched_at"],
        "published_at": row["published_at"],
    }


def _guide_payload(guide: MealGuide, used: Dict[str, sqlite3.Row]) -> Dict[str, Any]:
    def section(items):
        return [
            {"text": i.text, "anchor": i.anchor, "evidence_id": str(used[i.source_url]["id"])}
            for i in items
        ]

    payload: Dict[str, Any] = {
        "title": guide.title,
        "summary": guide.summary,
        "equipment": section(guide.equipment),
        "extra_ingredients": section(guide.extra_ingredients),
        "steps": section(guide.steps),
        "cautions": section(guide.cautions),
    }
    # Only present when a source states them; absent rather than estimated.
    if guide.servings is not None:
        payload["servings"] = guide.servings
    if guide.total_time_minutes is not None:
        payload["total_time_minutes"] = guide.total_time_minutes
    return payload


def _rule_index(rules: Tuple[SupportRule, ...]) -> Dict[Tuple[str, int], SupportRule]:
    return {(r.rule_id, r.version): r for r in rules}


def _reject(reasons: List[str], detail: str) -> None:
    reasons.append(detail)


def build_meal_detail(
    row: sqlite3.Row,
    guides: Dict[str, MealGuide],
    rule_index: Dict[Tuple[str, int], SupportRule],
    evidence_by_url: Dict[str, sqlite3.Row],
    allow_fixture_evidence: bool = False,
) -> Tuple[Optional[Dict[str, Any]], List[str]]:
    """Return (detail, rejection_reasons). A detail is returned only when every gate passes."""
    reasons: List[str] = []
    used_sources: Dict[str, sqlite3.Row] = {}

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

    guide = guides.get(rule_id)
    if guide is None:
        _reject(reasons, "no_registered_meal_guide: %s" % rule_id)
    elif guide.version != rule_version:
        _reject(reasons, "guide_version_mismatch: guide %s@%d vs candidate @%d"
                % (rule_id, guide.version, rule_version))
    else:
        used_sources, guide_reasons = verify_guide_sources(
            guide, evidence_by_url, allow_fixture_evidence)
        reasons.extend(guide_reasons)

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

    assert rule is not None and guide is not None
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
            "template_name": guide.template_name,
            "required_ingredients": list(guide.required_ingredients),
            # Ingredients the guide adds beyond the template. The app checks these against household
            # exclusions before attaching, so a guide can never smuggle in a rejected ingredient.
            "introduced_ingredients": list(guide.introduced_ingredients),
        },
        "guide": _guide_payload(guide, used_sources),
        # Every source the guide cites, in the order the guide first uses them.
        "sources": [_evidence_payload(used_sources[u]) for u in guide.source_urls],
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
    guides: Dict[str, MealGuide] = MEAL_GUIDES,
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
    evidence_by_url = _evidence_index(conn)
    details: List[Dict[str, Any]] = []
    omitted: List[Dict[str, Any]] = []

    for row in conn.execute(_EXPORT_SQL):
        detail, reasons = build_meal_detail(
            row, guides, rule_index, evidence_by_url, allow_fixture_evidence)
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
