#!/bin/bash
# Planetary Agent Cron Runner
# Run this in a tmux/screen session to keep the planets talking.
#
# Usage:
#   ./scripts/planetary_cron.sh          # run every 90 minutes
#   ./scripts/planetary_cron.sh 60       # run every 60 minutes
#
# Or add to crontab:
#   0 */2 * * * cd /home/bastard/Documents/ai-playground && ./scripts/planetary_cron.sh --once

set -euo pipefail
cd "$(dirname "$0")/.."

INTERVAL_MIN="${1:-90}"
LOGFILE="data/planetary_runtime.log"

if [ "${1:-}" = "--once" ]; then
    echo "[$(date)] Running one round..." >> "$LOGFILE"
    python3 scripts/planetary_runtime.py --once 2>&1 | tee -a "$LOGFILE"
    exit 0
fi

echo "🪐 Planetary cron started — interval: ${INTERVAL_MIN}m"
echo "   Log: $LOGFILE"
echo "   Ctrl+C to stop"

while true; do
    echo "" >> "$LOGFILE"
    echo "[$(date)] === Round ===" >> "$LOGFILE"
    python3 scripts/planetary_runtime.py --once 2>&1 | tee -a "$LOGFILE"
    echo "[$(date)] Next round in ${INTERVAL_MIN}m" >> "$LOGFILE"
    sleep $((INTERVAL_MIN * 60))
done
