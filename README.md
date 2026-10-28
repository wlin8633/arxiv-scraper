# arxiv-scraper

A small, dependency-free Python pipeline for building a personal arXiv reading
list. It reads official daily Atom feeds, scores papers against configurable
research interests, stores metadata in SQLite and JSONL, and downloads only
high-scoring PDFs to a mounted cloud directory.

## Features

- configurable arXiv categories, keyword rules, weights, and thresholds;
- daily Markdown index plus complete JSONL metadata;
- SQLite-backed deduplication, version tracking, and run history;
- validated PDF downloads with SHA-256 sidecar metadata;
- stable, searchable filenames such as
  `Smith_2026_arXiv-2610.12345v1.pdf`;
- detection of manually downloaded PDFs that use the suggested filename;
- safe refusal to write when the configured cloud mount is unavailable;
- optional systemd user timer with project-specific journal logs;
- no third-party Python packages.

The filename author token and first-seen year are frozen when a paper first
enters the library. If a later arXiv version changes its first author, all
versions still sort together.

## Requirements

- Python 3.11 or newer;
- Linux for the included systemd automation;
- a writable output directory, optionally backed by rclone, Google Drive, or
  another mounted cloud filesystem.

## Quick start

```bash
git clone https://github.com/wlin8633/arxiv-scraper.git
cd arxiv-scraper
cp config.example.toml config.toml
```

Edit `config.toml`, especially:

- `output_root` and `mount_root`;
- `timezone`;
- `user_agent` with your contact information;
- categories, rules, and score thresholds.

Run the offline tests:

```bash
python3 -m unittest discover -s tests -v
```

Generate an index without downloading PDFs:

```bash
python3 -m arxiv_scraper --config config.toml --no-download --verbose
```

Run normally:

```bash
python3 -m arxiv_scraper --config config.toml
```

## Output layout

```text
ArXiv Papers/
├── daily/2026/2026-10-28.md
├── metadata/2026/2026-10-28.jsonl
└── papers/2026/
    ├── Smith_2026_arXiv-2610.12345v1.pdf
    └── Smith_2026_arXiv-2610.12345v1.json
```

Operational state is kept separately at `general.state_dir`. Do not place the
SQLite database on a FUSE or cloud mount.

## Scoring

Each matching category and rule contributes its configured weight. A paper is:

- included in the Markdown list at `index_threshold`;
- downloaded automatically at `download_threshold`;
- always retained in the day's JSONL metadata.

Rules are regular expressions and can inspect `title`, `abstract`, `authors`,
or `categories`. The included configuration is a plasma/HEDP example and is
intended to be customized.

## Stable filenames and manual additions

Every listed paper receives a suggested filename based on the first author's
surname, initial arXiv year, stable arXiv ID, and version. To add a paper that
was not downloaded automatically:

1. Download it from the arXiv link in the daily index.
2. Use the exact suggested filename.
3. Put it in `papers/<initial-year>/`.
4. Run the scraper again.

The next run verifies the PDF header, computes its checksum, creates the JSON
sidecar, and links it from the daily index.

Free-form arXiv author names are not always unambiguous. Correct a surname token
before first ingestion with:

```toml
[author_overrides]
"2610.12345" = "de_la_Cruz"
```

## Automatic scheduling

After preparing `config.toml`, install the user service and timer:

```bash
chmod +x install-systemd.sh
./install-systemd.sh
```

The default timer runs daily at 14:15 Asia/Taipei with up to ten minutes of
random delay. Edit `systemd/arxiv-scraper.timer` for another schedule.

Useful commands:

```bash
systemctl --user status arxiv-scraper.timer --no-pager
systemctl --user start arxiv-scraper.service
journalctl --user-unit=arxiv-scraper.service -n 100 --no-pager
```

For unattended execution after logout, enable user lingering if it is not
already active. This may require administrator access:

```bash
loginctl show-user "$USER" -p Linger
sudo loginctl enable-linger "$USER"
```

## Safety and recovery

- `config.toml`, SQLite state, PDFs, generated metadata, tokens, and common
  credential files are ignored by Git.
- The scraper refuses to write into an unmounted local directory when
  `require_mount = true`.
- Downloads use a `.part` file and are renamed only after PDF validation.
- A process lock prevents overlapping runs.
- Re-running the same feed is idempotent.

If a scheduled run fails, check the cloud mount and then inspect:

```bash
journalctl --user-unit=arxiv-scraper.service -n 100 --no-pager
```

## arXiv usage

The client uses one connection and waits at least three seconds between arXiv
requests. Review the current [arXiv API Terms of Use](https://info.arxiv.org/help/api/tou.html)
before changing request behavior or redistributing downloaded content. PDFs are
intended for personal or research use; metadata and links are safer to share
than copied full text.
