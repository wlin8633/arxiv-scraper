from __future__ import annotations

import re
import unicodedata
from datetime import datetime


_PARTICLES = {
    "al", "da", "de", "del", "della", "di", "du", "la", "le",
    "van", "von", "der", "den",
}


def author_token(author_name: str) -> str:
    """Return a portable surname-like token from an arXiv display name."""
    name = " ".join(author_name.strip().split())
    if not name:
        return "Unknown"

    if "," in name:
        surname = name.split(",", 1)[0]
    else:
        words = name.split()
        start = len(words) - 1
        while start > 0 and words[start - 1].lower().strip(".-") in _PARTICLES:
            start -= 1
        surname = "_".join(words[start:])

    surname = re.sub(
        r"\\(?:[\"'`^~=.uvHckbdtr])\s*\{?([A-Za-z])\}?",
        r"\1",
        surname,
    )
    surname = re.sub(r"\\[A-Za-z]+\s*\{([^{}]+)\}", r"\1", surname)
    surname = surname.replace("{", "").replace("}", "").replace("\\", "")
    ascii_name = unicodedata.normalize("NFKD", surname).encode("ascii", "ignore").decode()
    ascii_name = ascii_name.replace("'", "").replace("’", "")
    token = re.sub(r"[^A-Za-z0-9_-]+", "_", ascii_name).strip("_-")
    return token or "Unknown"


def initial_year(published: str, arxiv_id: str) -> int:
    try:
        return datetime.fromisoformat(published.replace("Z", "+00:00")).year
    except (TypeError, ValueError):
        match = re.match(r"(?P<yy>\d{2})(?P<mm>\d{2})\.", arxiv_id)
        if match:
            yy = int(match.group("yy"))
            return 1900 + yy if yy >= 91 else 2000 + yy
        return datetime.now().year


def safe_arxiv_id(arxiv_id: str) -> str:
    return arxiv_id.replace("/", "-")


def suggested_filename(token: str, year: int, arxiv_id: str, version: int) -> str:
    return f"{token}_{year}_arXiv-{safe_arxiv_id(arxiv_id)}v{version}.pdf"
