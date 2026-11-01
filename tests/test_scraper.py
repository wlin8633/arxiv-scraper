from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from datetime import date
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from arxiv_scraper.config import Config, Rule
from arxiv_scraper.feed import api_query_url, load_api_backfill, parse_atom
from arxiv_scraper.models import Paper
from arxiv_scraper.naming import author_token, suggested_filename
from arxiv_scraper.pipeline import run_pipeline
from arxiv_scraper.scoring import score_paper
from arxiv_scraper.storage import Database


FIXTURE = Path(__file__).parent / "fixtures" / "sample_atom.xml"


def make_config(root: Path) -> Config:
    return Config(
        output_root=root / "output",
        mount_root=root,
        require_mount=False,
        state_dir=root / "state",
        timezone="Asia/Taipei",
        categories=("physics.plasm-ph", "physics.ins-det"),
        category_weights={"physics.plasm-ph": 1.5, "physics.ins-det": 1.0},
        rules=(
            Rule("laser-driven ion acceleration", r"laser[- ]driven\s+(?:proton|ion)", 5.0, ("title", "abstract")),
            Rule("ion acceleration", r"(?:proton|ion)\s+acceleration", 3.5, ("title", "abstract")),
            Rule("high-energy-density plasma", r"high[- ]energy[- ]density", 3.0, ("title", "abstract")),
            Rule("particle-in-cell", r"particle[- ]in[- ]cell", 2.5, ("title", "abstract")),
            Rule("CR-39", r"\bCR[- ]?39\b", 5.0, ("title", "abstract")),
            Rule("Thomson parabola", r"Thomson\s+parabola", 4.0, ("title", "abstract")),
        ),
        index_threshold=2.0,
        download_threshold=7.0,
        request_interval_seconds=0.0,
        request_timeout_seconds=1.0,
        request_retries=1,
        user_agent="test-client",
        author_overrides={},
    )


class FeedAndNamingTests(unittest.TestCase):
    def test_parse_feed_and_filename(self) -> None:
        papers = parse_atom(FIXTURE.read_bytes())
        self.assertEqual(len(papers), 3)
        self.assertEqual(papers[0].arxiv_id, "2610.12345")
        self.assertEqual(papers[0].version, 1)
        self.assertEqual(papers[0].authors[0], "Alice Smith")
        self.assertEqual(papers[0].abstract_url, "https://arxiv.org/abs/2610.12345v1")
        self.assertFalse(papers[0].abstract.startswith("arXiv:"))
        self.assertEqual(
            suggested_filename("Smith", 2026, papers[0].arxiv_id, 1),
            "Smith_2026_arXiv-2610.12345v1.pdf",
        )

    def test_author_particles(self) -> None:
        self.assertEqual(author_token("Ana de la Cruz"), "de_la_Cruz")
        self.assertEqual(author_token("Smith, Alice"), "Smith")
        self.assertEqual(author_token(r"Marko \v{S}imi\'c"), "Simic")

    def test_scoring(self) -> None:
        papers = parse_atom(FIXTURE.read_bytes())
        with tempfile.TemporaryDirectory() as temporary:
            config = make_config(Path(temporary))
            high_score, matches = score_paper(papers[0], config)
            low_score, _ = score_paper(papers[1], config)
        self.assertGreaterEqual(high_score, 10.0)
        self.assertLess(low_score, config.index_threshold)
        self.assertTrue(any("laser-driven" in match for match in matches))

    def test_api_query_uses_updated_date_window(self) -> None:
        url = api_query_url(
            "physics.plasm-ph",
            date(2026, 10, 27),
            date(2026, 11, 2),
            start=100,
            max_results=50,
        )
        query = parse_qs(urlparse(url).query)
        self.assertEqual(query["start"], ["100"])
        self.assertEqual(query["max_results"], ["50"])
        self.assertEqual(query["sortBy"], ["lastUpdatedDate"])
        self.assertIn(
            "lastUpdatedDate:[202610270000 TO 202611022359]",
            query["search_query"][0],
        )

    def test_api_backfill_deduplicates_cross_listed_versions(self) -> None:
        class FixtureClient:
            def __init__(self) -> None:
                self.urls: list[str] = []

            def read_bytes(self, url: str) -> bytes:
                self.urls.append(url)
                return FIXTURE.read_bytes()

        client = FixtureClient()
        papers = load_api_backfill(
            client,
            ("physics.plasm-ph", "physics.ins-det"),
            date(2026, 10, 27),
            date(2026, 11, 2),
            page_size=100,
            max_results_per_category=500,
        )
        self.assertEqual(len(papers), 3)
        self.assertEqual(len(client.urls), 2)


class PersistenceTests(unittest.TestCase):
    def test_unknown_token_is_repaired_once_author_is_available(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Database(Path(temporary) / "arxiv.db")
            paper = Paper(
                arxiv_id="2610.99999",
                version=1,
                title="Title",
                abstract="Abstract",
                authors=[],
                categories=["physics.plasm-ph"],
                published="2026-10-27T18:00:00Z",
                updated="2026-10-27T18:00:00Z",
                abstract_url="https://arxiv.org/abs/2610.99999v1",
                pdf_url="https://arxiv.org/pdf/2610.99999v1",
            )
            try:
                database.assign_identity(paper, "Unknown", 2026)
                token, year = database.assign_identity(paper, "Smith", 2026)
            finally:
                database.close()
        self.assertEqual((token, year), ("Smith", 2026))

    def test_author_token_is_frozen_across_versions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Database(Path(temporary) / "arxiv.db")
            try:
                v1 = Paper(
                    arxiv_id="2610.12345",
                    version=1,
                    title="Title",
                    abstract="Abstract",
                    authors=["Alice Smith"],
                    categories=["physics.plasm-ph"],
                    published="2026-10-27T18:00:00Z",
                    updated="2026-10-27T18:00:00Z",
                    abstract_url="https://arxiv.org/abs/2610.12345v1",
                    pdf_url="https://arxiv.org/pdf/2610.12345v1",
                )
                token1, year1 = database.assign_identity(v1, "Smith", 2026)
                v2 = replace(v1, version=2, authors=["Chris Lee"])
                token2, year2 = database.assign_identity(v2, "Lee", 2026)
            finally:
                database.close()
        self.assertEqual((token1, year1), ("Smith", 2026))
        self.assertEqual((token2, year2), ("Smith", 2026))

    def test_database_reports_known_versions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Database(Path(temporary) / "arxiv.db")
            paper = Paper(
                arxiv_id="2610.99998",
                version=1,
                title="Title",
                abstract="Abstract",
                authors=["Alice Smith"],
                categories=["physics.plasm-ph"],
                published="2026-10-27T18:00:00Z",
                updated="2026-10-27T18:00:00Z",
                abstract_url="https://arxiv.org/abs/2610.99998v1",
                pdf_url="https://arxiv.org/pdf/2610.99998v1",
            )
            try:
                self.assertFalse(database.has_version(paper.arxiv_id, 1))
                database.assign_identity(paper, "Smith", 2026)
                database.record_version(paper)
                self.assertTrue(database.has_version(paper.arxiv_id, 1))
                self.assertFalse(database.has_version(paper.arxiv_id, 2))
            finally:
                database.close()

    def test_offline_pipeline_and_manual_pdf_detection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = make_config(root)
            result = run_pipeline(
                config,
                date(2026, 10, 28),
                fixture=FIXTURE,
                no_download=True,
            )
            self.assertEqual(result.fetched, 3)
            self.assertEqual(result.indexed, 2)
            index = result.index_path.read_text(encoding="utf-8")
            self.assertIn("Smith_2026_arXiv-2610.12345v1.pdf", index)
            self.assertIn("Download suppressed (--no-download)", index)
            self.assertIn("../../metadata/2026/2026-10-28.jsonl", index)

            metadata_rows = [
                json.loads(line)
                for line in result.metadata_path.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(len(metadata_rows), 3)

            manual_pdf = (
                config.output_root
                / "papers"
                / "2026"
                / "Smith_2026_arXiv-2610.12345v1.pdf"
            )
            manual_pdf.write_bytes(b"%PDF-1.4\nmanual test\n")
            rerun = run_pipeline(
                config,
                date(2026, 10, 28),
                fixture=FIXTURE,
                no_download=True,
            )
            rerun_index = rerun.index_path.read_text(encoding="utf-8")
            self.assertIn("PDF already present", rerun_index)
            self.assertIn("../../papers/2026/Smith_2026_arXiv-2610.12345v1.pdf", rerun_index)
            self.assertTrue(manual_pdf.with_suffix(".json").exists())

    def test_api_backfill_processes_only_unknown_versions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = make_config(root)
            existing = parse_atom(FIXTURE.read_bytes())[0]
            run_pipeline(
                config,
                date(2026, 10, 28),
                fixture=FIXTURE,
                no_download=True,
            )
            new_paper = replace(
                existing,
                arxiv_id="2610.55555",
                title="Laser-driven ion acceleration measured with CR-39",
                abstract="CR-39 records laser-driven proton acceleration.",
                abstract_url="https://arxiv.org/abs/2610.55555v1",
                pdf_url="https://arxiv.org/pdf/2610.55555v1",
            )

            with patch("arxiv_scraper.pipeline.load_feed", return_value=[]), patch(
                "arxiv_scraper.pipeline.load_api_backfill",
                return_value=[existing, new_paper],
            ):
                result = run_pipeline(
                    config,
                    date(2026, 10, 29),
                    no_download=True,
                )

            self.assertEqual(result.fetched, 1)
            rows = [
                json.loads(line)
                for line in result.metadata_path.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual([row["arxiv_id"] for row in rows], ["2610.55555"])

    def test_empty_rerun_preserves_existing_daily_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = make_config(root)
            first = run_pipeline(
                config,
                date(2026, 10, 28),
                fixture=FIXTURE,
                no_download=True,
            )
            before = first.metadata_path.read_text(encoding="utf-8")

            with patch("arxiv_scraper.pipeline.load_feed", return_value=[]):
                rerun = run_pipeline(
                    replace(config, api_backfill_days=0),
                    date(2026, 10, 28),
                    no_download=True,
                )

            self.assertEqual(rerun.fetched, 0)
            self.assertEqual(rerun.metadata_path.read_text(encoding="utf-8"), before)
            self.assertIn(
                "Smith_2026_arXiv-2610.12345v1.pdf",
                rerun.index_path.read_text(encoding="utf-8"),
            )


if __name__ == "__main__":
    unittest.main()
