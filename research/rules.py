"""Closed registry of supported prepared actions and the exact source sentences that support them.

This is a small curated evidence-to-action mapping, not language understanding. A rule fires only
when a reviewer-curated positive sentence appears in the evidence as a COMPLETE sentence: same words,
same order, whole sentence boundary on both sides. A prefix ("Do not assume that ..."), a suffix
(", unless ..."), a question mark, or any rewording does not match; unknown phrasing simply produces
no rule candidate. Every displayed word of a rule candidate comes from this file or verbatim from
the evidence. No model output enters a rule candidate, and nothing here follows source instructions.

Adding an action means adding a rule here with sentences a reviewer has read in real evidence.
"""
import re
from dataclasses import dataclass
from typing import Dict, Iterator, List, Optional, Tuple


@dataclass(frozen=True)
class SupportRule:
    rule_id: str
    version: int
    action: str                          # the prepared action text shown to reviewers (fixed)
    relevance: str                       # fixed relevance condition
    support_sentences: Tuple[str, ...]   # reviewed sentences; any one, as a whole sentence, supports the action
    problem_sentences: Tuple[str, ...]   # reviewed sentences stating the household problem
    review_note: str = ""

    @property
    def generator(self) -> str:
        return "rule:%s@%d" % (self.rule_id, self.version)


RULES: Tuple[SupportRule, ...] = (
    SupportRule(
        rule_id="air_fryer_basket_after_each_use",
        version=1,
        action="Remind the household to clean the air fryer basket after each use.",
        relevance="household owns an air fryer",
        support_sentences=(
            "This may surprise you more than how much your appliance can tackle, but air fryer baskets "
            "need to be cleaned after every use.",
        ),
        problem_sentences=(
            "Regular cleaning helps prevent grease buildup, lingering odors, and stuck-on food that can "
            "make cleanup even harder the next time you cook.",
        ),
        review_note="Sentences read by reviewer Astra (2026-09-15) from the Good Housekeeping air fryer "
                    "basket evidence in the WEL-40 demo run. No lead time: 'after every use' is a cadence, "
                    "not an advance notice period.",
    ),
    SupportRule(
        rule_id="rinse_fresh_produce_under_running_water",
        version=1,
        action="Rinse the fresh vegetables for this meal under running water.",
        relevance="the planned meal uses fresh vegetables",
        support_sentences=(
            "Rinse fresh fruits and vegetables under running water.",
        ),
        problem_sentences=(
            "Unwashed fruits and vegetables",
            "Germs that cause food poisoning can survive in many places and spread around your kitchen.",
        ),
        review_note="Sentences read from live CDC evidence id=6, content hash "
                    "b2574db36c04e96958bae89bb4ec9f9e52d2d1ec1dcc01698e8d08af81aeb418, fetched "
                    "2026-09-15T15:33:48Z from https://www.cdc.gov/food-safety/prevention/index.html "
                    "(U.S. federal government work; attribute, do not imply endorsement). The action "
                    "restates the support sentence and adds no temperature, time or safety claim the "
                    "source does not make. Registered as reviewer-curated engineering; publication still "
                    "requires a named human approval plus a separate publishable decision.",
    ),
)

_QUOTES = {"‘": "'", "’": "'", "“": '"', "”": '"'}


def normalize_sentence(s: str) -> str:
    """Whitespace, case and curly quotes are not meaning; everything else must match exactly.
    Only one final full stop is optional. '?', '!' or extra punctuation stay and must match."""
    for k, v in _QUOTES.items():
        s = s.replace(k, v)
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s[:-1].rstrip() if s.endswith(".") else s


def sentence_units(text: str) -> Iterator[Tuple[str, str]]:
    """Yield (normalized, original) complete sentences. Block breaks (newlines) and sentence
    terminators followed by whitespace are boundaries; nothing inside a sentence is a boundary."""
    for block in (text or "").split("\n"):
        for unit in re.split(r"(?<=[.!?])\s+", block):
            n = normalize_sentence(unit)
            if n:
                yield n, re.sub(r"\s+", " ", unit).strip()


@dataclass(frozen=True)
class RuleMatch:
    rule: SupportRule
    support_quote: str               # the evidence sentence itself (whole), as written in the evidence
    problem_quote: Optional[str]     # None when no reviewed problem sentence is present as a whole sentence

    @property
    def complete(self) -> bool:
        return self.problem_quote is not None


def _find(units: Dict[str, str], reviewed: Tuple[str, ...]) -> Optional[str]:
    for s in reviewed:
        hit = units.get(normalize_sentence(s))
        if hit is not None:
            return hit
    return None


def match_rules(evidence_text: str, rules: Tuple[SupportRule, ...] = RULES) -> List[RuleMatch]:
    """Rules whose support sentence occurs as a whole sentence in the evidence. Deterministic; no model."""
    units: Dict[str, str] = {}
    for n, original in sentence_units(evidence_text):
        units.setdefault(n, original)
    out = []
    for r in rules:
        sup = _find(units, r.support_sentences)
        if sup is None:
            continue
        out.append(RuleMatch(r, sup, _find(units, r.problem_sentences)))
    return out
