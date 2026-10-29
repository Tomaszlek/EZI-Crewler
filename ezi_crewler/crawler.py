"""Website crawling and progress event production."""

import queue
import threading
import time
from collections import deque
from typing import List, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from .models import CrawlProgress, CrawlRun, Page
from .parsing import LinkParser, normalize_url


USER_AGENT = "EZI-Crewler/1.0 (educational website structure crawler)"
MAX_RESPONSE_BYTES = 2_000_000


def _fetch_page(url: str, timeout: float = 12.0) -> Tuple[str, str, int]:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=timeout) as response:
        content_type = response.headers.get_content_type()
        charset = response.headers.get_content_charset() or "utf-8"
        data = response.read(MAX_RESPONSE_BYTES + 1)
        if len(data) > MAX_RESPONSE_BYTES:
            data = data[:MAX_RESPONSE_BYTES]
        return data.decode(charset, errors="replace"), content_type, response.status


def _site_host(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def crawl(
    run: CrawlRun,
    stop_event: threading.Event,
    events: "queue.Queue[Tuple[str, object]]",
    delay: float,
) -> None:
    """Crawl a site and send progress events to the Tkinter thread."""
    root_host = _site_host(run.start_url)
    pending = deque([(run.start_url, 0)])
    scheduled = {run.start_url}
    last_request = 0.0

    while pending and len(run.pages) < run.max_pages and not stop_event.is_set():
        url, depth = pending.popleft() if run.strategy == "Breadth first" else pending.pop()
        page = Page(url=url, depth=depth)
        run.pages[url] = page
        try:
            wait = delay - (time.monotonic() - last_request)
            if wait > 0 and stop_event.wait(wait):
                break
            source, content_type, status = _fetch_page(url)
            last_request = time.monotonic()
            page.status = str(status)
            page.is_html = content_type in ("text/html", "application/xhtml+xml")
            if page.is_html:
                parser = LinkParser(run.using)
                parser.feed(source)
                parser.close()
                page.title = parser.title
                page.description = parser.description
                page.keywords = parser.keywords
                page.body = parser.body
                discovered: List[Tuple[str, str]] = []
                for raw_url, kind in parser.links:
                    target = normalize_url(raw_url, url)
                    if not target:
                        continue
                    if run.crawl_mode == "server" and _site_host(target) != root_host:
                        continue
                    run.edges.add((url, target))
                    if kind == "link":
                        run.hyperlinks.add((url, target))
                    discovered.append((target, kind))
                # Process 1 Page only: external sites contribute only their first page.
                external_leaf = run.external_one_page and _site_host(url) != root_host
                if depth < run.max_depth and not external_leaf:
                    for target, kind in discovered:
                        if kind == "image" or target in scheduled:
                            continue
                        if len(scheduled) >= run.max_pages:
                            continue
                        scheduled.add(target)
                        pending.append((target, depth + 1))
        except (HTTPError, URLError, TimeoutError, OSError, UnicodeError, ValueError) as error:
            page.error = str(error)
            page.status = "error"
            events.put(("log", f"Błąd pobierania {url}: {error}"))
        events.put(("page", CrawlProgress(page, dict(run.pages), set(run.hyperlinks), set(run.edges))))

    state = "anulowany" if stop_event.is_set() else "zakończony"
    events.put(("done", state))
