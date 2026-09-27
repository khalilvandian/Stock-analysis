#!/bin/bash
# Installs project dependencies when a Claude Code on the web session starts.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "$CLAUDE_PROJECT_DIR"
uv sync
echo 'export PATH="$CLAUDE_PROJECT_DIR/.venv/bin:$PATH"' >> "$CLAUDE_ENV_FILE"
