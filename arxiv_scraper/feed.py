from __future__ import annotations

import logging
import re
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

from .models import Paper


LOGGER = logging.getLogger(__name__)
ATOM = "{http://www.w3.org/2005/Atom}"
DC = "{http://purl.org/dc/elements/1.1/}"
ARXIV_ID_RE = re.compile(
    r"(?P<base>\d{4}\.\d{4,5}|[A-Za-z.-]+/\d{7})(?:v(?P<version>\d+))?"
)


class ThrottledClient:
    def __init__(self, user_agent: str, interval_seconds: float, timeout_seconds: float, retries: int) -> None:
        self.user_agent = user_agent
        self.interval_seconds = interval_seconds
        self.timeout_seconds = timeout_seconds
        self.retries = retries
        self._last_request = 0.0

    def _wait(self) -> None:
        remaining = self.interval_seconds - (time.monotonic() - self._last_request)
        if remaining > 0:
            time.sleep(remaining)

    def open(self, url: str):
        last_error: Exception | None = None
        for attempt in range(1, self.retries + 1):
            self._wait()
            request = urllib.request.Request(
                url,
                headers={"User-Agent": self.user_agent, "Accept": "*/*"},
            )
            try:
                response = urllib.request.urlopen(request, timeout=self.timeout_seconds)
                self._last_request = time.monotonic()
                return response
            except (urllib.error.URLError, TimeoutError) as exc:
                self._last_request = time.monotonic()
                last_error = exc
                if attempt < self.retries:
                    delay = min(5 * (3 ** (attempt - 1)), 45)
                    LOGGER.warning("Request failed; retrying in %ss: %s", delay, exc)
                    time.sleep(delay)
        assert last_error is not None
        raise last_error

    def read_bytes(self, url: str) -> bytes:
        with self.open(url) as response:
            return response.read()


def feed_url(categories: tuple[str, ...]) -> str:
    if not categories:
        raise ValueError("At least one arXiv category is required")
    return "https://rss.arxiv.org/atom/" + "+".join(categories)


def _text(parent: ET.Element, tag: str) -> str:
    element = parent.find(f"{ATOM}{tag}")
    if element is None or element.text is None:
        return ""
    return " ".join(element.text.split())


def _extract_id(value: str) -> tuple[str, int]:
    matches = list(ARXIV_ID_RE.finditer(value))
    if not matches:
        raise ValueError(f"Cannot parse arXiv identifier from {value!r}")
    match = matches[-1]
    return match.group("base"), int(match.group("version") or 1)


def parse_atom(data: bytes) -> list[Paper]:
    root = ET.fromstring(data)
    papers: list[Paper] = []
    for entry in root.findall(f"{ATOM}entry"):
        raw_id = _text(entry, "id")
        arxiv_id, version = _extract_id(raw_id)
        links = entry.findall(f"{ATOM}link")
        abstract_url = f"https://arxiv.org/abs/{arxiv_id}v{version}"
        pdf_url = ""
        for link in links:
            href = link.attrib.get("href", "")
            if link.attrib.get("type") == "application/pdf" or link.attrib.get("title") == "pdf":
                pdf_url = href
        if not pdf_url:
            pdf_url = f"https://arxiv.org/pdf/{arxiv_id}v{version}"

        authors = []
        for author in entry.findall(f"{ATOM}author"):
            name = _text(author, "name")
            if name:
                authors.append(name)
        if not authors:
            creator = entry.find(f"{DC}creator")
            if creator is not None and creator.text:
                authors = [name.strip() for name in creator.text.split(",") if name.strip()]
        abstract = _text(entry, "summary")
        if abstract.startswith("arXiv:") and "Abstract:" in abstract:
            abstract = abstract.split("Abstract:", 1)[1].strip()
        categories = [
            category.attrib["term"]
            for category in entry.findall(f"{ATOM}category")
            if category.attrib.get("term")
        ]
        papers.append(
            Paper(
                arxiv_id=arxiv_id,
                version=version,
                title=_text(entry, "title"),
                abstract=abstract,
                authors=authors,
                categories=categories,
                published=_text(entry, "published"),
                updated=_text(entry, "updated"),
                abstract_url=abstract_url,
                pdf_url=pdf_url,
            )
        )
    return papers


def load_feed(client: ThrottledClient, categories: tuple[str, ...], fixture: Path | None) -> list[Paper]:
    if fixture:
        LOGGER.info("Reading feed fixture: %s", fixture)
        data = fixture.read_bytes()
    else:
        url = feed_url(categories)
        LOGGER.info("Fetching arXiv feed: %s", url)
        data = client.read_bytes(url)
    return parse_atom(data)
