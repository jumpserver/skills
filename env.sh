#!/usr/bin/env bash

# Load JumpServer skill environment variables from a local .env.local file.
# Usage:
#   source ./env.sh
#
# This helper is optional. The Python scripts load .env.local automatically,
# which also works on Windows without bash. If the file does not exist yet,
# initialize it through the skill's interactive config flow or create it manually.

if [ -n "${BASH_SOURCE[0]:-}" ]; then
  SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
else
  SKILL_DIR="$(pwd)"
fi

LOCAL_ENV="$SKILL_DIR/.env.local"

set -a

if [ -f "$LOCAL_ENV" ]; then
  # shellcheck disable=SC1091
  . "$LOCAL_ENV"
else
  echo "env.sh: .env.local not found in $SKILL_DIR" >&2
  echo "env.sh: initialize it through the interactive config flow or create it manually." >&2
  return 1 2>/dev/null || exit 1
fi

set +a

echo "JumpServer skill environment loaded from $SKILL_DIR."
