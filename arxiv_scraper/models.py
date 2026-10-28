from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class Paper:
    arxiv_id: str
    version: int
    title: str
    abstract: str
    authors: list[str]
    categories: list[str]
    published: str
    updated: str
    abstract_url: str
    pdf_url: str
    score: float = 0.0
    matched_rules: list[str] = field(default_factory=list)
    library_author_token: str = ""
    first_seen_year: int = 0
    suggested_filename: str = ""
    status: str = "Metadata only"
    local_pdf: str | None = None
    sha256: str | None = None

    @property
    def versioned_id(self) -> str:
        return f"{self.arxiv_id}v{self.version}"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
