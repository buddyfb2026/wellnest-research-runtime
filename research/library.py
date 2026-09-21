"""Local, read-only browser for current WellNest recipe research.

This module deliberately has no dependency on the worker configuration or database
migrations.  It opens an existing SQLite file in URI read-only mode and renders a
small server-side HTML application for loopback use only.
"""

from __future__ import annotations

import argparse
import html
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterable, List, Mapping, Optional, Sequence
from urllib.parse import parse_qs, quote, unquote, urlparse

from .recipe_pack import build_served_state


ASSET_DIR = Path(__file__).with_name("library_assets")
STATUS_ORDER = (
    "Ready for review", "Missing information", "Approved", "On hold",
    "Withdrawn", "Rejected", "Extraction failed", "Status unavailable",
)
ALLOWED_BIND_HOSTS = frozenset(("127.0.0.1",))
SOURCE_UNSPECIFIED_REASONS = frozenset(("not_stated_by_source",))


class LibraryUnavailable(RuntimeError):
    """The existing research store cannot safely supply the library."""


@dataclass(frozen=True)
class RecipeCard:
    recipe_id: int
    recipe_version_id: int
    title: str
    source: str
    source_url: Optional[str]
    status: str
    status_note: str
    details_hidden: bool
    summary: str
    total_time: Optional[str]
    servings: Optional[str]
    ingredient_count: int
    step_count: int
    ingredients: Sequence[str]
    steps: Sequence[str]
    source_missing: Sequence[str]
    extraction_issues: Sequence[str]
    autopilot_status: str
    autopilot_label: str
    autopilot_note: str
    created_at: str
    collected_label: str


@dataclass(frozen=True)
class LibrarySnapshot:
    recipes: Sequence[RecipeCard]
    all_count: int
    sources: Sequence[str]
    status_counts: Mapping[str, int]
    autopilot_counts: Mapping[str, int]
    last_run_label: str
    last_run_status: str
    last_run_findings: str


def _readonly_uri(path: Path) -> str:
    """Build an SQLite file URI without exposing it to the HTTP surface."""
    resolved = path.expanduser().resolve(strict=True)
    return "file:%s?mode=ro" % quote(str(resolved), safe="/")


def open_readonly(path: Path) -> sqlite3.Connection:
    """Open an existing store with both transport- and connection-level write denial."""
    try:
        conn = sqlite3.connect(_readonly_uri(path), uri=True, timeout=2.0)
    except (OSError, sqlite3.Error) as exc:
        raise LibraryUnavailable("The research library is unavailable.") from exc
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    conn.execute("PRAGMA busy_timeout=1500")
    return conn


def safe_external_url(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    try:
        parsed = urlparse(candidate)
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    if parsed.username or parsed.password:
        return None
    return candidate


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> Sequence[Any]:
    return value if isinstance(value, list) else ()


def _literal(value: Any) -> Optional[str]:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, dict):
        direct = value.get("value")
        if isinstance(direct, str) and direct.strip():
            return direct.strip()
        source = _as_mapping(value.get("source"))
        literal = source.get("value")
        if isinstance(literal, str) and literal.strip():
            return literal.strip()
    return None


def _minutes_field(document: Mapping[str, Any], field: str) -> Optional[int]:
    entry = _as_mapping(_as_mapping(document.get("times")).get(field))
    value = entry.get("value")
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _duration_label(minutes: Optional[int]) -> Optional[str]:
    if minutes is None:
        return None
    if minutes < 60:
        return "%d min" % minutes
    hours, remainder = divmod(minutes, 60)
    return "%d hr%s" % (hours, " %d min" % remainder if remainder else "")


def _servings_label(document: Mapping[str, Any]) -> Optional[str]:
    value = _as_mapping(_as_mapping(document.get("servings")).get("value"))
    low, high = value.get("min"), value.get("max")
    if not isinstance(low, int) or isinstance(low, bool):
        return None
    if isinstance(high, int) and not isinstance(high, bool) and high != low:
        return "%d–%d servings" % (low, high)
    return "%d serving%s" % (low, "" if low == 1 else "s")


def status_projection(state: Any, completeness: Any, state_reason: Any,
                      state_set_by: Any) -> tuple[str, str, bool]:
    """Map stored state to a bounded label, explanation, and content gate."""
    if state == "approved":
        note = ("Approved by a reviewer." if isinstance(state_set_by, str) and
                state_set_by.startswith("human:") else "The stored review state is approved.")
        return "Approved", note, False
    if state == "rejected":
        if isinstance(state_set_by, str) and state_set_by.startswith("human:"):
            return "Withdrawn", "Withdrawn by a reviewer. This recipe is not an active review candidate.", True
        return "Rejected", "Rejected before review. Recipe details are not shown.", True
    if state == "deferred":
        reason = state_reason if isinstance(state_reason, str) else ""
        if reason.startswith("source_embedded_instructions_flagged"):
            note = ("On hold because the source contained instruction-like text. "
                    "Recipe details are hidden until a reviewer clears it.")
        elif reason.startswith("inference_budget_exhausted"):
            note = "On hold until extraction can run within the processing budget."
        else:
            note = "On hold pending additional review. Recipe details are not shown."
        return "On hold", note, True
    if state == "failed":
        return "Extraction failed", "Extraction did not produce a usable recipe. No recipe details are shown.", True
    if state == "pending" and completeness == "complete":
        return "Ready for review", "Source-backed fields are complete and awaiting review.", False
    if state == "pending":
        return "Missing information", "Some source details are still unknown.", False
    return "Status unavailable", "The stored review status is not recognized. Recipe details are not shown.", True


def _plain_unknown(entry: Any) -> str:
    field = str(_as_mapping(entry).get("field") or "detail")
    labels = {
        "servings": "Servings",
        "prep_time": "Prep time",
        "cook_time": "Cook time",
        "total_time": "Total time",
        "steps": "Some instructions",
    }
    if field.startswith("ingredient["):
        return "One ingredient needs clarification"
    return "%s not confirmed by the source" % labels.get(field, field.replace("_", " ").capitalize())


def _missing_details(document: Mapping[str, Any]) -> tuple[Sequence[str], Sequence[str]]:
    source_missing, extraction_issues = [], []
    for item in _as_list(document.get("unknown_fields")):
        reason = _as_mapping(item).get("reason")
        destination = source_missing if reason in SOURCE_UNSPECIFIED_REASONS else extraction_issues
        destination.append(_plain_unknown(item))
    return tuple(source_missing), tuple(extraction_issues)


AUTOPILOT_BLOCK_NOTES = {
    "no_publication": "The approval record needed by the existing Autopilot feed is missing.",
    "withdrawn": "This approval was withdrawn.",
    "not_human_published": "The approval was not recorded by a human reviewer.",
    "row_state_disagrees_with_log": "The review state and approval record do not agree.",
    "fingerprint_drift": "The approved content no longer matches its recorded fingerprint.",
    "not_current_observation": "A different source observation is now current.",
    "schema_invalid": "The approved document does not match the current recipe contract.",
    "content_not_usable": "Core cooking content is not usable under the existing feed contract.",
    "unknown_reason_out_of_contract": "A missing-field reason needs correction before feed use.",
    "has_conflicts": "Source conflicts still need resolution.",
    "support_not_in_evidence": "The source support check did not pass.",
    "non_live_evidence": "The approval is not backed by live source evidence.",
    "source_embedded_instructions_flagged": "The source contains instruction-like text requiring review.",
    "malformed_applicability": "Meal-planning applicability is incomplete.",
    "missing_rights_basis": "The approval is missing its recorded rights basis.",
    "ingredient_map_incomplete": "Ingredient applicability mapping is incomplete.",
    "equipment_not_reviewed": "Equipment needs have not completed review.",
    "applicability_slot_collision": "Another approved recipe currently occupies the same feed slot.",
}


def _autopilot_eligibility(conn: sqlite3.Connection) -> Optional[tuple[set[int], Mapping[int, str]]]:
    """Evaluate the existing feed contract without allocating a pack or writing state."""
    try:
        served, omitted = build_served_state(conn, allow_fixture_evidence=False)
        ready = {int(item["publication"]["recipe_version_id"]) for item in served["recipes"]}
        blocked = {int(item["recipe_version_id"]): str(item["reason"]) for item in omitted}
        return ready, blocked
    except (KeyError, TypeError, ValueError, sqlite3.Error):
        return None


def _autopilot_projection(version_id: int, status: str,
                          eligibility: Optional[tuple[set[int], Mapping[int, str]]]) -> tuple[str, str, str]:
    if status != "Approved":
        return "not_approved", "Not approved", "Autopilot eligibility applies only after approval."
    if eligibility is None:
        return ("not_evaluated", "Eligibility not evaluated",
                "Approved, but this view could not evaluate the existing Autopilot feed contract.")
    ready, blocked = eligibility
    if version_id in ready:
        return ("ready", "Ready for family Autopilot",
                "Passes the existing read-only recipe-pack eligibility contract.")
    reason = blocked.get(version_id)
    if reason:
        return ("blocked", "Approved · Not ready for Autopilot",
                AUTOPILOT_BLOCK_NOTES.get(reason, "An existing feed eligibility check did not pass."))
    return ("not_evaluated", "Eligibility not evaluated",
            "Approved, but no eligibility result was available for this recipe version.")


def _source_name(document: Mapping[str, Any], source_url: Optional[str]) -> str:
    evidence = _as_mapping(document.get("evidence"))
    attribution = evidence.get("attribution")
    if isinstance(attribution, str) and attribution.strip():
        name = attribution.split(";")[0].strip()
        if name.endswith(")") and " (" in name:
            base, parenthetical = name.rsplit(" (", 1)
            domain = parenthetical[:-1]
            if "." in domain and " " not in domain:
                name = base
        return name
    if source_url:
        host = urlparse(source_url).hostname or "Original source"
        return host.removeprefix("www.")
    return "Source not identified"


def _date_label(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.strftime("%b %-d, %Y")
    except (TypeError, ValueError):
        return "Date unknown"


def _card_from_row(row: sqlite3.Row,
                   eligibility: Optional[tuple[set[int], Mapping[int, str]]]) -> Optional[RecipeCard]:
    try:
        document = json.loads(row["content"])
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(document, dict):
        return None
    evidence = _as_mapping(document.get("evidence"))
    title = _literal(document.get("name")) or _literal(evidence.get("title")) or "Untitled recipe"
    source_url = safe_external_url(row["source_url"])
    status, status_note, details_hidden = status_projection(
        row["state"], row["completeness"], row["state_reason"], row["state_set_by"])
    ingredients = tuple(filter(None, (_literal(item) for item in _as_list(document.get("ingredients")))))
    steps = tuple(filter(None, (_literal(item) for item in _as_list(document.get("steps")))))
    if details_hidden:
        ingredients, steps = (), ()
    source_missing, extraction_issues = (((), ()) if details_hidden else _missing_details(document))
    total = _duration_label(_minutes_field(document, "total_time"))
    servings = _servings_label(document)
    if details_hidden:
        total, servings = None, None
        summary = status_note
    else:
        facts = ["%d source-backed ingredient%s" % (len(ingredients), "" if len(ingredients) == 1 else "s"),
                 "%d instruction%s" % (len(steps), "" if len(steps) == 1 else "s")]
        if total:
            facts.append("%s total" % total)
        summary = "The source includes %s." % ", ".join(facts)
    autopilot_status, autopilot_label, autopilot_note = _autopilot_projection(
        int(row["recipe_version_id"]), status, eligibility)
    return RecipeCard(
        recipe_id=int(row["recipe_id"]), recipe_version_id=int(row["recipe_version_id"]), title=title,
        source=_source_name(document, source_url), source_url=source_url,
        status=status, status_note=status_note, details_hidden=details_hidden, summary=summary,
        total_time=total, servings=servings, ingredient_count=len(ingredients), step_count=len(steps),
        ingredients=ingredients, steps=steps, source_missing=source_missing,
        extraction_issues=extraction_issues, autopilot_status=autopilot_status,
        autopilot_label=autopilot_label, autopilot_note=autopilot_note, created_at=row["created_at"],
        collected_label=_date_label(row["created_at"]),
    )


def _last_run(conn: sqlite3.Connection) -> tuple[str, str, str]:
    row = conn.execute(
        "SELECT started_at, finished_at, status, summary FROM runs ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return "No engine run recorded", "Unknown", "No run findings available"
    when = row["finished_at"] or row["started_at"]
    try:
        parsed = datetime.fromisoformat(when.replace("Z", "+00:00")).astimezone()
        label = parsed.strftime("%-I:%M %p · %b %-d")
    except (TypeError, ValueError):
        label = "Time unavailable"
    try:
        decoded = json.loads(row["summary"] or "{}")
    except (TypeError, json.JSONDecodeError):
        decoded = {}
    summary = decoded if isinstance(decoded, dict) else {}
    new_versions = summary.get("recipe_versions_new", 0)
    fetched = summary.get("fetched_ok", 0)
    new_versions = (new_versions if isinstance(new_versions, int) and
                    not isinstance(new_versions, bool) and new_versions >= 0 else 0)
    fetched = (fetched if isinstance(fetched, int) and
               not isinstance(fetched, bool) and fetched >= 0 else 0)
    findings = "%d recipe%s added · %d source%s checked" % (
        new_versions, "" if new_versions == 1 else "s", fetched, "" if fetched == 1 else "s")
    return label, str(row["status"]).capitalize(), findings


def read_snapshot(db_path: Path) -> LibrarySnapshot:
    """Read one short-lived, transaction-free snapshot of current recipe versions."""
    conn = open_readonly(db_path)
    try:
        eligibility = _autopilot_eligibility(conn)
        rows = conn.execute(
            """SELECT rv.recipe_id, rv.id AS recipe_version_id, rv.content, rv.completeness,
                      rv.state, rv.state_reason,
                      rv.state_set_by, rv.created_at,
                      r.source_url
               FROM recipe_versions rv
               JOIN recipes r ON r.id = rv.recipe_id
               JOIN (SELECT recipe_id, MAX(version_no) AS version_no
                       FROM recipe_versions GROUP BY recipe_id) current
                 ON current.recipe_id = rv.recipe_id AND current.version_no = rv.version_no
               ORDER BY rv.created_at DESC, rv.recipe_id DESC"""
        ).fetchall()
        cards = tuple(card for row in rows if (card := _card_from_row(row, eligibility)) is not None)
        last_label, last_status, last_findings = _last_run(conn)
    except sqlite3.Error as exc:
        raise LibraryUnavailable("The research library is unavailable.") from exc
    finally:
        conn.close()
    counts = {status: sum(card.status == status for card in cards) for status in STATUS_ORDER}
    autopilot_counts = {status: sum(card.autopilot_status == status for card in cards)
                        for status in ("ready", "blocked", "not_evaluated")}
    return LibrarySnapshot(
        recipes=cards, all_count=len(cards), sources=tuple(sorted({card.source for card in cards})),
        status_counts=counts, autopilot_counts=autopilot_counts,
        last_run_label=last_label, last_run_status=last_status,
        last_run_findings=last_findings,
    )


def filter_recipes(recipes: Iterable[RecipeCard], query: str = "", source: str = "",
                   status: str = "", sort: str = "newest") -> List[RecipeCard]:
    needle = query.casefold().strip()
    selected = [card for card in recipes
                if (not needle or needle in " ".join((card.title, card.source, *card.ingredients)).casefold())
                and (not source or card.source == source)
                and (not status or card.status == status)]
    if sort == "title":
        selected.sort(key=lambda card: card.title.casefold())
    else:
        selected.sort(key=lambda card: (card.created_at, card.recipe_id), reverse=True)
    return selected


def esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _shell(body: str, title: str = "Research Library", current: str = "library") -> str:
    library_class = ' class="active" aria-current="page"' if current == "library" else ""
    approved_class = ' class="active" aria-current="page"' if current == "approved" else ""
    return """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>%s · WellNest</title><link rel="stylesheet" href="/assets/library.css"></head>
<body><header class="site-header"><a class="brand" href="/" aria-label="WellNest Research Library home">
<span class="brand-mark" aria-hidden="true">W</span><span><strong>WellNest</strong><small>Research Library</small></span></a>
<nav aria-label="Research Library views"><a%s href="/">Findings</a><a%s href="/approved">Approved &amp; Autopilot</a></nav>
<span class="local-pill"><i></i> Local &amp; read-only</span></header>
%s
<footer><span>WellNest Research</span><span>Actual findings · no edits from this library</span></footer>
<script src="/assets/library.js" defer></script></body></html>""" % (
        esc(title), library_class, approved_class, body)


def _option(value: str, selected: str, label: Optional[str] = None) -> str:
    return '<option value="%s"%s>%s</option>' % (
        esc(value), ' selected' if value == selected else "", esc(label or value))


def render_index(snapshot: LibrarySnapshot, params: Mapping[str, str]) -> str:
    query, source, status = params.get("q", ""), params.get("source", ""), params.get("status", "")
    sort = params.get("sort", "newest")
    cards = filter_recipes(snapshot.recipes, query, source, status, sort)
    source_options = _option("", source, "All sources") + "".join(_option(x, source) for x in snapshot.sources)
    status_options = _option("", status, "All statuses") + "".join(_option(x, status) for x in STATUS_ORDER)
    card_markup = "".join(_render_card(card) for card in cards)
    if not cards:
        card_markup = '<section class="empty"><span>⌕</span><h2>No recipes match</h2><p>Try a broader search or clear a filter.</p><a href="/">Clear filters</a></section>'
    body = """<main>
<section class="hero"><div><p class="eyebrow">A calm place for fresh findings</p><h1>Recipes worth a closer look.</h1>
<p class="lede">Browse what the research engine has actually found, with source details and missing information shown honestly.</p></div>
<aside class="run-card"><div class="run-icon">↻</div><div><small>Last engine run</small><strong>%s</strong><span>%s · %s</span></div></aside></section>
<section class="stats" aria-label="Library summary"><div><strong>%d</strong><span>Current recipes</span></div><div><strong>%d</strong><span>Ready for review</span></div><div><strong>%d</strong><span>Need information</span></div><div><strong>%d</strong><span>Approved</span></div></section>
<form class="filters" method="get" action="/" data-filter-form><label class="search"><span>⌕</span><input name="q" value="%s" placeholder="Search recipes or ingredients" aria-label="Search recipes"></label>
<label><span>Source</span><select name="source">%s</select></label><label><span>Status</span><select name="status">%s</select></label>
<label><span>Sort</span><select name="sort">%s%s</select></label><button type="submit">Search</button></form>
<div class="results-heading"><div><p class="eyebrow">Current collection</p><h2>%d recipe%s</h2></div>%s</div>
<section class="recipe-grid">%s</section></main>""" % (
        esc(snapshot.last_run_label), esc(snapshot.last_run_status), esc(snapshot.last_run_findings),
        snapshot.all_count, snapshot.status_counts["Ready for review"], snapshot.status_counts["Missing information"],
        snapshot.status_counts["Approved"], esc(query), source_options, status_options,
        _option("newest", sort, "Newest first"), _option("title", sort, "A–Z"), len(cards),
        "" if len(cards) == 1 else "s", '<a class="clear" href="/">Clear filters</a>' if any((query, source, status, sort != "newest")) else "", card_markup)
    return _shell(body)


def _render_card(card: RecipeCard) -> str:
    meta = [item for item in (card.total_time, card.servings) if item]
    meta.append("%d step%s" % (card.step_count, "" if card.step_count == 1 else "s"))
    if card.source_missing:
        meta.append("Source doesn’t specify: %d" % len(card.source_missing))
    if card.extraction_issues:
        meta.append("Extraction correction: %d" % len(card.extraction_issues))
    cls = {"Ready for review": "ready", "Approved": "approved", "On hold": "hold",
           "Withdrawn": "withdrawn", "Rejected": "withdrawn",
           "Extraction failed": "failed", "Status unavailable": "failed"}.get(card.status, "missing")
    autopilot = (('<div class="autopilot %s"><strong>%s</strong><span>%s</span></div>' %
                  (esc(card.autopilot_status), esc(card.autopilot_label), esc(card.autopilot_note)))
                 if card.status == "Approved" else "")
    return """<article class="recipe-card"><div class="card-top"><span class="status %s"><i></i>%s</span><span class="date">%s</span></div>
<p class="source">%s</p><h3><a href="/recipe/%d">%s</a></h3><p class="summary">%s</p>
%s<div class="meta">%s</div><a class="view-link" href="/recipe/%d">View recipe <span>→</span></a></article>""" % (
        cls, esc(card.status), esc(card.collected_label), esc(card.source), card.recipe_id, esc(card.title),
        esc(card.summary), autopilot, "".join("<span>%s</span>" % esc(item) for item in meta), card.recipe_id)


def render_approved(snapshot: LibrarySnapshot) -> str:
    approved = [card for card in snapshot.recipes if card.status == "Approved"]
    groups = (
        ("ready", "Ready for family Autopilot", "Approved recipes that pass the existing recipe-pack contract."),
        ("blocked", "Approved, with feed work remaining", "Approved recipes blocked by a specific existing feed check."),
        ("not_evaluated", "Eligibility not evaluated", "Approved recipes whose feed eligibility could not be evaluated here."),
    )
    sections = []
    for key, heading, description in groups:
        cards = [card for card in approved if card.autopilot_status == key]
        sections.append('<section class="approved-group"><div class="results-heading"><div><p class="eyebrow">%d recipe%s</p><h2>%s</h2><p>%s</p></div></div><div class="recipe-grid">%s</div></section>' % (
            len(cards), "" if len(cards) == 1 else "s", esc(heading), esc(description),
            "".join(_render_card(card) for card in cards) or '<div class="group-empty">None currently.</div>'))
    body = """<main><section class="hero approved-hero"><div><p class="eyebrow">Approved recipes</p>
<h1>What’s ready for family Autopilot.</h1><p class="lede">Approval and feed readiness are separate. This view applies the existing recipe-pack contract read-only and keeps approved-but-blocked recipes visible without changing them.</p></div></section>
<section class="stats approved-stats" aria-label="Approved recipe readiness"><div><strong>%d</strong><span>Approved recipes</span></div><div><strong>%d</strong><span>Autopilot ready</span></div><div><strong>%d</strong><span>Approved, blocked</span></div><div><strong>%d</strong><span>Not evaluated</span></div></section>
%s</main>""" % (len(approved), snapshot.autopilot_counts["ready"],
                   snapshot.autopilot_counts["blocked"], snapshot.autopilot_counts["not_evaluated"],
                   "".join(sections))
    return _shell(body, "Approved & Autopilot", current="approved")


def render_detail(card: RecipeCard) -> str:
    cls = {"Ready for review": "ready", "Approved": "approved", "On hold": "hold",
           "Withdrawn": "withdrawn", "Rejected": "withdrawn",
           "Extraction failed": "failed", "Status unavailable": "failed"}.get(card.status, "missing")
    source_link = ('<a class="source-button" href="%s" target="_blank" rel="noopener noreferrer">Visit original source <span>↗</span></a>' % esc(card.source_url)) if card.source_url else '<span class="source-unavailable">Original source link unavailable</span>'
    autopilot = (('<div class="autopilot %s"><strong>%s</strong><span>%s</span></div>' %
                  (esc(card.autopilot_status), esc(card.autopilot_label), esc(card.autopilot_note)))
                 if card.status == "Approved" else "")
    facts = []
    fact_values = (("Total time", "Not shown"), ("Serves", "Not shown"),
                   ("Ingredients", "Not shown"), ("Steps", "Not shown")) if card.details_hidden else (
        ("Total time", card.total_time), ("Serves", card.servings),
        ("Ingredients", str(card.ingredient_count)), ("Steps", str(card.step_count)))
    for label, value in fact_values:
        facts.append('<div><small>%s</small><strong>%s</strong></div>' % (esc(label), esc(value or "Unknown")))
    ingredients = "".join("<li>%s</li>" % esc(item) for item in card.ingredients) or "<li>Ingredients are not available from the source.</li>"
    steps = "".join("<li>%s</li>" % esc(item) for item in card.steps) or "<li>Instructions are not available from the source.</li>"
    unknowns = ""
    if card.source_missing:
        unknowns += ('<aside class="unknowns source-missing"><h2>Source doesn’t specify</h2>'
                     '<p>These details are not stated by the source. Their absence does not by itself make the recipe unusable.</p><ul>%s</ul></aside>' %
                     "".join("<li>%s</li>" % esc(item) for item in card.source_missing))
    if card.extraction_issues:
        unknowns += ('<aside class="unknowns extraction-issues"><h2>Extraction needs correction</h2>'
                     '<p>The source may contain these details, but the current extraction did not resolve them reliably.</p><ul>%s</ul></aside>' %
                     "".join("<li>%s</li>" % esc(item) for item in card.extraction_issues))
    recipe_body = ('<section class="unavailable"><p class="eyebrow">Recipe details withheld</p><h2>%s</h2><p>%s</p></section>' %
                   (esc(card.status), esc(card.status_note))) if card.details_hidden else (
        '<section class="recipe-body"><div><p class="eyebrow">What you’ll need</p><h2>Ingredients</h2><ul class="ingredients">%s</ul></div>'
        '<div><p class="eyebrow">From the source</p><h2>Instructions</h2><ol class="steps">%s</ol></div></section>' %
        (ingredients, steps))
    body = """<main class="detail"><a class="back" href="/">← Back to library</a><section class="detail-hero"><div><div class="detail-kicker"><span class="status %s"><i></i>%s</span><span>%s</span></div><p class="source">%s</p><h1>%s</h1><p class="lede">%s</p>%s%s</div>
<aside class="fact-card">%s</aside></section>%s
%s</main>""" % (
        cls, esc(card.status), esc(card.collected_label), esc(card.source), esc(card.title), esc(card.summary),
        autopilot, source_link,
        "".join(facts), unknowns, recipe_body)
    return _shell(body, card.title)


def render_error(title: str, message: str, status: int) -> str:
    return _shell('<main class="error"><p class="eyebrow">%d</p><h1>%s</h1><p>%s</p><a href="/">Return to the library</a></main>' % (status, esc(title), esc(message)), title)


def make_handler(db_path: Path):
    class LibraryHandler(BaseHTTPRequestHandler):
        server_version = "WellNestLibrary/1"

        def _send(self, content: bytes, content_type: str, status: int = 200) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.end_headers()
            self.wfile.write(content)

        def _html(self, page: str, status: int = 200) -> None:
            self._send(page.encode("utf-8"), "text/html; charset=utf-8", status)

        def _valid_host(self) -> bool:
            raw = self.headers.get("Host", "")
            if not raw or raw != raw.strip():
                return False
            try:
                parsed = urlparse("http://" + raw)
                request_port = parsed.port
            except ValueError:
                return False
            return (parsed.hostname == "127.0.0.1" and parsed.username is None and
                    parsed.password is None and parsed.path == "" and not parsed.query and
                    not parsed.fragment and request_port in (None, self.server.server_port))

        def _reject_unexpected_host(self) -> bool:
            if self._valid_host():
                return False
            self._html(render_error("Request rejected", "This local library accepts only loopback requests.", 421), 421)
            return True

        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            if self._reject_unexpected_host():
                return
            parsed = urlparse(self.path)
            if parsed.path.startswith("/assets/"):
                name = parsed.path.removeprefix("/assets/")
                if name not in ("library.css", "library.js"):
                    self._html(render_error("Not found", "That page does not exist.", 404), 404)
                    return
                asset = ASSET_DIR / name
                mime = "text/css; charset=utf-8" if name.endswith(".css") else "text/javascript; charset=utf-8"
                self._send(asset.read_bytes(), mime)
                return
            try:
                snapshot = read_snapshot(db_path)
            except LibraryUnavailable:
                self._html(render_error("Library unavailable", "The current research findings could not be read safely.", 503), 503)
                return
            if parsed.path == "/":
                raw = parse_qs(parsed.query, keep_blank_values=True)
                params = {key: values[0][:200] for key, values in raw.items() if values}
                self._html(render_index(snapshot, params))
                return
            if parsed.path == "/approved":
                self._html(render_approved(snapshot))
                return
            if parsed.path.startswith("/recipe/"):
                try:
                    recipe_id = int(unquote(parsed.path.removeprefix("/recipe/")))
                except ValueError:
                    recipe_id = -1
                card = next((item for item in snapshot.recipes if item.recipe_id == recipe_id), None)
                if card:
                    self._html(render_detail(card))
                else:
                    self._html(render_error("Recipe not found", "That recipe is not in the current collection.", 404), 404)
                return
            self._html(render_error("Not found", "That page does not exist.", 404), 404)

        def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            if self._reject_unexpected_host():
                return
            self._html(render_error("Read-only library", "This library does not accept changes.", 405), 405)

        def log_message(self, fmt: str, *args: Any) -> None:
            # Avoid request logs containing local query text or filesystem context.
            return

    return LibraryHandler


def serve(db_path: Path, host: str = "127.0.0.1", port: int = 8765) -> None:
    if host not in ALLOWED_BIND_HOSTS:
        raise ValueError("Research Library may bind only to a loopback address")
    snapshot = read_snapshot(db_path)
    server = ThreadingHTTPServer((host, port), make_handler(db_path))
    address = "[%s]" % host if ":" in host else host
    print("WellNest Research Library: http://%s:%d/ (%d current recipes)" % (address, server.server_port, snapshot.all_count), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Serve the local read-only WellNest Research Library")
    parser.add_argument("--db", type=Path, required=True, help="existing WellNest research SQLite file")
    parser.add_argument("--host", default="127.0.0.1", choices=sorted(ALLOWED_BIND_HOSTS))
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    serve(args.db, args.host, args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
