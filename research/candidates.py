"""Build reviewable candidates. Two generators, kept apart on purpose:

  * rule candidates (research/rules.py): a fixed prepared action whose reviewed support sentence
    occurs as a whole sentence in the evidence. Deterministic, no model. These are the only
    candidates the worker ever saves as 'pending'.
  * free-text model proposals: validated (grounded quotes, shopping claims, invented identities,
    timing) so the reason is specific, then ALWAYS deferred or rejected. The model's prose is
    stored raw in `validation` for audit and is never shown as action/inference/product output.

Rules (WEL-40 AC3/AC5/AC6):
  * observations must be verbatim substrings of the evidence text; anything else is demoted
  * a proposal with no grounded observation is rejected, not approved on model confidence
  * price/stock/discount/purchase claims or brand-like identities not present in the text, in any
    prose field, give a specific defer reason (they are not the safety boundary; the closed
    action registry is)
  * lead_time_days is kept only when a grounded quote states that very whole-number value
  * evidence flagged for embedded instructions -> candidate deferred for human review
  * state is never 'approved' when set by the worker; publishable is never set here
  * proposed_destination stays NULL; stock/price claims stay 'not_verified'
"""
import hashlib
import json
import re
import sqlite3
from typing import Any, Dict, List, Optional

from .fetch import now_iso
from .rules import RuleMatch

FREE_TEXT_DEFER_REASON = ("unvalidated_free_text: model prose is not a registered supported action; "
                          "raw output retained for audit, not shown")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def _grounded(quote: str, text_norm: str) -> bool:
    # Tolerate only surrounding quotes/trailing punctuation; wording must match verbatim.
    q = _norm(quote).strip('"\u201c\u201d\'').rstrip(".;:,!")
    return bool(q) and len(q) >= 12 and q in text_norm


def dedupe_key(evidence_id: int, generator: str) -> str:
    return hashlib.sha256(("%d|%s" % (evidence_id, generator)).encode()).hexdigest()


def _as_list(v: Any) -> List[str]:
    if isinstance(v, list):
        return [str(x) for x in v if str(x).strip()]
    if isinstance(v, str) and v.strip():
        return [v]
    return []



# ---- proposal validation (F2/F3): the smallest enforceable representation -------------
PROSE_FIELDS = ("household_problem", "proposed_action", "inferences", "relevance_conditions")

SHOPPING_CLAIM_PATTERNS = [
    (r"[$€£]\s?\d", "price"),
    (r"\b\d+([.,]\d+)?\s?(usd|dollars|eur|gbp)\b", "price"),
    (r"\b(in|out of|back in|low) stock\b", "stock"),
    (r"\b(sold out|available (now|today)|ships (today|tomorrow)|limited (stock|quantity))\b", "stock"),
    (r"\b(\d+\s?% off|on sale|discount(ed)?|deal of the day|promo code|coupon)\b", "discount"),
    (r"\b(buy(?!\s+guide)|purchase|add to cart)\b|\border (the|a|an|it|now|today|online|from|yours)\b|(?:^|[.!?]\s+)order\b|\bshop (for|the|now|at|it)\b", "purchase"),
]
_SHOP = [(re.compile(p, re.I), kind) for p, kind in SHOPPING_CLAIM_PATTERNS]

# brand/model-like tokens: mid-sentence Capitalized runs of 2+ words, or letter+digit codes (V15, X100)
_IDENTITY_RUN = re.compile(r"(?<![.!?]\s)(?<!^)\b([A-Z][\w&'-]+(?:\s+[A-Z][\w&'-]+)+)")
_MODEL_CODE = re.compile(r"\b(?=[A-Za-z]*\d)(?=\d*[A-Za-z])[A-Za-z0-9-]{2,}\b")
_UNIT_DAYS = {"day": 1, "days": 1, "week": 7, "weeks": 7, "month": 30, "months": 30}
_NUM_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
              "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "a": 1, "an": 1}


def shopping_claims(text: str) -> List[str]:
    return sorted({kind for rx, kind in _SHOP if rx.search(text or "")})


def unsupported_identities(text: str, text_norm: str) -> List[str]:
    found = []
    for m in _IDENTITY_RUN.finditer(text or ""):
        run = m.group(1)
        if _norm(run) not in text_norm:
            found.append(run)
    for m in _MODEL_CODE.finditer(text or ""):
        tok = m.group(0)
        if _norm(tok) not in text_norm:
            found.append(tok)
    return found


_PERIOD_WORDS = {"daily": 1, "weekly": 7, "monthly": 30}


_TIMING_RX = re.compile(
    # a complete whole-number quantity only: not the '5' of '1.5', '1,5', '2-3' or '1/2', not 'half a week'
    r"(?<![\d.,/–-])(?<!half )(?<!quarter )\b(\d+|%s)\b(?![.,/–-]\d)\s+(days?|weeks?|months?)\b"
    % "|".join(_NUM_WORDS))


def timing_days_in_quote(quote: str) -> List[int]:
    """Every day-count a quote literally supports: 'every two weeks' -> [14], 'every week' -> [7].
    Decimal, fractional, ranged or otherwise incomplete quantities support nothing."""
    q = (quote or "").lower()
    out = []
    for m in _TIMING_RX.finditer(q):
        n = int(m.group(1)) if m.group(1).isdigit() else _NUM_WORDS[m.group(1)]
        out.append(n * _UNIT_DAYS[m.group(2)])
    for m in re.finditer(r"\b(every|each|per)\s+(day|week|month)\b", q):
        out.append(_UNIT_DAYS[m.group(2)])
    for word, days in _PERIOD_WORDS.items():
        if re.search(r"\b%s\b" % word, q):
            out.append(days)
    return out


def _as_int(v: Any) -> Optional[int]:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    if v != v or v in (float("inf"), float("-inf")) or v != int(v):
        return None
    return int(v)


def validate_proposal(proposal: Dict[str, Any], text_norm: str) -> Dict[str, Any]:
    """Coerce the model output into typed fields and collect every reason it cannot be
    an ordinary pending candidate. Nothing outside the returned keys is used."""
    v: Dict[str, Any] = {
        "household_problem": proposal.get("household_problem") if isinstance(proposal.get("household_problem"), str) else None,
        "proposed_action": proposal.get("proposed_action") if isinstance(proposal.get("proposed_action"), str) else None,
        "observations": _as_list(proposal.get("observations")),
        "inferences": _as_list(proposal.get("inferences")),
        "relevance_conditions": _as_list(proposal.get("relevance_conditions")),
        "product_mentions": _as_list(proposal.get("product_mentions")),
        "expiry_quote": proposal.get("expiry_quote") if isinstance(proposal.get("expiry_quote"), str) else None,
        "lead_time_quote": proposal.get("lead_time_quote") if isinstance(proposal.get("lead_time_quote"), str) else None,
        "lead_time_days": None,
        "lead_time_basis": None,
        "unsupported": [],
        "defer_reasons": [],
        "type_errors": [],
    }
    for key in ("household_problem", "proposed_action", "expiry_quote", "lead_time_quote"):
        if key in proposal and proposal[key] is not None and not isinstance(proposal[key], str):
            v["type_errors"].append("%s must be a string" % key)
    for key in ("observations", "inferences", "relevance_conditions", "product_mentions"):
        if key in proposal and proposal[key] is not None and not isinstance(proposal[key], (list, str)):
            v["type_errors"].append("%s must be a list" % key)

    # F2: shopping claims and invented identities anywhere in the prose
    prose = [v["household_problem"] or "", v["proposed_action"] or ""] + v["inferences"] + v["relevance_conditions"]
    claims = sorted({c for t in prose for c in shopping_claims(t)})
    if claims:
        v["defer_reasons"].append("unsupported_shopping_claim: %s" % ", ".join(claims))
    idents = []
    for t in prose:
        idents += unsupported_identities(t, text_norm)
    if idents:
        v["defer_reasons"].append("unsupported_product_identity: %s" % ", ".join(dict.fromkeys(idents)))

    # F3: timing must be supported by a grounded quote that states that very value
    raw = proposal.get("lead_time_days")
    days = _as_int(raw)
    if raw is not None:
        if days is None or days < 0 or days > 3650:
            v["unsupported"].append("lead_time_days: invalid value %r" % (raw,))
        elif not (v["lead_time_quote"] and _grounded(v["lead_time_quote"], text_norm)):
            v["unsupported"].append("lead_time_days: %d has no grounded timing quote" % days)
        elif days not in timing_days_in_quote(v["lead_time_quote"]):
            v["unsupported"].append("lead_time_days: %d not stated by quote %r" % (days, v["lead_time_quote"]))
        else:
            v["lead_time_days"], v["lead_time_basis"] = days, v["lead_time_quote"]
    return v


def _empty_candidate(evidence_row: sqlite3.Row, generator: str) -> Dict[str, Any]:
    return {
        "dedupe_key": dedupe_key(int(evidence_row["id"]), generator),
        "evidence_id": int(evidence_row["id"]),
        "generator": generator,
        "household_problem": None,
        "proposed_action": None,
        "observations": [],
        "inferences": [],
        "unsupported_claims": [],
        "relevance_conditions": [],
        "lead_time_days": None,
        "lead_time_basis": None,
        "expires_at": None,
        "expiry_basis": None,
        "product_mentions": [],
        "source_attribution": evidence_row["attribution"],
        "proposed_destination": None,
        "stock_price_claims": "not_verified",
        "state": "pending",
        "state_reason": None,
        "state_set_by": "worker",
        "publishable": 0,
        "validation": None,   # JSON: {"kind": "rule", ...} | {"kind": "free_text", ...}; NULL = legacy (unvalidated)
    }


def build_rule_candidate(evidence_row: sqlite3.Row, match: RuleMatch) -> Dict[str, Any]:
    """A pending candidate whose every displayed word is fixed rule text or a whole evidence sentence."""
    r = match.rule
    injection_flags = json.loads(evidence_row["injection_flags"] or "[]")
    cand = _empty_candidate(evidence_row, r.generator)
    cand["household_problem"] = match.problem_quote
    cand["proposed_action"] = r.action
    cand["observations"] = [match.support_quote] + ([match.problem_quote] if match.problem_quote else [])
    cand["relevance_conditions"] = [r.relevance]
    cand["validation"] = {"kind": "rule", "rule_id": r.rule_id, "rule_version": r.version,
                          "support_quote": match.support_quote, "problem_quote": match.problem_quote,
                          "model_inference": False, "review_note": r.review_note}
    if not match.complete:
        cand["state"], cand["state_reason"] = "deferred", (
            "rule_support_incomplete: support sentence present but no reviewed problem sentence "
            "occurs as a whole sentence in this evidence")
    elif injection_flags:
        cand["state"], cand["state_reason"] = "deferred", "source_embedded_instructions_flagged: human review required"
    return cand


def build_candidate(evidence_row: sqlite3.Row, evidence_text: str, proposal: Optional[Dict[str, Any]],
                    generator: str, failure_reason: Optional[str] = None) -> Dict[str, Any]:
    """Validate a free-text model proposal and return a deferred/rejected candidate with a specific
    reason. Never pending: free prose is not a registered action. The raw proposal is kept for audit."""
    text_norm = _norm(evidence_text)
    injection_flags = json.loads(evidence_row["injection_flags"] or "[]")
    cand = _empty_candidate(evidence_row, generator)
    cand["validation"] = {"kind": "free_text", "raw_proposal": proposal, "model_inference": True}
    if proposal is None:
        cand["state"], cand["state_reason"] = "deferred", failure_reason or "inference_unavailable"
        return cand
    if not isinstance(proposal, dict):
        cand["state"], cand["state_reason"] = "rejected", "invalid_proposal: not an object"
        return cand

    v = validate_proposal(proposal, text_norm)
    for q in v["observations"]:
        (cand["observations"] if _grounded(q, text_norm) else cand["unsupported_claims"]).append(q)
    # household_problem / proposed_action / inferences / relevance_conditions / product_mentions stay
    # empty on the row: model prose is audit material (validation.raw_proposal), not display content.
    cand["lead_time_days"], cand["lead_time_basis"] = v["lead_time_days"], v["lead_time_basis"]
    cand["unsupported_claims"] += v["unsupported"]
    eq = v["expiry_quote"]
    if eq and _grounded(eq, text_norm):
        cand["expiry_basis"] = eq            # a supported timing statement; a date is only set by a human
    elif eq:
        cand["unsupported_claims"].append("expiry: %s" % eq)

    unsupported_products = [name for name in v["product_mentions"] if _norm(name) not in text_norm]

    # Any 'approved' / confidence field from the model is ignored on purpose.
    if v["type_errors"]:
        cand["state"], cand["state_reason"] = "rejected", "invalid_proposal_types: %s" % "; ".join(v["type_errors"])
    elif not v["household_problem"] or not v["proposed_action"]:
        cand["state"], cand["state_reason"] = "rejected", "incomplete_proposal: missing problem or action"
    elif not cand["observations"]:
        cand["state"], cand["state_reason"] = "rejected", "no_grounded_observation: no quote matched the evidence"
    elif v["defer_reasons"] or unsupported_products:
        reasons = list(v["defer_reasons"])
        if unsupported_products:
            reasons.append("unsupported_product_identity: %s" % ", ".join(unsupported_products))
        cand["state"], cand["state_reason"] = "deferred", "; ".join(reasons)
    elif injection_flags:
        cand["state"], cand["state_reason"] = "deferred", "source_embedded_instructions_flagged: human review required"
    else:
        cand["state"], cand["state_reason"] = "deferred", FREE_TEXT_DEFER_REASON
    return cand


def save_candidate(conn: sqlite3.Connection, cand: Dict[str, Any]) -> Optional[int]:
    """Insert if the dedupe key is new; return id or None if it already existed."""
    if conn.execute("SELECT 1 FROM candidates WHERE dedupe_key=?", (cand["dedupe_key"],)).fetchone():
        return None
    ts = now_iso()
    cur = conn.execute(
        """INSERT INTO candidates(dedupe_key, evidence_id, generator, household_problem, proposed_action,
               observations, inferences, unsupported_claims, relevance_conditions, lead_time_days, lead_time_basis,
               expires_at, expiry_basis, product_mentions, source_attribution, proposed_destination, stock_price_claims,
               state, state_reason, state_set_by, publishable, validation, created_at, updated_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (cand["dedupe_key"], cand["evidence_id"], cand["generator"], cand["household_problem"],
         cand["proposed_action"], json.dumps(cand["observations"]), json.dumps(cand["inferences"]),
         json.dumps(cand["unsupported_claims"]), json.dumps(cand["relevance_conditions"]), cand["lead_time_days"],
         cand["lead_time_basis"], cand["expires_at"], cand["expiry_basis"], json.dumps(cand["product_mentions"]), cand["source_attribution"],
         cand["proposed_destination"], cand["stock_price_claims"], cand["state"], cand["state_reason"],
         cand["state_set_by"], cand["publishable"],
         json.dumps(cand["validation"], default=str) if cand["validation"] is not None else None, ts, ts),
    )
    return int(cur.lastrowid)


VALID_HUMAN_STATES = ("approved", "rejected", "deferred", "pending")


def human_review(conn: sqlite3.Connection, candidate_id: int, state: str, reviewer: str, reason: str) -> None:
    """Only a named human sets 'approved'. Approval does not make a candidate publishable."""
    if state not in VALID_HUMAN_STATES:
        raise ValueError("state must be one of %s" % (VALID_HUMAN_STATES,))
    if not reviewer or not reason:
        raise ValueError("reviewer and reason are required")
    cur = conn.execute(
        "UPDATE candidates SET state=?, state_reason=?, state_set_by=?, updated_at=? WHERE id=?",
        (state, reason, "human:%s" % reviewer, now_iso(), candidate_id),
    )
    if cur.rowcount != 1:
        raise ValueError("candidate %d not found" % candidate_id)
