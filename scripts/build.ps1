$ErrorActionPreference = 'Stop'
$camRoot = Split-Path -Parent $PSScriptRoot
$camPython = Join-Path $camRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $camPython)) { throw 'Execute scripts/setup.ps1 primeiro.' }
& $camPython -m PyInstaller (Join-Path $camRoot 'work/cam-ui/CAMLocal.spec') --noconfirm --distpath (Join-Path $camRoot 'dist/CAM-local-Windows') --workpath (Join-Path $camRoot 'build/PyInstaller')
if ($LASTEXITCODE -ne 0) { throw 'O build do executável falhou.' }
& $camPython (Join-Path $camRoot 'scripts/package_binary.py')
if ($LASTEXITCODE -ne 0) { throw 'Não foi possível preparar a distribuição.' }
Write-Host 'Distribuição pronta em dist/CAM-Local-Windows-publico.zip'
