#!/usr/bin/env bash
set -euo pipefail

# Uso:
#   tools/rollback_cleanup.sh <backup_tar_gz> <commit_before_cleanup>
# Ejemplo:
#   tools/rollback_cleanup.sh backups/cleanup_backup_20260428_100633.tar.gz 601f8a7

BACKUP_PATH="${1:-}"
BASE_COMMIT="${2:-}"

if [[ -z "$BACKUP_PATH" || -z "$BASE_COMMIT" ]]; then
  echo "Usage: tools/rollback_cleanup.sh <backup_tar_gz> <commit_before_cleanup>"
  exit 1
fi

if [[ ! -f "$BACKUP_PATH" ]]; then
  echo "Backup not found: $BACKUP_PATH"
  exit 1
fi

echo "[1/3] Restoring backup archive..."
tar -xzf "$BACKUP_PATH"

echo "[2/3] Resetting git state..."
git fetch --all --prune
git reset --hard "$BASE_COMMIT"

echo "[3/3] Done."
echo "Repository restored to commit: $BASE_COMMIT"
echo "If needed, run: git clean -fd (careful: removes untracked files)."
