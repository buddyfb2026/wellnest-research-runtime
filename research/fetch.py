"""Bounded retrieval. Only allowlisted URLs are ever requested.

The transport is injectable so tests never touch the network. URLs found *inside*
retrieved content are never followed: content is data, not a crawl frontier.
"""
import re
import urllib.error
import urllib.request
import urllib.robotparser
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Dict, Optional, Tuple
from urllib.parse import urlsplit, urlunsplit

Transport = Callable[[str, str, int, int], Tuple[int, str, Dict[str, str], bytes]]


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def urllib_transport(url: str, user_agent: str, timeout: int, max_bytes: int):
    req = urllib.request.Request(url, headers={"User-Agent": user_agent, "Accept": "text/html,*/*;q=0.5"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read(max_bytes + 1)
            headers = {k.lower(): v for k, v in resp.headers.items()}
            return resp.status, resp.geturl(), headers, body[:max_bytes]
    except urllib.error.HTTPError as e:
        try:
            body = e.read(max_bytes)
        except Exception:
            body = b""
        return e.code, e.geturl() or url, {k.lower(): v for k, v in (e.headers or {}).items()}, body


@dataclass
class FetchResult:
    url: str
    outcome: str                      # ok | blocked | error
    attempted_at: str
    http_status: Optional[int] = None
    final_url: Optional[str] = None
    robots_status: str = "not_checked"
    reason: Optional[str] = None
    html: Optional[str] = None
    headers: Dict[str, str] = field(default_factory=dict)


LOGIN_PATH_RE = re.compile(r"/(accounts/)?(login|signin|sign-in|auth)(/|\?|$)", re.I)
PAYWALL_MARKERS = ("subscribe to continue", "subscription required", "to continue reading")


class Fetcher:
    def __init__(self, transport: Transport = urllib_transport, user_agent: str = "WellNestResearch/0.1",
                 timeout: int = 20, max_bytes: int = 2_000_000, check_robots: bool = True):
        self.transport = transport
        self.user_agent = user_agent
        self.timeout = timeout
        self.max_bytes = max_bytes
        self.check_robots = check_robots
        self._robots: Dict[str, Tuple[str, Optional[urllib.robotparser.RobotFileParser]]] = {}
        self.requests_made = 0          # source URL requests
        self.robots_requests = 0        # robots.txt requests (accounted separately)

    def _robots_for(self, url: str) -> Tuple[str, Optional[urllib.robotparser.RobotFileParser]]:
        parts = urlsplit(url)
        origin = urlunsplit((parts.scheme, parts.netloc, "", "", ""))
        if origin in self._robots:
            return self._robots[origin]
        robots_url = origin + "/robots.txt"
        self.robots_requests += 1
        try:
            status, _, _, body = self.transport(robots_url, self.user_agent, self.timeout, 200_000)
        except Exception as e:  # network failure
            self._robots[origin] = ("unreachable:%s" % type(e).__name__, None)
            return self._robots[origin]
        if status != 200:
            self._robots[origin] = ("unreachable:http_%s" % status, None)
            return self._robots[origin]
        rp = urllib.robotparser.RobotFileParser()
        rp.parse(body.decode("utf-8", "replace").splitlines())
        self._robots[origin] = ("fetched", rp)
        return self._robots[origin]

    def fetch(self, url: str) -> FetchResult:
        attempted_at = now_iso()
        robots_status = "not_checked"
        if self.check_robots:
            state, rp = self._robots_for(url)
            if rp is None:
                robots_status = state  # unreachable: recorded, not treated as permission
            elif rp.can_fetch(self.user_agent, url) and rp.can_fetch("*", url):
                robots_status = "allowed"
            else:
                return FetchResult(url, "blocked", attempted_at, robots_status="disallowed",
                                   reason="robots.txt disallows this path for our agent")
        self.requests_made += 1
        try:
            status, final_url, headers, body = self.transport(url, self.user_agent, self.timeout, self.max_bytes)
        except Exception as e:
            return FetchResult(url, "error", attempted_at, robots_status=robots_status,
                               reason="transport error: %s: %s" % (type(e).__name__, e))
        html = body.decode("utf-8", "replace")
        if status in (401, 403):
            return FetchResult(url, "blocked", attempted_at, status, final_url, robots_status,
                               "http %d: access denied / login required" % status, None, headers)
        if status == 404:
            return FetchResult(url, "error", attempted_at, status, final_url, robots_status,
                               "http 404: not found", None, headers)
        if status >= 400:
            return FetchResult(url, "error", attempted_at, status, final_url, robots_status,
                               "http %d" % status, None, headers)
        if final_url and LOGIN_PATH_RE.search(urlsplit(final_url).path) and not LOGIN_PATH_RE.search(urlsplit(url).path):
            return FetchResult(url, "blocked", attempted_at, status, final_url, robots_status,
                               "redirected to a login page", None, headers)
        lower = html.lower()
        if 'type="password"' in lower and len(re.sub(r"<[^>]+>", " ", html).split()) < 400:
            return FetchResult(url, "blocked", attempted_at, status, final_url, robots_status,
                               "login wall: password form with no article body", None, headers)
        if any(m in lower for m in PAYWALL_MARKERS) and len(re.sub(r"<[^>]+>", " ", html).split()) < 400:
            return FetchResult(url, "blocked", attempted_at, status, final_url, robots_status,
                               "paywall marker with no article body", None, headers)
        ctype = headers.get("content-type", "")
        if ctype and "html" not in ctype and "text" not in ctype:
            return FetchResult(url, "error", attempted_at, status, final_url, robots_status,
                               "unsupported content-type: %s" % ctype, None, headers)
        return FetchResult(url, "ok", attempted_at, status, final_url, robots_status, None, html, headers)
