# Opt-in local integration test. Requires ports 8000/3000 to be free.
# Starts the real app, but never calls Canvas, parsing or knowledge endpoints.
. (Join-Path $PSScriptRoot 'common.ps1')
Initialize-Launcher
if ((Test-Listening 8000) -or (Test-Listening 3000)) {
    throw 'Stop existing servers before running launcher tests. This test will not stop unowned processes.'
}
$shell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$sentinels = @()
function Assert-Check([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw "FAIL: $Message" }
    Write-Host "PASS: $Message"
}
function Invoke-Launcher([string]$Name) {
    $args = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $PSScriptRoot $Name))
    if ($Name -eq 'start-studyflow.ps1') { $args += '-NoBrowser' }
    & $shell @args
    Assert-Check ($LASTEXITCODE -eq 0) $Name
}
try {
    # Independent Python/Node workloads must survive the stop scenario.
    $sentinels += Start-Process (Join-Path $script:ProjectRoot 'backend\.venv\Scripts\python.exe') `
        -ArgumentList '-c "import time; time.sleep(180)"' -WindowStyle Hidden -PassThru
    $sentinels += Start-Process (Get-Command node.exe).Source `
        -ArgumentList '-e "setInterval(()=>{},1000)"' -WindowStyle Hidden -PassThru
    # Two near-simultaneous double-clicks must serialize startup through the mutex.
    $startArgs = '-NoProfile -ExecutionPolicy Bypass -File "{0}" -NoBrowser' -f (Join-Path $PSScriptRoot 'start-studyflow.ps1')
    $launches = @()
    foreach ($number in @(1, 2)) {
        $launched = Start-Process $shell -ArgumentList $startArgs -WindowStyle Hidden -PassThru `
            -RedirectStandardOutput (Join-Path $script:RuntimeRoot "test-start-$number.log") `
            -RedirectStandardError (Join-Path $script:RuntimeRoot "test-start-$number.error.log")
        # Windows PowerShell 5.1 needs the handle retained to read ExitCode after exit.
        $null = $launched.Handle
        $launches += $launched
    }
    foreach ($launch in $launches) {
        Assert-Check ($launch.WaitForExit(90000)) 'Concurrent launcher completed within deadline'
        Assert-Check ($launch.ExitCode -eq 0) 'Concurrent launcher succeeded'
    }
    Assert-Check ((Test-Ready 'backend') -and (Test-Ready 'frontend')) 'A: cold startup, health and frontend ready'
    $backend = Get-OwnedProcess 'backend'
    $frontend = Get-OwnedProcess 'frontend'
    Assert-Check ($null -ne $backend -and $null -ne $frontend) 'Both process identities recorded'
    Invoke-Launcher 'start-studyflow.ps1'
    Assert-Check ((Get-OwnedProcess 'backend').Pid -eq $backend.Pid -and
        (Get-OwnedProcess 'frontend').Pid -eq $frontend.Pid) 'B: repeated start reuses the same server processes'

    # A stale PID file pointing at a live unrelated node process must not kill it.
    $statePath = Get-StatePath 'frontend'
    $saved = Get-Content -LiteralPath $statePath -Raw
    $fake = $saved | ConvertFrom-Json
    $fake.Process = Get-ProcessIdentity $sentinels[1].Id
    $fake.Process.Created = '2000-01-01T00:00:00.0000000Z'
    $fake | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $statePath -Encoding UTF8
    try {
        Stop-OwnedServer 'frontend'
        Assert-Check (-not $sentinels[1].HasExited -and (Test-Ready 'frontend')) 'Stale PID reuse does not terminate unrelated or live app processes'
    } finally { Set-Content -LiteralPath $statePath -Value $saved -Encoding UTF8 }

    Invoke-Launcher 'stop-studyflow.ps1'
    Assert-Check (-not (Test-Listening 8000) -and -not (Test-Listening 3000)) 'C: owned backend/frontend listeners stopped'
    foreach ($sentinel in $sentinels) {
        Assert-Check (-not $sentinel.HasExited) 'Unrelated Python/Node workload survived'
    }
    Invoke-Launcher 'start-studyflow.ps1'
    Assert-Check ((Test-Ready 'backend') -and (Test-Ready 'frontend')) 'D: restart after stop succeeds'
} finally {
    Invoke-Launcher 'stop-studyflow.ps1'
    foreach ($sentinel in $sentinels) {
        if (-not $sentinel.HasExited) {
            # Only locally created test processes, using their original handles.
            $null = & "$env:SystemRoot\System32\taskkill.exe" /PID $sentinel.Id /T /F 2>&1
        }
    }
}
