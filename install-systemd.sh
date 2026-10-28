#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="$PROJECT_ROOT/config.toml"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"

if [[ ! -f "$CONFIG_FILE" ]]; then
  echo "Missing $CONFIG_FILE. Copy config.example.toml to config.toml and edit it first." >&2
  exit 1
fi

readarray -t CONFIG_PATHS < <(
  python3 -c 'import pathlib, sys, tomllib
with open(sys.argv[1], "rb") as stream:
    general = tomllib.load(stream)["general"]
for key in ("state_dir", "output_root"):
    print(pathlib.Path(general[key]).expanduser().resolve())' "$CONFIG_FILE"
)

STATE_DIR="${CONFIG_PATHS[0]}"
OUTPUT_ROOT="${CONFIG_PATHS[1]}"

mkdir -p "$STATE_DIR" "$OUTPUT_ROOT" "$UNIT_DIR"
sed \
  -e "s|@PROJECT_ROOT@|$PROJECT_ROOT|g" \
  -e "s|@STATE_DIR@|$STATE_DIR|g" \
  -e "s|@OUTPUT_ROOT@|$OUTPUT_ROOT|g" \
  "$PROJECT_ROOT/systemd/arxiv-scraper.service.in" \
  > "$UNIT_DIR/arxiv-scraper.service"
install -m 0644 "$PROJECT_ROOT/systemd/arxiv-scraper.timer" "$UNIT_DIR/arxiv-scraper.timer"

systemctl --user daemon-reload
systemctl --user enable --now arxiv-scraper.timer
systemctl --user list-timers arxiv-scraper.timer --no-pager
