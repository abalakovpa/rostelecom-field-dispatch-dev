param([ValidateRange(1,300)][int]$PlanLimit = 5)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
docker info --format '{{.ServerVersion}}'
if ($LASTEXITCODE -ne 0) { throw 'Start Docker Desktop Linux Engine and retry.' }
$qaProject = 'dispatcher-http-qa'
$qaEnvironment = '.env.http-qa'
if (!(Test-Path $qaEnvironment)) {
    $qaPassword = [Guid]::NewGuid().ToString('N') + [Guid]::NewGuid().ToString('N')
    @('POSTGRES_DB=dispatcher_http_qa','POSTGRES_USER=dispatcher',"POSTGRES_PASSWORD=$qaPassword",'POSTGRES_HOST=db','POSTGRES_PORT=5432','APP_PORT=18080','DOCKER_POSTGRES_PORT=15434') | Set-Content -Encoding ASCII $qaEnvironment
    Remove-Variable qaPassword
}
$qaOverride = 'compose.http-qa.local.yaml'
@('services:','  api:','    volumes:','      - .:/qa') | Set-Content -Encoding ASCII $qaOverride
docker compose --env-file $qaEnvironment -p $qaProject -f compose.yaml -f $qaOverride up --build -d
if ($LASTEXITCODE -ne 0) { throw 'QA startup failed.' }
$qaReady = $false
for ($qaAttempt = 0; $qaAttempt -lt 60; $qaAttempt++) {
    try {
        $qaHealth = Invoke-RestMethod 'http://127.0.0.1:18080/api/v1/health' -TimeoutSec 2
        if ($qaHealth.status -eq 'ok') { $qaReady = $true; break }
    } catch {}
    Start-Sleep -Seconds 2
}
if (!$qaReady) { throw 'QA API did not become ready. Inspect container logs.' }
docker compose --env-file $qaEnvironment -p $qaProject -f compose.yaml -f $qaOverride exec -T -w /qa api python scripts/check_scenario_api.py --url http://127.0.0.1:8080 --db-env /qa/.env.http-qa --test-database dispatcher_http_qa --allow-reset --plan-limit $PlanLimit --output /qa/data/qa
$qaResult = $LASTEXITCODE
Write-Host 'Reports: data/qa. Containers and database retained for investigation.'
if ($qaResult -ne 0) { throw "HTTP scenario failed (exit $qaResult). See partial report.json." }
