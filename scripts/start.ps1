param([switch]$Demo, [int]$Port = 8083)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$pythonExecutable = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExecutable)) {
    throw 'Create .venv and install requirements.txt first. See docs/run_app.md'
}
if ($Demo) { $env:DATA_SOURCE = 'demo' } else { $env:DATA_SOURCE = 'postgres' }
if (-not $Demo) {
    & $pythonExecutable (Join-Path $PSScriptRoot 'check_connection.py')
    if ($LASTEXITCODE -ne 0) {
        throw 'Database check failed. Update .env and try again. See docs/run_app.md'
    }
}
if (Test-Path -LiteralPath (Join-Path $projectRoot '.env')) {
    & $pythonExecutable -m uvicorn api.main:app --host 127.0.0.1 --port $Port --env-file .env
} else {
    & $pythonExecutable -m uvicorn api.main:app --host 127.0.0.1 --port $Port
}
