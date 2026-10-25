"""HTML metadata extraction and URL normalization."""

import html
import re
from html.parser import HTMLParser
from typing import List, Optional, Tuple
from urllib.parse import urldefrag, urljoin, urlsplit, urlunsplit


class LinkParser(HTMLParser):
    """Collect page metadata and links from an HTML document."""

    def __init__(self, using: str) -> None:
        super().__init__(convert_charrefs=True)
        self.using = using
        self.title_parts: List[str] = []
        self.description = ""
        self.keywords = ""
        self.body_parts: List[str] = []
        self.links: List[Tuple[str, str]] = []
        self.in_title = False
        self.in_body = False

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        values = dict(attrs)
        if tag == "title":
            self.in_title = True
        if tag == "body":
            self.in_body = True
        if tag == "meta":
            name = (values.get("name") or "").lower()
            content = (values.get("content") or "").strip()
            if name == "description":
                self.description = content
            elif name in ("keywords", "keyw"):
                self.keywords = content

        if self.using == "images+hyperlinks":
            if tag == "a" and values.get("href"):
                self.links.append((values["href"] or "", "link"))
            elif tag == "img" and values.get("src"):
                self.links.append((values["src"] or "", "image"))
            return

        for attribute in ("href", "src"):
            value = values.get(attribute)
            if value:
                kind = "image" if tag == "img" else "link"
                self.links.append((value, kind))

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self.in_title = False
        elif tag == "body":
            self.in_body = False

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if not text:
            return
        if self.in_title:
            self.title_parts.append(text)
        if self.in_body:
            self.body_parts.append(text)

    @property
    def title(self) -> str:
        return " ".join(self.title_parts).strip()

    @property
    def body(self) -> str:
        return re.sub(r"\s+", " ", " ".join(self.body_parts)).strip()


def normalize_url(value: str, base_url: str) -> Optional[str]:
    value = html.unescape(value.strip())
    markdown_link = re.fullmatch(r"\[[^\]]+\]\((https?://[^)\s]+)\)", value)
    if markdown_link:
        value = markdown_link.group(1)
    if not value or value.startswith("#"):
        return None
    absolute = urljoin(base_url, value)
    absolute = urldefrag(absolute).url
    parts = urlsplit(absolute)
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        return None
    path = parts.path or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, parts.query, ""))
