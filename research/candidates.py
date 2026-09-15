"""Turn a model proposal into a reviewable candidate, grounding every claim first.

Rules (WEL-40 AC3/AC5/AC6):
  * observations must be verbatim substrings of the evidence text; anything else is demoted
  * a candidate with no grounded observation is rejected, not approved on model confidence
  * product mentions not present in the text mark the candidate deferred (unsupported identity)
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


def build_candidate(evidence_row: sqlite3.Row, evidence_text: str, proposal: Optional[Dict[str, Any]],
                    generator: str, failure_reason: Optional[str] = None) -> Dict[str, Any]:
    text_norm = _norm(evidence_text)
    injection_flags = json.loads(evidence_row["injection_flags"] or "[]")
    cand: Dict[str, Any] = {
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
    }
    if proposal is None:
        cand["state"], cand["state_reason"] = "deferred", failure_reason or "inference_unavailable"
        return cand

    for q in _as_list(proposal.get("observations")):
        (cand["observations"] if _grounded(q, text_norm) else cand["unsupported_claims"]).append(q)
    cand["inferences"] = _as_list(proposal.get("inferences"))
    cand["relevance_conditions"] = _as_list(proposal.get("relevance_conditions"))
    cand["household_problem"] = (proposal.get("household_problem") or None)
    cand["proposed_action"] = (proposal.get("proposed_action") or None)

    lt = proposal.get("lead_time_days")
    cand["lead_time_days"] = int(lt) if isinstance(lt, (int, float)) and not isinstance(lt, bool) else None
    eq = proposal.get("expiry_quote")
    if isinstance(eq, str) and _grounded(eq, text_norm):
        cand["expiry_basis"] = eq            # a supported timing statement; a date is only set by a human
    elif eq:
        cand["unsupported_claims"].append("expiry: %s" % eq)

    unsupported_products = []
    for name in _as_list(proposal.get("product_mentions")):
        ok = _norm(name) in text_norm
        cand["product_mentions"].append({"name": name, "grounded": ok})
        if not ok:
            unsupported_products.append(name)

    # Any 'approved' / confidence field from the model is ignored on purpose.
    if not cand["household_problem"] or not cand["proposed_action"]:
        cand["state"], cand["state_reason"] = "rejected", "incomplete_proposal: missing problem or action"
    elif not cand["observations"]:
        cand["state"], cand["state_reason"] = "rejected", "no_grounded_observation: no quote matched the evidence"
    elif unsupported_products:
        cand["state"], cand["state_reason"] = "deferred", "unsupported_product_identity: %s" % ", ".join(unsupported_products)
    elif injection_flags:
        cand["state"], cand["state_reason"] = "deferred", "source_embedded_instructions_flagged: human review required"
    return cand


def save_candidate(conn: sqlite3.Connection, cand: Dict[str, Any]) -> Optional[int]:
    """Insert if the dedupe key is new; return id or None if it already existed."""
    if conn.execute("SELECT 1 FROM candidates WHERE dedupe_key=?", (cand["dedupe_key"],)).fetchone():
        return None
    ts = now_iso()
    cur = conn.execute(
        """INSERT INTO candidates(dedupe_key, evidence_id, generator, household_problem, proposed_action,
               observations, inferences, unsupported_claims, relevance_conditions, lead_time_days, expires_at,
               expiry_basis, product_mentions, source_attribution, proposed_destination, stock_price_claims,
               state, state_reason, state_set_by, publishable, created_at, updated_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (cand["dedupe_key"], cand["evidence_id"], cand["generator"], cand["household_problem"],
         cand["proposed_action"], json.dumps(cand["observations"]), json.dumps(cand["inferences"]),
         json.dumps(cand["unsupported_claims"]), json.dumps(cand["relevance_conditions"]), cand["lead_time_days"],
         cand["expires_at"], cand["expiry_basis"], json.dumps(cand["product_mentions"]), cand["source_attribution"],
         cand["proposed_destination"], cand["stock_price_claims"], cand["state"], cand["state_reason"],
         cand["state_set_by"], cand["publishable"], ts, ts),
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
