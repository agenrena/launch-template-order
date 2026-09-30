#!/bin/bash
# Start this store's App on this computer (double-click on macOS, or ./start.command).
# Needs uv (https://docs.astral.sh/uv/) and Node.js 22.12+. Data stays in data/.
cd "$(dirname "$0")" || exit 1
PATH="$HOME/.local/bin:$HOME/.cargo/bin:$HOME/.volta/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
if ! command -v node >/dev/null 2>&1 && [ -s "$HOME/.nvm/nvm.sh" ]; then
  . "$HOME/.nvm/nvm.sh"
  nvm use --silent >/dev/null 2>&1  # the version in .nvmrc
fi
if ! command -v uv >/dev/null 2>&1; then
  echo "需要先安裝 uv（可以請你的 Agent 安裝）：https://docs.astral.sh/uv/"
  exit 1
fi
exec uv run --no-project --python 3.13 --with-requirements backend/requirements.txt \
  python scripts/start.py "$@"
