# Shared Windows PowerShell 5.1+ helpers. Never load or print environment secrets.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$script:ProjectRoot = Split-Path -Parent $PSScriptRoot
$script:RuntimeRoot = Join-Path $script:ProjectRoot '.runtime'
$script:LogRoot = Join-Path $script:ProjectRoot 'logs'
$script:BackendUrl = 'http://127.0.0.1:8000'
$script:FrontendUrl = 'http://localhost:3000'

function Initialize-Launcher {
    New-Item -ItemType Directory -Force -Path $script:RuntimeRoot, $script:LogRoot | Out-Null
}

function Write-Status([string]$Message) {
    Write-Host $Message
    Add-Content -LiteralPath (Join-Path $script:LogRoot 'launcher.log') -Encoding UTF8 -Value (
        '{0} {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Message)
}

function Enter-LauncherLock {
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $hash = [BitConverter]::ToString($sha.ComputeHash(
            [Text.Encoding]::UTF8.GetBytes($script:ProjectRoot.ToUpperInvariant()))).Replace('-', '')
    } finally { $sha.Dispose() }
    $mutex = New-Object System.Threading.Mutex($false, "Local\StudyFlow-$hash")
    try {
        try { $acquired = $mutex.WaitOne(60000) }
        catch [System.Threading.AbandonedMutexException] { $acquired = $true }
        if (-not $acquired) { throw 'Another StudyFlow launcher is busy. Try again shortly.' }
        return $mutex
    } catch { $mutex.Dispose(); throw }
}

function Get-StatePath([string]$Role) { Join-Path $script:RuntimeRoot "$Role.json" }

function Get-ProcessIdentity([int]$ProcessId) {
    $process = Get-CimInstance Win32_Process -Filter "ProcessId=$ProcessId"
    if ($null -eq $process) { return $null }
    [pscustomobject]@{
        Pid = [int]$process.ProcessId
        Created = $process.CreationDate.ToUniversalTime().ToString('o')
        Executable = [string]$process.ExecutablePath
        CommandLine = [string]$process.CommandLine
    }
}

function Get-OwnedProcess([string]$Role) {
    $path = Get-StatePath $Role
    if (-not (Test-Path -LiteralPath $path)) { return $null }
    try {
        $state = Get-Content -LiteralPath $path -Raw | ConvertFrom-Json
        if ($state.Root -ne $script:ProjectRoot -or $state.Role -ne $Role) { return $null }
        $actual = Get-ProcessIdentity $state.Process.Pid
        if ($null -ne $actual -and $actual.Created -ceq $state.Process.Created -and
            $actual.Executable -eq $state.Process.Executable -and
            $actual.CommandLine -ceq $state.Process.CommandLine) { return $actual }
    } catch {
        # A corrupt/stale PID record must never authorize termination.
        Write-Status "Cannot verify saved $Role process; leaving it untouched."
    }
    return $null
}

function Save-OwnedProcess([string]$Role, [int]$ProcessId) {
    $identity = Get-ProcessIdentity $ProcessId
    if ($null -eq $identity -or -not $identity.Executable -or -not $identity.CommandLine) {
        throw "Cannot record $Role process ownership. See logs/$Role.error.log."
    }
    @{ Root = $script:ProjectRoot; Role = $Role; Process = $identity } |
        ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Get-StatePath $Role) -Encoding UTF8
}

function Test-Listening([int]$Port) {
    return @([System.Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners() |
        Where-Object { $_.Port -eq $Port }).Count -gt 0
}

function Test-Ready([string]$Role) {
    try {
        if ($Role -eq 'backend') {
            $health = Invoke-WebRequest "$script:BackendUrl/health" -UseBasicParsing -TimeoutSec 2
            if ($health.StatusCode -ne 200 -or ($health.Content | ConvertFrom-Json).status -ne 'ok') { return $false }
            $api = Invoke-RestMethod "$script:BackendUrl/openapi.json" -TimeoutSec 2
            return $api.info.title -eq 'StudyFlow API'
        }
        $page = Invoke-WebRequest 'http://127.0.0.1:3000' -UseBasicParsing -TimeoutSec 2
        return $page.StatusCode -eq 200 -and $page.Content -match '<title>StudyFlow' -and $page.Content -match '/_next/'
    } catch { return $false }
}

function Wait-Ready([string]$Role, [int]$TimeoutSeconds) {
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        if (Test-Ready $Role) { return }
        Start-Sleep -Milliseconds 400
    } while ([DateTime]::UtcNow -lt $deadline)
    throw "StudyFlow $Role failed to start. Check logs/$Role.log and logs/$Role.error.log; its port may be occupied by another app."
}

function Start-OwnedServer([string]$Role) {
    $python = Join-Path $script:ProjectRoot 'backend\.venv\Scripts\python.exe'
    if ($Role -eq 'backend') {
        if (-not (Test-Path -LiteralPath $python)) {
            throw 'StudyFlow backend failed to start. Missing backend\.venv; follow README installation first.'
        }
        $executable = $python
        $arguments = '-m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log'
        $working = Join-Path $script:ProjectRoot 'backend'
    } else {
        $node = Get-Command node.exe -ErrorAction SilentlyContinue
        $next = Join-Path $script:ProjectRoot 'frontend\node_modules\next\dist\bin\next'
        if ($null -eq $node -or -not (Test-Path -LiteralPath $next)) {
            throw 'StudyFlow frontend failed to start. Install Node.js and run npm ci in frontend first.'
        }
        if (-not (Test-Path -LiteralPath (Join-Path $script:ProjectRoot 'frontend\.next\BUILD_ID'))) {
            throw 'StudyFlow frontend failed to start. Run npm run build in frontend first.'
        }
        $executable = $node.Source
        # Exactly the package.json `next start` entry, invoked directly so ownership
        # does not depend on a detached npm/cmd wrapper. Quote paths with spaces.
        $arguments = '"{0}" start --hostname 127.0.0.1 --port 3000' -f $next
        $working = Join-Path $script:ProjectRoot 'frontend'
    }
    Write-Status "Starting $Role..."
    $process = Start-Process -FilePath $executable -ArgumentList $arguments -WorkingDirectory $working `
        -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $script:LogRoot "$Role.log") `
        -RedirectStandardError (Join-Path $script:LogRoot "$Role.error.log")
    try { Save-OwnedProcess $Role $process.Id }
    catch {
        # This is the freshly returned process handle, never a PID loaded from disk.
        if (-not $process.HasExited) { $process.Kill() }
        throw
    }
}

function Stop-OwnedServer([string]$Role) {
    $owned = Get-OwnedProcess $Role
    if ($null -eq $owned) {
        Write-Status "No verified launcher-owned $Role process to stop; other servers are left running."
        return
    }
    # PID + creation time + executable + complete command line protect against
    # stale PID reuse. /T also stops the venv Python redirector's child interpreter.
    $null = & "$env:SystemRoot\System32\taskkill.exe" /PID $owned.Pid /T /F 2>&1
    if ($LASTEXITCODE -ne 0 -and $null -ne (Get-OwnedProcess $Role)) {
        throw "Could not stop launcher-owned $Role. See logs/launcher.log."
    }
    Remove-Item -LiteralPath (Get-StatePath $Role) -ErrorAction SilentlyContinue
    Write-Status "Stopped $Role."
}
