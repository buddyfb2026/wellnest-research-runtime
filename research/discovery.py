"""Beyond-seed discovery through an explicitly declared route (WEL-41 AC4).

Three distinct steps, persisted separately:

  1. hint        — a same-origin link found on a *declared* discovery route page (an allowlist entry
                   with `"role": "discovery_route"`, e.g. a publisher's public section index). Stored
                   in `source_hints` with fetch_permitted=0 and provenance. Links inside ordinary
                   article evidence, model output or embedded instructions are never hints.
  2. assessment  — the same request-boundary gate the fetcher applies (http(s), not private, same
                   origin as the route, not a login path, robots allows). At most
                   MAX_DISCOVERY_ASSESSMENTS_PER_CYCLE per cycle; only robots.txt may be requested.
  3. collection  — a hint assessed `permitted` becomes a scheduled source (due now) and is fetched
                   by a later cycle like any other permitted source, under the same caps.

Bounded: at most MAX_DISCOVERY_HINTS_PER_ROUTE hints stored per route page, no recursion (hints
are never themselves routes), and a denied hint causes zero content requests.
"""
import json
import sqlite3
from html.parser import HTMLParser
from typing import Any, Dict, List, Tuple
from urllib.parse import urljoin, urlsplit, urlunsplit

from .fetch import LOGIN_PATH_RE, Fetcher, _origin
from . import source_registry as registry


class _LinkParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hrefs: List[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.hrefs.append(href)


def _route_prefix(route_url: str) -> str:
    path = urlsplit(route_url).path
    return path if path.endswith("/") else path.rsplit("/", 1)[0] + "/"


def extract_hints(route_url: str, html: str, max_hints: int, known_urls=None) -> List[str]:
    """At most max_hints new same-origin links; previously seen links do not consume slots."""
    p = _LinkParser()
    try:
        p.feed(html or "")
    except Exception:
        pass
    prefix = _route_prefix(route_url)
    origin = _origin(route_url)
    seen, out = set(), []
    known_urls = known_urls or set()
    for href in p.hrefs:
        abs_url = urljoin(route_url, href.strip())
        parts = urlsplit(abs_url)
        if parts.scheme.lower() not in ("http", "https") or _origin(abs_url) != origin:
            continue
        clean = urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, "", ""))
        if not parts.path.startswith(prefix) or clean.rstrip("/") == route_url.rstrip("/"):
            continue
        if LOGIN_PATH_RE.search(parts.path):
            continue
        if clean in seen or clean in known_urls:
            continue
        seen.add(clean)
        out.append(clean)
        if len(out) >= max_hints:
            break
    return out


def record_hint(conn: sqlite3.Connection, url: str, route: Dict[str, Any], now_iso: str) -> bool:
    """Insert a discovered hint (fetch_permitted=0). Returns True if new. Never overwrites an
    existing assessment or an allowlist entry."""
    if conn.execute("SELECT 1 FROM source_hints WHERE url=?", (url,)).fetchone():
        conn.execute("UPDATE source_hints SET last_seen_at=? WHERE url=?", (now_iso, url))
        return False
    conn.execute(
        """INSERT INTO source_hints(url, source_type, attribution, access_basis, fetch_permitted, usage_constraints,
               discovery_origin, notes, first_seen_at, last_seen_at, discovered_at, discovery_route)
           VALUES(?,?,?,?,0,?,?,?,?,?,?,?)""",
        (url, route["source_type"], route.get("attribution"), "unassessed: found on discovery route %s" % route["url"],
         route.get("usage_constraints"), "route:%s" % route["url"], "discovered link; not collected until assessed",
         now_iso, now_iso, now_iso, route["url"]),
    )
    return True


def unassessed_hints(conn: sqlite3.Connection, limit: int) -> List[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM source_hints WHERE discovery_route IS NOT NULL AND access_assessment IS NULL "
        "ORDER BY discovered_at, url LIMIT ?", (int(limit),)).fetchall()


def assess(conn: sqlite3.Connection, fetcher: Fetcher, hint: sqlite3.Row, now_iso: str) -> Tuple[bool, str]:
    """Record the access assessment. Permitted hints inherit the route's access basis and become
    fetchable; denied ones stay hints. No content request is made here."""
    route_url = hint["discovery_route"]
    denied = registry.effective_denied(conn, hint["url"])
    if denied:
        ok, robots_status, why = False, "not_checked", denied
    else:
        ok, robots_status, why = fetcher.permit(hint["url"], route_url)
    assessment = {"status": "permitted" if ok else "denied", "reason": why or "same origin as declared route; robots allows",
                  "robots_status": robots_status, "checked_at": now_iso, "route": route_url}
    if ok:
        route = conn.execute("SELECT access_basis FROM source_hints WHERE url=?", (route_url,)).fetchone()
        basis = "%s; inherited from discovery route %s" % (route["access_basis"] if route else "public_web_robots_checked", route_url)
        conn.execute("UPDATE source_hints SET access_assessment=?, fetch_permitted=1, access_basis=?, "
                     "notes='discovered and assessed permitted; collected on schedule' WHERE url=?",
                     (json.dumps(assessment), basis, hint["url"]))
    else:
        conn.execute("UPDATE source_hints SET access_assessment=?, fetch_permitted=0 WHERE url=?",
                     (json.dumps(assessment), hint["url"]))
    return ok, assessment["reason"]


def permitted_discovered(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    """Discovered hints that passed assessment, shaped like allowlist entries."""
    rows = conn.execute(
        "SELECT * FROM source_hints WHERE discovery_route IS NOT NULL AND fetch_permitted=1 ORDER BY discovered_at, url").fetchall()
    return [{"url": r["url"], "source_type": r["source_type"], "attribution": r["attribution"],
             "access_basis": r["access_basis"], "fetch": True, "usage_constraints": r["usage_constraints"],
             "discovery_origin": r["discovery_origin"], "discovered": True} for r in rows]
