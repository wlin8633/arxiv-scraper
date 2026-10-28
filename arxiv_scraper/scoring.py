from __future__ import annotations

import re

from .config import Config
from .models import Paper


def score_paper(paper: Paper, config: Config) -> tuple[float, list[str]]:
    score = 0.0
    matches: list[str] = []

    for category in paper.categories:
        weight = config.category_weights.get(category, 0.0)
        if weight:
            score += weight
            matches.append(f"category:{category} ({weight:+g})")

    searchable = {
        "title": paper.title,
        "abstract": paper.abstract,
        "authors": " ".join(paper.authors),
        "categories": " ".join(paper.categories),
    }
    for rule in config.rules:
        found_in = [
            field
            for field in rule.fields
            if field in searchable
            and re.search(rule.pattern, searchable[field], flags=re.IGNORECASE)
        ]
        if found_in:
            score += rule.weight
            matches.append(f"{rule.label} ({rule.weight:+g}; {', '.join(found_in)})")

    return round(score, 3), matches
