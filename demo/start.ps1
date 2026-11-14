param([int]$Port = 8083)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonExecutable = Join-Path $projectRoot '.venv-demo\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExecutable)) {
    $pythonExecutable = Join-Path $projectRoot '.venv\Scripts\python.exe'
}
if (-not (Test-Path -LiteralPath $pythonExecutable)) {
    throw 'Create .venv-demo and install demo/requirements.txt. See demo/README.md'
}
& $pythonExecutable (Join-Path $PSScriptRoot 'start.py') --port $Port
