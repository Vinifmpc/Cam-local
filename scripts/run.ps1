param([Parameter(ValueFromRemainingArguments=$true)][string[]]$CamArguments)
$ErrorActionPreference = 'Stop'
$camRoot = Split-Path -Parent $PSScriptRoot
$camPython = Join-Path $camRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $camPython)) { throw 'Execute scripts/setup.ps1 primeiro.' }
& $camPython (Join-Path $camRoot 'work/cam-ui/desktop_app.py') @CamArguments
exit $LASTEXITCODE
