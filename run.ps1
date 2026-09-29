$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (!(Test-Path .env)) { Copy-Item .env.example .env }
uv sync --frozen
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
node tools/ensure-web.mjs
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host 'Evidence: http://127.0.0.1:8000'
uv run research serve
