"""Data models shared by the crawler and user interface."""

from dataclasses import dataclass, field
from typing import Dict, Set, Tuple


@dataclass
class Page:
    url: str
    depth: int
    title: str = ""
    description: str = ""
    keywords: str = ""
    body: str = ""
    status: str = ""
    error: str = ""
    is_html: bool = False


@dataclass
class CrawlRun:
    name: str
    start_url: str
    max_depth: int
    max_pages: int
    strategy: str
    crawl_mode: str
    using: str
    pages: Dict[str, Page] = field(default_factory=dict)
    edges: Set[Tuple[str, str]] = field(default_factory=set)
    hyperlinks: Set[Tuple[str, str]] = field(default_factory=set)

    @property
    def graph_depth(self) -> int:
        return max((page.depth for page in self.pages.values()), default=0)
