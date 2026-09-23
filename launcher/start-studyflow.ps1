param(
    [switch]$NoBrowser,
    [ValidateRange(1, 180)][int]$TimeoutSeconds = 60
)
. (Join-Path $PSScriptRoot 'common.ps1')
$lock = $null
$started = @()
try {
    Initialize-Launcher
    $lock = Enter-LauncherLock
    Write-Status 'Starting StudyFlow...'
    foreach ($role in @('backend', 'frontend')) {
        $port = if ($role -eq 'backend') { 8000 } else { 3000 }
        if (Test-Ready $role) {
            Write-Status "$role is already running; reusing it."
        } else {
            if ($null -eq (Get-OwnedProcess $role) -and -not (Test-Listening $port)) {
                Start-OwnedServer $role
                $started += $role
            } else { Write-Status "Waiting for existing $role on port $port..." }
            Wait-Ready $role $TimeoutSeconds
        }
        Write-Status "$role ready."
    }
    if (-not $NoBrowser) {
        Write-Status 'Opening StudyFlow...'
        # Interactive browser opening is intentional; only servers are hidden.
        Start-Process $script:FrontendUrl
    }
    Write-Status 'StudyFlow is ready.'
} catch {
    Write-Host ('Startup failed: ' + $_.Exception.Message) -ForegroundColor Red
    if ($null -ne $lock) {
        Write-Status 'StudyFlow startup failed. Check the runtime logs and the message in this window.'
    }
    if ($null -ne $lock) {
        foreach ($role in @('frontend', 'backend')) {
            if ($started -contains $role) {
                try { Stop-OwnedServer $role } catch { Write-Host "Could not clean up $role; use Stop StudyFlow." }
            }
        }
    }
    exit 1
} finally {
    if ($null -ne $lock) { $lock.ReleaseMutex(); $lock.Dispose() }
}
