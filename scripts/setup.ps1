param([string]$Python = 'python')
$ErrorActionPreference = 'Stop'
$camRoot = Split-Path -Parent $PSScriptRoot
if (-not (Get-Command node -ErrorAction SilentlyContinue)) { throw 'Instale Node.js 24 x64 antes de continuar.' }
if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) { throw 'npm não encontrado. Confira a instalação do Node.js.' }
& $Python -c "import sys,struct; assert sys.version_info[:2] == (3,12) and struct.calcsize('P') == 8, 'Use Python 3.12 x64'"
if ($LASTEXITCODE -ne 0) { throw 'Use Python 3.12 x64 para criar o ambiente.' }
$camPython = Join-Path $camRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $camPython)) {
    & $Python -m venv (Join-Path $camRoot '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Não foi possível criar o ambiente virtual.' }
}
& $camPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw 'Não foi possível preparar o pip.' }
& $camPython -m pip install --only-binary=numpy,pyclipr,cffi -r (Join-Path $camRoot 'requirements-dev.txt')
if ($LASTEXITCODE -ne 0) { throw 'Falha ao instalar as dependências Python.' }
foreach ($camRuntime in @('ui-runtime','geometry-runtime')) {
    Push-Location -LiteralPath (Join-Path $camRoot "work/$camRuntime")
    try {
        & npm.cmd ci --ignore-scripts --no-audit --no-fund
        if ($LASTEXITCODE -ne 0) { throw "Falha ao instalar $camRuntime." }
    } finally { Pop-Location }
}
Write-Host 'Ambiente pronto. Execute scripts/run.ps1 ou scripts/build.ps1.'
