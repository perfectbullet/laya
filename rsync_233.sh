#!/usr/bin/env bash
# Sync this checkout's source code to the CUDA host.  Local model weights and
# development artefacts stay on their respective machines.
set -euo pipefail

source_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
target_host="${LAYA_SYNC_HOST:-zenking@192.168.100.233}"
target_dir="${LAYA_SYNC_DIR:-/data/metahuman_work/laya}"

# Do not make the remote checkout an exact mirror by default: it can contain
# host-only files such as .env.  Opt into removals explicitly when needed.
delete_args=()
if [[ "${LAYA_SYNC_DELETE:-0}" == "1" ]]; then
    delete_args=(--delete-delay)
fi

ssh "$target_host" "mkdir -p '$target_dir'"

rsync \
    --archive \
    --compress \
    --human-readable \
    --itemize-changes \
    "${delete_args[@]}" \
    --exclude '.git/' \
    --exclude '.venv/' \
    --exclude 'venv/' \
    --exclude 'env/' \
    --exclude '__pycache__/' \
    --exclude '*.py[cod]' \
    --exclude '.pytest_cache/' \
    --exclude '.ruff_cache/' \
    --exclude '.hf-cache/' \
    --exclude '.pip-cache/' \
    --exclude 'models/' \
    --exclude 'build/' \
    --exclude 'dist/' \
    --exclude '*.egg-info/' \
    --exclude 'node_modules/' \
    --exclude '.env' \
    --exclude '.env.*' \
    --exclude 'site/' \
    "$source_dir/" \
    "$target_host:$target_dir/" \
    "$@"

echo "Synced $source_dir to $target_host:$target_dir"
