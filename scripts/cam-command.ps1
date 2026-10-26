param(
    [string]$Action = 'state',
    [string]$Json,
    [string]$File,
    [int]$Port = 0,
    [switch]$Start,
    [string]$DataDir
)
$ErrorActionPreference = 'Stop'
$taskTemp = Join-Path ([IO.Path]::GetTempPath()) ('cam-command-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $taskTemp | Out-Null
try {
    $taskInput = Join-Path $taskTemp 'command.json'
    $taskReply = Join-Path $taskTemp 'reply.json'
    if ($File) {
        Copy-Item -LiteralPath (Resolve-Path -LiteralPath $File).Path -Destination $taskInput
    } else {
        $taskText = if ($Json) { $Json } else { @{ action = $Action } | ConvertTo-Json -Compress }
        [IO.File]::WriteAllText($taskInput, $taskText, [Text.UTF8Encoding]::new($false))
    }
    $taskArgs = @('--command', ('"' + $taskInput + '"'), '--report', ('"' + $taskReply + '"'))
    if ($Port) { $taskArgs += @('--port', $Port) }
    if ($Start) { $taskArgs += '--start' }
    if ($DataDir) { $taskArgs += @('--data-dir', ('"' + $DataDir + '"')) }
    $taskProcess = Start-Process -FilePath (Join-Path $PSScriptRoot 'CAM Local.exe') -ArgumentList $taskArgs -WindowStyle Hidden -PassThru
    # Start-Process -Wait follows the entire child tree, including the GUI
    # opened by --start. Wait only for the command process itself.
    $taskProcess.WaitForExit()
    if (Test-Path -LiteralPath $taskReply) { Get-Content -LiteralPath $taskReply -Raw }
    else { throw 'O executável não escreveu o relatório. Consulte %LOCALAPPDATA%/CAMLocal/erro-desktop.txt.' }
    if ($taskProcess.ExitCode -ne 0) { throw "Falha no comando CAM (exit $($taskProcess.ExitCode)). Veja o JSON acima." }
} finally {
    # Only delete the exact two files created in our fresh temporary directory.
    foreach ($taskFile in @('command.json', 'reply.json')) {
        $taskPath = Join-Path $taskTemp $taskFile
        if (Test-Path -LiteralPath $taskPath) { Remove-Item -LiteralPath $taskPath -Force }
    }
    Remove-Item -LiteralPath $taskTemp -Force
}
