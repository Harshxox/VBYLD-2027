param([switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$python = Join-Path $root 'ergo_ml_backend\.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Install the backend environment first; see README.md.' }
$node = (Get-Command node.exe -ErrorAction SilentlyContinue).Source
if (-not $node) {
    $bundled = Get-ChildItem -Path 'C:\Program Files\WindowsApps\OpenAI.CodexPrimaryRuntime.*\dependencies\node\bin\node.exe' -ErrorAction SilentlyContinue | Select-Object -Last 1
    if ($bundled) { $node = $bundled.FullName }
}
if (-not $node) { throw 'Node.js 22.12 or newer is required.' }
function Free-Port([int]$start) {
    foreach ($candidate in $start..($start + 50)) {
        $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $candidate)
        try { $listener.Start(); return $candidate } catch {} finally { $listener.Stop() }
    }
    throw 'No free local port found.'
}
$backendPort = Free-Port 8000
$frontendPort = Free-Port 5173
$env:ALLOWED_ORIGINS = "http://127.0.0.1:$frontendPort,http://localhost:$frontendPort"
$env:VITE_API_BASE = "http://127.0.0.1:$backendPort"
& $python (Join-Path $root 'scripts\configure_local.py')
$logs = Join-Path $root 'logs'
New-Item -ItemType Directory -Force -Path $logs | Out-Null
$children = @()
try {
    $api = Start-Process -FilePath $python -ArgumentList @('-m','uvicorn','app.main:app','--host','127.0.0.1','--port',"$backendPort") -WorkingDirectory (Join-Path $root 'ergo_ml_backend') -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logs 'backend.log') -RedirectStandardError (Join-Path $logs 'backend-error.log')
    $children += $api
    $ready = $false
    for ($i=0; $i -lt 60; $i++) {
        if ($api.HasExited) { throw 'Backend stopped. See logs/backend-error.log.' }
        try { $r = Invoke-RestMethod "$env:VITE_API_BASE/health" -TimeoutSec 2; if ($r.status -eq 'ok') { $ready=$true; break } } catch {}
        Start-Sleep -Milliseconds 500
    }
    if (-not $ready) { throw 'Backend startup timed out.' }
    $vite = '"' + (Join-Path $root 'node_modules\vite\bin\vite.js') + '"'
    $web = Start-Process -FilePath $node -ArgumentList @($vite,'--host','127.0.0.1','--port',"$frontendPort",'--strictPort') -WorkingDirectory $root -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logs 'frontend.log') -RedirectStandardError (Join-Path $logs 'frontend-error.log')
    $children += $web
    $url = "http://127.0.0.1:$frontendPort"
    $state = @{ backendUrl=$env:VITE_API_BASE; frontendUrl=$url; processes=@($children | ForEach-Object { @{id=$_.Id; started=$_.StartTime.ToUniversalTime().ToString('o')} }) }
    $state | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $logs 'local-run.json')
    $webReady = $false
    for ($i=0; $i -lt 40; $i++) {
        if ($web.HasExited) { throw 'Frontend stopped. See logs/frontend-error.log.' }
        try { Invoke-WebRequest $url -UseBasicParsing -TimeoutSec 2 | Out-Null; $webReady=$true; break } catch { Start-Sleep -Milliseconds 300 }
    }
    if (-not $webReady) { throw 'Frontend startup timed out.' }
    if (-not $NoBrowser) { Start-Process $url }
    Write-Output "ErgoCare: $url"
    Write-Output "API: $env:VITE_API_BASE"
} catch {
    foreach ($child in $children) { if (-not $child.HasExited) { & taskkill.exe /PID $child.Id /T /F | Out-Null } }
    throw
}
