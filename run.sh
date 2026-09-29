#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
command -v uv >/dev/null || { echo '需要 uv：https://docs.astral.sh/uv/getting-started/installation/'; exit 1; }
command -v node >/dev/null || { echo '需要 Node.js 22+：https://nodejs.org/'; exit 1; }
node -e 'if (Number(process.versions.node.split(".")[0]) < 22) process.exit(1)' || { echo '需要 Node.js 22+'; exit 1; }
if [ ! -f .env ]; then cp .env.example .env; chmod 600 .env; fi
uv sync --frozen
node tools/ensure-web.mjs
echo 'Evidence 启动：http://127.0.0.1:8000（不会自动打开浏览器）'
exec uv run research serve
