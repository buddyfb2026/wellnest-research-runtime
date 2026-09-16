"""Bounded retrieval. Only allowlisted URLs are ever requested.

The transport is injectable so tests never touch the network. The transport must NOT
follow redirects: every hop is checked here before it is requested. URLs found *inside*
retrieved content are never followed: content is data, not a crawl frontier.
"""
import ipaddress
import re
import urllib.error
import urllib.request
import urllib.robotparser
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Callable, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlsplit, urlunsplit

Transport = Callable[[str, str, int, int], Tuple[int, str, Dict[str, str], bytes]]
MAX_REDIRECTS = 3


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # surface 3xx as HTTPError; Fetcher decides whether the hop is permitted


_OPENER = urllib.request.build_opener(_NoRedirect)


def urllib_transport(url: str, user_agent: str, timeout: int, max_bytes: int):
    req = urllib.request.Request(url, headers={"User-Agent": user_agent, "Accept": "text/html,*/*;q=0.5"})
    try:
        with _OPENER.open(req, timeout=timeout) as resp:
            body = resp.read(max_bytes + 1)
            headers = {k.lower(): v for k, v in resp.headers.items()}
            return resp.status, resp.geturl(), headers, body[:max_bytes]
    except urllib.error.HTTPError as e:
        try:
            body = e.read(max_bytes)
        except Exception:
            body = b""
        return e.code, url, {k.lower(): v for k, v in (e.headers or {}).items()}, body


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
    hops: List[str] = field(default_factory=list)
    received_at: Optional[str] = None
    retry_after_deadline: Optional[datetime] = None
    retry_after_error: Optional[str] = None


def parse_retry_after(raw: Optional[str], received_at: datetime):
    """Return (deadline, unrepresentable reason). Malformed/past values use normal backoff."""
    if not isinstance(raw, str) or not raw.strip():
        return None, None
    value = raw.strip()
    try:
        if re.fullmatch(r"[0-9]+", value):
            deadline = received_at + timedelta(seconds=int(value))
        else:
            # An HTTP-date has a four-digit year. Detect oversized years before the parser
            # rejects them as merely malformed, so an explicit unreachable date cannot shorten.
            if re.search(r"[A-Za-z]{3}\s+[0-9]{5,}\s+[0-9]{2}:[0-9]{2}:[0-9]{2}", value):
                raise OverflowError('HTTP-date year beyond datetime range')
            deadline = parsedate_to_datetime(value)
            if deadline.tzinfo is None:
                deadline = deadline.replace(tzinfo=timezone.utc)
            deadline = deadline.astimezone(timezone.utc)
        return (deadline, None) if deadline > received_at else (None, None)
    except (OverflowError, ArithmeticError):
        return None, 'Retry-After deadline unrepresentable: %s; manual review required' % raw
    except (ValueError, TypeError):
        # Very long numeric tokens can exceed Python's integer conversion safety bound.
        if re.fullmatch(r"[0-9]+", value):
            return None, 'Retry-After deadline unrepresentable: %s; manual review required' % raw
        return None, None


LOGIN_PATH_RE = re.compile(r"/(accounts/)?(login|signin|sign-in|auth)(/|\?|$)", re.I)
PAYWALL_MARKERS = ("subscribe to continue", "subscription required", "to continue reading")


def _origin(url: str) -> str:
    p = urlsplit(url)
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), "", "", ""))


def _is_private_host(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    if host in ("localhost", "") or host.endswith(".localhost") or host.endswith(".local"):
        return True
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
    except ValueError:
        return False


def _word_count(html: str) -> int:
    return len(re.sub(r"<[^>]+>", " ", html).split())


class Fetcher:
    def __init__(self, transport: Transport = urllib_transport, user_agent: str = "WellNestResearch/0.1",
                 timeout: int = 20, max_bytes: int = 2_000_000, check_robots: bool = True,
                 clock: Optional[Callable[[], datetime]] = None, *,
                 deny_fn: Optional[Callable[[str], Optional[str]]] = None):
        self.deny_fn = deny_fn or (lambda url: None)
        self.transport = transport
        self.user_agent = user_agent
        self.timeout = timeout
        self.max_bytes = max_bytes
        self.check_robots = check_robots
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._robots: Dict[str, Tuple[str, Optional[urllib.robotparser.RobotFileParser]]] = {}
        self.requests_made = 0          # source URL requests (every hop counts)
        self.robots_requests = 0        # robots.txt requests (accounted separately)

    def _robots_for(self, url: str) -> Tuple[str, Optional[urllib.robotparser.RobotFileParser]]:
        origin = _origin(url)
        if origin in self._robots:
            return self._robots[origin]
        robots_url = origin + "/robots.txt"
        self.robots_requests += 1
        try:
            status, _, _, body = self.transport(robots_url, self.user_agent, self.timeout, 200_000)
        except Exception as e:  # network failure: the access check is unavailable, not passed
            self._robots[origin] = ("unavailable:%s" % type(e).__name__, None)
            return self._robots[origin]
        rp = urllib.robotparser.RobotFileParser()
        if status == 200:
            rp.parse(body.decode("utf-8", "replace").splitlines())
            self._robots[origin] = ("fetched", rp)
        elif 400 <= status < 500:
            rp.parse([])  # RFC 9309: no robots file means unrestricted
            self._robots[origin] = ("absent:http_%d" % status, rp)
        else:
            self._robots[origin] = ("unavailable:http_%d" % status, None)
        return self._robots[origin]

    def _permit(self, url: str, allowlisted: str) -> Tuple[bool, str, str]:
        """(permitted, robots_status, reason). The only gate before a request is made."""
        if urlsplit(url).scheme.lower() not in ("http", "https"):
            return False, "not_checked", "non-http destination refused: %s" % url
        if _is_private_host(url):
            return False, "not_checked", "loopback/private destination refused: %s" % url
        if _origin(url) != _origin(allowlisted):
            return False, "not_checked", "destination origin %s is not the allowlisted origin" % _origin(url)
        if LOGIN_PATH_RE.search(urlsplit(url).path) and not LOGIN_PATH_RE.search(urlsplit(allowlisted).path):
            return False, "not_checked", "destination is a login page: %s" % url
        if not self.check_robots:
            return True, "not_checked", ""
        state, rp = self._robots_for(url)
        if rp is None:
            return False, state, "robots.txt %s: required access check unavailable, not fetching" % state
        if rp.can_fetch(self.user_agent, url) and rp.can_fetch("*", url):
            return True, "allowed" if state == "fetched" else "allowed_no_robots", ""
        return False, "disallowed", "robots.txt disallows this path for our agent"

    def permit(self, url: str, allowlisted: str) -> Tuple[bool, str, str]:
        """Access assessment without a content request: at most one robots.txt request per origin.
        Used by discovery to assess a hint before it may ever be collected."""
        reason = self.deny_fn(url)
        return (False, "not_checked", reason) if reason else self._permit(url, allowlisted)

    def fetch(self, url: str) -> FetchResult:
        attempted_at = self.clock().astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        current, hops = url, []
        robots_status = "not_checked"
        for hop in range(MAX_REDIRECTS + 1):
            denied = self.deny_fn(current)
            if denied:
                return FetchResult(url, "blocked", attempted_at, reason="%s at hop %d" % (denied, hop + 1), hops=hops)
            ok, robots_status, why = self._permit(current, url)
            if not ok:
                return FetchResult(url, "blocked", attempted_at, robots_status=robots_status, reason=why, hops=hops)
            self.requests_made += 1
            hops.append(current)
            try:
                status, final_url, headers, body = self.transport(current, self.user_agent, self.timeout, self.max_bytes)
            except Exception as e:
                return FetchResult(url, "error", attempted_at, robots_status=robots_status, hops=hops,
                                   reason="transport error: %s: %s" % (type(e).__name__, e))
            received = self.clock().astimezone(timezone.utc)
            if 300 <= status < 400:
                loc = headers.get("location")
                if not loc:
                    return FetchResult(url, "error", attempted_at, status, current, robots_status,
                                       "http %d without Location" % status, None, headers, hops)
                current = urljoin(current, loc)
                continue
            result = self._classify(url, current, status, headers, body, attempted_at, robots_status, hops)
            result.received_at = received.strftime("%Y-%m-%dT%H:%M:%SZ")
            raw_retry = next((v for k, v in headers.items() if k.lower() == "retry-after"), None)
            result.retry_after_deadline, result.retry_after_error = parse_retry_after(raw_retry, received)
            return result
        return FetchResult(url, "blocked", attempted_at, robots_status=robots_status, hops=hops,
                           reason="more than %d redirects" % MAX_REDIRECTS)

    @staticmethod
    def _classify(url, final_url, status, headers, body, attempted_at, robots_status, hops) -> FetchResult:
        html = body.decode("utf-8", "replace")
        if status in (401, 403):
            return FetchResult(url, "blocked", attempted_at, status, final_url, robots_status,
                               "http %d: access denied / login required" % status, None, headers, hops)
        if status == 404:
            return FetchResult(url, "error", attempted_at, status, final_url, robots_status,
                               "http 404: not found", None, headers, hops)
        if status >= 400:
            return FetchResult(url, "error", attempted_at, status, final_url, robots_status,
                               "http %d" % status, None, headers, hops)
        lower = html.lower()
        if 'type="password"' in lower and _word_count(html) < 400:
            return FetchResult(url, "blocked", attempted_at, status, final_url, robots_status,
                               "login wall: password form with no article body", None, headers, hops)
        if any(m in lower for m in PAYWALL_MARKERS) and _word_count(html) < 400:
            return FetchResult(url, "blocked", attempted_at, status, final_url, robots_status,
                               "paywall marker with no article body", None, headers, hops)
        ctype = headers.get("content-type", "")
        if ctype and "html" not in ctype and "text" not in ctype:
            return FetchResult(url, "error", attempted_at, status, final_url, robots_status,
                               "unsupported content-type: %s" % ctype, None, headers, hops)
        return FetchResult(url, "ok", attempted_at, status, final_url, robots_status, None, html, headers, hops)
