$ErrorActionPreference = 'Stop'
$path = Join-Path $PSScriptRoot 'logs\local-run.json'
if (-not (Test-Path -LiteralPath $path)) { Write-Output 'No tracked local run.'; exit }
$state = Get-Content -LiteralPath $path -Raw | ConvertFrom-Json
foreach ($tracked in $state.processes) {
    $process = Get-Process -Id $tracked.id -ErrorAction SilentlyContinue
    if ($process -and $process.StartTime.ToUniversalTime().ToString('o') -eq $tracked.started) {
        # A venv redirector can own a child Python process; stop the tracked tree.
        & taskkill.exe /PID $process.Id /T /F | Out-Null
    }
}
Remove-Item -LiteralPath $path
Write-Output 'Stopped the tracked ErgoCare servers.'
