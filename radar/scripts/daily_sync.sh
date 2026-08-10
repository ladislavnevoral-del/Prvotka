#!/bin/bash
# Denní synchronizace RBD Radaru se Sbírkou listin.
# Spouští ho launchd (viz scripts/com.rbdradar.daily.plist) nebo ručně:
#   bash scripts/daily_sync.sh

set -u
PROJECT_DIR="/Users/ladislavnevoral/Downloads/RBD Radar/rbd_radar_v02"
LOG_DIR="$PROJECT_DIR/data/logs"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/sync-$(date +%Y-%m-%d).log"

cd "$PROJECT_DIR" || exit 1
source .venv/bin/activate

{
  echo "===== RBD Radar denní sync: $(date '+%Y-%m-%d %H:%M:%S') ====="
  # Menší dávka, ať jsme k justice.cz šetrní; každý den se posune dál,
  # protože už stažené listiny se přeskakují.
  python -m app.pipeline --sync-all --limit 15 --max-docs 3
  echo "===== konec: $(date '+%H:%M:%S') ====="
} >> "$LOG" 2>&1

# Úklid logů starších než 30 dní
find "$LOG_DIR" -name "sync-*.log" -mtime +30 -delete 2>/dev/null
