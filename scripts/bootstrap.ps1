$ErrorActionPreference = "Stop"
uv python install 3.12
if ($LASTEXITCODE -ne 0) { throw "Python installation failed" }
uv sync --group dev
if ($LASTEXITCODE -ne 0) { throw "Dependency synchronization failed" }
if (-not (Test-Path -LiteralPath .env)) {
    Copy-Item -LiteralPath .env.example -Destination .env
}
Write-Host "Scaffold ready. Run: uv run harness-api"
