$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "Project virtual-environment Python was not found at $Python"
}

Push-Location $ProjectRoot
try {
    & $Python -m app.maintenance purge-rate-limits --batch-size 1000
    if ($LASTEXITCODE -ne 0) {
        throw "Rate-limit cleanup failed with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}
