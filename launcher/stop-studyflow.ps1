. (Join-Path $PSScriptRoot 'common.ps1')
$lock = $null
try {
    Initialize-Launcher
    $lock = Enter-LauncherLock
    Write-Status 'Stopping launcher-owned StudyFlow servers...'
    foreach ($role in @('frontend', 'backend')) { Stop-OwnedServer $role }
    Write-Status 'Stop complete.'
} catch {
    Write-Host ('Stop failed: ' + $_.Exception.Message) -ForegroundColor Red
    exit 1
} finally {
    if ($null -ne $lock) { $lock.ReleaseMutex(); $lock.Dispose() }
}
