#!/usr/bin/env bash
set -e
set -m


cd $(dirname $0)

RESTART_INTERVAL=$((24 * 60 * 60))
FLASK_PID=""

cleanup() {
    echo ""
    echo "[INFO] Caught termination signal, shutting down Flask..."
    if [[ -n "$FLASK_PID" ]]; then
        kill -TERM -- -"$FLASK_PID" 2>/dev/null
        wait "$FLASK_PID" 2>/dev/null
    fi
    echo "[INFO] Exiting."
    exit 0
}

trap cleanup SIGINT SIGTERM

while true; do
    echo "[INFO] Starting Flask app at $(date)"
    python3 -m ws_monitor.web_page &
    FLASK_PID=$!

    sleep "$RESTART_INTERVAL" &
    SLEEP_PID=$!

    # Wait until either sleep finishes or we get interrupted
    wait "$SLEEP_PID"
done
