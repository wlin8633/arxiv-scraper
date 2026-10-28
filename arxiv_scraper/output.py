from __future__ import annotations

import hashlib
import json
import os
from datetime import date
from pathlib import Path

from .models import Paper


def validate_output(output_root: Path, mount_root: Path, require_mount: bool) -> None:
    if require_mount and not mount_root.is_mount():
        raise RuntimeError(
            f"Required Google Drive mount is not active: {mount_root}. "
            "Refusing to write into the unmounted local directory."
        )
    output_root.mkdir(parents=True, exist_ok=True)
    if not os.access(output_root, os.W_OK):
        raise PermissionError(f"Output directory is not writable: {output_root}")


def run_paths(output_root: Path, year: int) -> dict[str, Path]:
    paths = {
        "daily": output_root / "daily" / str(year),
        "metadata": output_root / "metadata" / str(year),
    }
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    return paths


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def is_pdf_file(path: Path) -> bool:
    try:
        with path.open("rb") as stream:
            return stream.read(5) == b"%PDF-"
    except OSError:
        return False


def atomic_text(path: Path, content: str) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(content, encoding="utf-8", newline="\n")
    temporary.replace(path)


def write_jsonl(path: Path, papers: list[Paper]) -> None:
    content = "".join(
        json.dumps(paper.to_dict(), ensure_ascii=False, sort_keys=True) + "\n"
        for paper in papers
    )
    atomic_text(path, content)


def write_sidecar(path: Path, paper: Paper) -> None:
    atomic_text(path, json.dumps(paper.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def _single_line(text: str) -> str:
    return " ".join(text.split())


def render_index(run_date: date, papers: list[Paper], total_fetched: int) -> str:
    lines = [
        f"# arXiv papers — {run_date.isoformat()}",
        "",
        f"Fetched: {total_fetched} | Listed: {len(papers)}",
        "",
        f"Complete metadata: [JSONL](../../metadata/{run_date.year}/{run_date.isoformat()}.jsonl)",
        "",
        "Papers are sorted by score. The filename author token is frozen when a paper first enters the library, so later author-list changes do not rename earlier versions.",
        "",
    ]
    if not papers:
        lines.extend(["No papers reached the index threshold today.", ""])
        return "\n".join(lines)

    for paper in papers:
        lines.extend(
            [
                f"## {paper.library_author_token}_{paper.first_seen_year} — {paper.title}",
                "",
                f"- Authors: {', '.join(paper.authors)}",
                f"- arXiv: [{paper.versioned_id}]({paper.abstract_url})",
                f"- Categories: {', '.join(paper.categories)}",
                f"- Score: {paper.score:g}",
                f"- Matched: {'; '.join(paper.matched_rules) or 'None'}",
                f"- Status: {paper.status}",
                f"- Suggested filename: `{paper.suggested_filename}`",
            ]
        )
        if paper.local_pdf:
            pdf_link = "../../" + paper.local_pdf.replace("\\", "/")
            json_link = str(Path(pdf_link).with_suffix(".json")).replace("\\", "/")
            lines.append(f"- PDF: [Open PDF]({pdf_link})")
            lines.append(f"- Metadata: [JSON]({json_link})")
        lines.extend([f"- Abstract: {_single_line(paper.abstract)}", ""])
    return "\n".join(lines)
