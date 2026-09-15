"""EXPERIMENTAL challenger for sentence segmentation (WEL-43 AC3). NOT the default.

Nothing in the collection path imports this module: `research/worker.py` and `research/rules.py`
keep the incumbent `rules.sentence_units` behaviour. This file exists so one adjustment can be
measured against a frozen set of cases, and it is adopted only by a human editing `rules.py` after
reading the evaluation.

The adjustment, in one sentence: *a line break that falls in the middle of a sentence should not end
that sentence.*

The incumbent treats every newline as a sentence boundary. Extracted text gets a newline from every
block-level tag, so a sentence interrupted by an inline `<div>`/`<li>`/`<br>` arrives as two
fragments and can no longer match a reviewed sentence as a whole. The challenger rejoins a line with
the following one when the first does not end in a sentence terminator and the second starts like a
continuation, and it neutralises invisible characters (NBSP, zero-width marks, soft hyphens) that
make an otherwise identical sentence compare unequal.

Scope of any claim made from this module: **sentence processing over already-extracted text.** It
does not change HTML extraction, stored text, content hashes or evidence versioning; it runs at
match time only.
"""
import re
from typing import Dict, Iterator, List, Optional, Tuple

from .rules import RULES, RuleMatch, SupportRule, normalize_sentence

VERSION = "sentence_integrity_v1"

# Invisible characters that render as nothing (or as a space) but break exact comparison.
_NBSP = "   "
_ZERO_WIDTH = "​‌‍⁠﻿­"
_TERMINATORS = ".!?:;"
# A following line continues the previous one when it starts lowercase, with a closing punctuation
# mark, or with a conjunction that cannot start a reviewed sentence on its own.
_CONTINUATION = re.compile(r"^[a-z0-9,;)\]’'\"-]")


def normalize_invisibles(text: str) -> str:
    for ch in _NBSP:
        text = text.replace(ch, " ")
    for ch in _ZERO_WIDTH:
        text = text.replace(ch, "")
    return text


def rejoin_lines(text: str) -> List[str]:
    """Merge continuation lines into single logical blocks. Deterministic and order preserving."""
    blocks: List[str] = []
    for raw in normalize_invisibles(text or "").split("\n"):
        line = raw.strip()
        if not line:
            continue
        if blocks:
            prev = blocks[-1]
            if prev and prev[-1] not in _TERMINATORS and _CONTINUATION.match(line):
                blocks[-1] = "%s %s" % (prev, line)
                continue
        blocks.append(line)
    return blocks


def sentence_units(text: str) -> Iterator[Tuple[str, str]]:
    """Challenger counterpart of `rules.sentence_units`, over rejoined blocks."""
    for block in rejoin_lines(text):
        for unit in re.split(r"(?<=[.!?])\s+", block):
            n = normalize_sentence(unit)
            if n:
                yield n, re.sub(r"\s+", " ", unit).strip()


def _find(units: Dict[str, str], reviewed: Tuple[str, ...]) -> Optional[str]:
    for s in reviewed:
        hit = units.get(normalize_sentence(normalize_invisibles(s)))
        if hit is not None:
            return hit
    return None


def match_rules(evidence_text: str, rules: Tuple[SupportRule, ...] = RULES) -> List[RuleMatch]:
    """Same contract and same whole-sentence requirement as `rules.match_rules`, different segmentation."""
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
