from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .config import Config
from .download import download_pdf
from .feed import ThrottledClient, load_feed
from .models import Paper
from .naming import author_token, initial_year, suggested_filename
from .output import (
    atomic_text,
    is_pdf_file,
    render_index,
    run_paths,
    sha256_file,
    validate_output,
    write_jsonl,
    write_sidecar,
)
from .scoring import score_paper
from .storage import Database


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PipelineResult:
    fetched: int
    indexed: int
    downloaded: int
    failed: int
    index_path: Path
    metadata_path: Path


def _prepare_paper(paper: Paper, config: Config, database: Database) -> None:
    paper.score, paper.matched_rules = score_paper(paper, config)
    override = config.author_overrides.get(paper.arxiv_id)
    proposed_token = override or author_token(paper.authors[0] if paper.authors else "")
    proposed_year = initial_year(paper.published, paper.arxiv_id)
    token, year = database.assign_identity(paper, proposed_token, proposed_year)
    paper.library_author_token = token
    paper.first_seen_year = year
    paper.suggested_filename = suggested_filename(
        token, year, paper.arxiv_id, paper.version
    )


def _paper_paths(config: Config, paper: Paper) -> tuple[Path, Path]:
    directory = config.output_root / "papers" / str(paper.first_seen_year)
    directory.mkdir(parents=True, exist_ok=True)
    pdf_path = directory / paper.suggested_filename
    return pdf_path, pdf_path.with_suffix(".json")


def run_pipeline(
    config: Config,
    run_date: date,
    fixture: Path | None = None,
    no_download: bool = False,
) -> PipelineResult:
    validate_output(config.output_root, config.mount_root, config.require_mount)
    config.state_dir.mkdir(parents=True, exist_ok=True)
    paths = run_paths(config.output_root, run_date.year)
    index_path = paths["daily"] / f"{run_date.isoformat()}.md"
    metadata_path = paths["metadata"] / f"{run_date.isoformat()}.jsonl"
    database = Database(config.state_dir / "arxiv.db")
    run_id = database.begin_run(run_date.isoformat())
    client = ThrottledClient(
        config.user_agent,
        config.request_interval_seconds,
        config.request_timeout_seconds,
        config.request_retries,
    )
    downloaded = 0
    failed = 0
    papers: list[Paper] = []
    try:
        papers = load_feed(client, config.categories, fixture)
        for paper in papers:
            _prepare_paper(paper, config, database)
            pdf_path, sidecar_path = _paper_paths(config, paper)

            if pdf_path.exists() and is_pdf_file(pdf_path):
                paper.sha256 = sha256_file(pdf_path)
                paper.local_pdf = str(pdf_path.relative_to(config.output_root))
                paper.status = "PDF already present"
            elif pdf_path.exists():
                failed += 1
                paper.status = "Invalid existing PDF"
                LOGGER.error("Existing file is not a valid PDF: %s", pdf_path)
            elif paper.score >= config.download_threshold and not no_download:
                try:
                    LOGGER.info("Downloading %s to %s", paper.versioned_id, pdf_path)
                    paper.sha256 = download_pdf(client, paper.pdf_url, pdf_path)
                    paper.local_pdf = str(pdf_path.relative_to(config.output_root))
                    paper.status = "PDF downloaded"
                    downloaded += 1
                except Exception as exc:
                    failed += 1
                    paper.status = f"Download failed: {type(exc).__name__}"
                    LOGGER.exception("Failed to download %s", paper.versioned_id)
            elif paper.score >= config.download_threshold and no_download:
                paper.status = "Download suppressed (--no-download)"
            else:
                paper.status = "Metadata only"

            if paper.local_pdf:
                write_sidecar(sidecar_path, paper)
            database.record_version(paper)

        papers.sort(key=lambda item: (-item.score, item.title.casefold()))
        indexed = [paper for paper in papers if paper.score >= config.index_threshold]
        write_jsonl(metadata_path, papers)
        atomic_text(index_path, render_index(run_date, indexed, len(papers)))
        database.finish_run(run_id, len(papers), len(indexed), downloaded, failed)
        return PipelineResult(
            fetched=len(papers),
            indexed=len(indexed),
            downloaded=downloaded,
            failed=failed,
            index_path=index_path,
            metadata_path=metadata_path,
        )
    except Exception:
        database.fail_run(run_id)
        raise
    finally:
        database.close()
