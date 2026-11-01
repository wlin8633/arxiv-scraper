from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from .config import Config
from .download import download_pdf
from .feed import ThrottledClient, load_api_backfill, load_feed
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


def _unique_versions(papers: list[Paper]) -> list[Paper]:
    unique: dict[tuple[str, int], Paper] = {}
    for paper in papers:
        unique[(paper.arxiv_id, paper.version)] = paper
    return list(unique.values())


def _read_existing_metadata(path: Path) -> list[Paper]:
    if not path.exists():
        return []
    papers: list[Paper] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        try:
            papers.append(Paper(**json.loads(line)))
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError(
                f"Cannot merge invalid metadata row {line_number} in {path}"
            ) from exc
    return papers


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
        rss_papers = _unique_versions(load_feed(client, config.categories, fixture))
        papers = list(rss_papers)
        api_candidates: list[Paper] = []
        if fixture is None and config.api_backfill_days > 0:
            lookback_start = run_date - timedelta(
                days=max(config.api_backfill_days - 1, 0)
            )
            api_candidates = load_api_backfill(
                client,
                config.categories,
                lookback_start,
                run_date,
                config.api_page_size,
                config.api_max_results_per_category,
            )
            rss_keys = {
                (paper.arxiv_id, paper.version) for paper in rss_papers
            }
            papers.extend(
                paper
                for paper in api_candidates
                if (paper.arxiv_id, paper.version) not in rss_keys
                and not database.has_version(paper.arxiv_id, paper.version)
            )
            papers = _unique_versions(papers)
            LOGGER.info(
                "Source reconciliation: rss=%s api_candidates=%s to_process=%s",
                len(rss_papers),
                len(api_candidates),
                len(papers),
            )

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

        combined = _unique_versions(_read_existing_metadata(metadata_path) + papers)
        combined.sort(key=lambda item: (-item.score, item.title.casefold()))
        combined_indexed = [
            paper for paper in combined if paper.score >= config.index_threshold
        ]
        write_jsonl(metadata_path, combined)
        atomic_text(
            index_path,
            render_index(run_date, combined_indexed, len(combined)),
        )
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
