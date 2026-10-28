from __future__ import annotations

import argparse
import logging
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import load_config
from .locking import exclusive_lock
from .pipeline import run_pipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fetch, rank, and archive new arXiv papers."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config.toml"),
        help="Path to the TOML configuration file.",
    )
    parser.add_argument(
        "--feed-file",
        type=Path,
        help="Read an Atom feed from disk instead of contacting arXiv.",
    )
    parser.add_argument(
        "--date",
        type=date.fromisoformat,
        help="Override the report date (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--no-download",
        action="store_true",
        help="Generate metadata and index without downloading PDFs.",
    )
    parser.add_argument("--verbose", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = load_config(args.config.resolve())
    run_date = args.date or datetime.now(ZoneInfo(config.timezone)).date()
    try:
        with exclusive_lock(config.state_dir / "arxiv-scraper.lock"):
            result = run_pipeline(
                config,
                run_date,
                fixture=args.feed_file.resolve() if args.feed_file else None,
                no_download=args.no_download,
            )
    except Exception:
        logging.getLogger(__name__).exception("arxiv-scraper failed")
        return 1

    logging.getLogger(__name__).info(
        "Finished: fetched=%s indexed=%s downloaded=%s failed=%s index=%s",
        result.fetched,
        result.indexed,
        result.downloaded,
        result.failed,
        result.index_path,
    )
    return 2 if result.failed else 0
