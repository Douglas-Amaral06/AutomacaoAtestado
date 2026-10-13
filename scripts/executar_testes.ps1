$ErrorActionPreference = "Stop"
$env:PYTHONDONTWRITEBYTECODE = "1"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$testTemp = Join-Path $projectRoot ".pytest-tmp"
& ".\.venv\Scripts\python.exe" -m pytest -q -p no:cacheprovider --basetemp $testTemp
exit $LASTEXITCODE
