#!/usr/bin/env bash
# Sync ENOM source/config/docs and the locally built frontend to production
# (SSH alias: enom). Offline globe tiles are downloaded by the running server.
# This script does not install dependencies or restart services.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SRC="$(cd -- "$SCRIPT_DIR/.." && pwd)/"
REMOTE_HOST="${ENOM_PROD_HOST:-enom}"
REMOTE_DIR="${ENOM_PROD_DIR:-/home/jamels/ENOM}"

if [[ ! -f "$SRC/apps/twinworld/dist/index.html" ]]; then
  echo "Build the frontend first: cd apps/twinworld && npm ci && npm run build" >&2
  exit 1
fi

if ! command -v rsync >/dev/null 2>&1; then
  echo "rsync is required on the local machine." >&2
  exit 1
fi

RSYNC_ARGS=(-az --human-readable --itemize-changes)
if [[ "${1:-}" == "--dry-run" ]]; then
  RSYNC_ARGS+=(--dry-run)
elif [[ $# -gt 0 ]]; then
  echo "Usage: $0 [--dry-run]" >&2
  exit 2
fi

echo "Syncing $SRC to $REMOTE_HOST:$REMOTE_DIR/"
rsync "${RSYNC_ARGS[@]}" \
  --exclude='.git/' \
  --exclude='.venv/' \
  --exclude='node_modules/' \
  --exclude='build/' \
  --exclude='test-results/' \
  --exclude='playwright-report/' \
  --exclude='__pycache__/' \
  --exclude='.pytest_cache/' \
  --exclude='.mypy_cache/' \
  --exclude='.ruff_cache/' \
  --exclude='.cache/' \
  --exclude='.DS_Store' \
  --exclude='*.tsbuildinfo' \
  --exclude='/.env' \
  --exclude='/.env.*' \
  --exclude='/data/raw/' \
  --exclude='/data/terrain/' \
  --exclude='/data/patches/' \
  --exclude='/data/offline_globe_maps/' \
  --exclude='/apps/twinworld/public/tiles/offline/' \
  --exclude='/artifacts/' \
  "$SRC" "$REMOTE_HOST:$REMOTE_DIR/"

echo "ENOM source sync complete. No remote service was restarted."
