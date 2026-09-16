"""HTML → text, title, dates, excerpt, and an untrusted-instruction scan.

Nothing here executes or follows anything found in the page.
"""
import hashlib
import json
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import List, Optional, Tuple

SKIP_TAGS = {"script", "style", "noscript", "svg", "nav", "header", "footer", "aside", "form", "iframe", "template"}
BLOCK_TAGS = {"p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "br", "tr", "section", "article", "blockquote", "dd", "dt"}


class _TextParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: List[str] = []
        self.title_parts: List[str] = []
        self.metas: List[Tuple[str, str]] = []
        self.jsonld: List[str] = []
        self._skip = 0
        self._in_title = False
        self._title_done = False   # only the document <title>, never SVG <title> elements
        self._in_jsonld = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "meta":
            key = a.get("property") or a.get("name") or a.get("itemprop")
            if key and a.get("content"):
                self.metas.append((key.lower(), a["content"]))
            return
        if tag == "script" and (a.get("type") or "").lower() == "application/ld+json":
            self._in_jsonld = True
            return
        if tag in SKIP_TAGS:
            self._skip += 1
        if tag == "title" and not self._title_done:
            self._in_title = True
        if tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag == "script" and self._in_jsonld:
            self._in_jsonld = False
            return
        if tag in SKIP_TAGS and self._skip:
            self._skip -= 1
        if tag == "title" and self._in_title:
            self._in_title = False
            self._title_done = True
        if tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._in_jsonld:
            self.jsonld.append(data)
            return
        if self._in_title:
            self.title_parts.append(data)
        if not self._skip:
            self.parts.append(data)


@dataclass
class Extracted:
    title: Optional[str]
    text: str
    excerpt: str
    content_hash: str
    published_at: Optional[str]
    published_at_basis: str
    modified_at: Optional[str]
    injection_flags: List[str] = field(default_factory=list)
    locators: dict = field(default_factory=dict)


def _normalize(text: str) -> str:
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return "\n".join(line.strip() for line in text.split("\n")).strip()


def _find_jsonld_dates(blobs: List[str]) -> Tuple[Optional[str], Optional[str]]:
    pub = mod = None

    def walk(o):
        nonlocal pub, mod
        if isinstance(o, dict):
            if pub is None and isinstance(o.get("datePublished"), str):
                pub = o["datePublished"]
            if mod is None and isinstance(o.get("dateModified"), str):
                mod = o["dateModified"]
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    for b in blobs:
        try:
            walk(json.loads(b))
        except Exception:
            continue
    return pub, mod


# Instruction-like patterns. A hit never changes worker behaviour; it only flags the
# evidence so any derived candidate is deferred for human review.
INJECTION_PATTERNS = [
    r"ignore (all |any )?(previous|prior|above) (instructions|prompts?)",
    r"disregard (all |any )?(previous|prior|above)",
    r"you are (now )?(an? )?(ai|assistant|language model)",
    r"system prompt",
    r"\b(run|execute) (the )?(following )?(command|script|tool)",
    r"\bcurl\s+-|\bwget\s+|\brm\s+-rf\b",
    r"call (the )?(tool|function) ",
    r"(fetch|visit|open|navigate to) (this|the following) (url|link)",
    r"as an? (ai|assistant), you must",
]
_INJ = [re.compile(p, re.I) for p in INJECTION_PATTERNS]


def scan_for_instructions(text: str) -> List[str]:
    return [p.pattern for p in _INJ if p.search(text)]


def extract(html: str, excerpt_chars: int = 1200) -> Extracted:
    p = _TextParser()
    try:
        p.feed(html)
    except Exception:
        pass
    text = _normalize("".join(p.parts))
    title = _normalize("".join(p.title_parts)) or None
    metas = dict(p.metas)
    pub = basis = mod = None
    for key, b in (("article:published_time", "meta:article:published_time"),
                   ("datepublished", "meta:datePublished"),
                   ("date", "meta:date"),
                   ("dc.date", "meta:dc.date"),
                   ("pubdate", "meta:pubdate")):
        if metas.get(key):
            pub, basis = metas[key], b
            break
    mod = metas.get("article:modified_time") or metas.get("datemodified")
    if pub is None:
        jp, jm = _find_jsonld_dates(p.jsonld)
        if jp:
            pub, basis = jp, "jsonld:datePublished"
        mod = mod or jm
    if pub is None:
        basis = "unknown"
    content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    excerpt = text[:excerpt_chars]
    # Import here to keep the text extractor independent and to guarantee that locator work cannot
    # alter the established rendered text or its content hash.
    from .recipe_locate import locate
    locators = locate(html, text, title)
    return Extracted(title, text, excerpt, content_hash, pub, basis or "unknown", mod,
                     scan_for_instructions(text), locators)
