@echo off
setlocal DisableDelayedExpansion
rem Run normally, never as administrator. Do not run during an update or UAC prompt.
rem The application folder is this file's directory (normally C:\Program Files\Clock Overlay).
set "OVERLAY_APP=%~dp0"
set "OVERLAY_BATCH=%~f0"
set "OVERLAY_PYTHON=C:\Program Files\Python314\pythonw.exe"
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -NonInteractive -Command "$ErrorActionPreference='Stop'; try { $text=[IO.File]::ReadAllText($env:OVERLAY_BATCH); $marker='# POWERSHELL'+' PAYLOAD'; & ([scriptblock]::Create($text.Substring($text.LastIndexOf($marker)+$marker.Length))) } catch { [Console]::Error.WriteLine($_.Exception.Message); exit 1 }"
if errorlevel 1 (
  echo Overlay restart failed. Review the error above; no automatic retry.
  pause
  exit /b 1
)
exit /b 0
# POWERSHELL PAYLOAD
$ErrorActionPreference = 'Stop'
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if ($principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Run overlay.bat normally, NOT as administrator.'
}
$app = [IO.Path]::GetFullPath($env:OVERLAY_APP).TrimEnd([char]92)
$python = $env:OVERLAY_PYTHON
$scripts = @('clock_overlay_v3.py', 'ip_overlay.py', 'cchl_cal_overlay.py', 'ceel_cal_overlay.py')
$lock = Join-Path $app '.overlay-update.lock'
if (Test-Path -LiteralPath $lock) { throw 'Update lock present. Do not restart until the update/recovery is complete.' }
foreach ($file in @($python) + @($scripts | ForEach-Object { Join-Path $app $_ })) {
    if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { throw "Required file missing: $file" }
}
Set-Location -LiteralPath $app
# Prevent simultaneous launcher instances for this installation, without requiring app write access.
$sha = [Security.Cryptography.SHA256]::Create()
$key = [BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::Unicode.GetBytes($app.ToLowerInvariant()))).Replace('-', '')
$mutex = New-Object Threading.Mutex($false, ('Local\WindowsOverlays-' + $key))
$owned = $false
try {
    try { $owned = $mutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $owned = $true }
    if (-not $owned) { throw 'Another overlay launcher is running.' }
    # Only the exact interpreter and exact quoted full script argument are matched.
    # No basename matching, taskkill, or updater-child termination.
    $patterns = @($scripts | ForEach-Object {
        '(?i)^\s*"?' + [regex]::Escape($python) + '"?\s+"' + [regex]::Escape((Join-Path $app $_)) + '"\s*$'
    })
    $targets = @(Get-CimInstance Win32_Process -Filter "Name = 'pythonw.exe'" | Where-Object {
        $process = $_
        $process.ExecutablePath -ieq $python -and @($patterns | Where-Object { $process.CommandLine -match $_ }).Count -gt 0
    })
    # Acquire process handles before stopping: wait on the same objects, not recycled PIDs.
    $handles = @($targets | ForEach-Object {
        $process = Get-Process -Id $_.ProcessId -ErrorAction Stop
        $null = $process.Handle
        # Bind the CIM observation to this process instance before any termination.
        if ($process.StartTime.ToUniversalTime().ToString('yyyyMMddHHmmssffffff') -ne $_.CreationDate.ToUniversalTime().ToString('yyyyMMddHHmmssffffff')) {
            throw 'Process identity changed during inspection. No overlays stopped.'
        }
        $process
    })
    if (Test-Path -LiteralPath $lock) { throw 'Update started; restart cancelled.' }
    foreach ($process in $handles) {
        if (-not $process.HasExited) { $process.Kill() }
    }
    foreach ($process in $handles) {
        if (-not $process.WaitForExit(10000)) { throw 'An old overlay did not exit. No replacement overlays started.' }
    }
    if (Test-Path -LiteralPath $lock) { throw 'Update started; overlays stopped but not restarted.' }
    $started = @()
    try {
        foreach ($script in $scripts) {
            $started += Start-Process -FilePath $python -ArgumentList ('"' + (Join-Path $app $script) + '"') -WorkingDirectory $app -PassThru -ErrorAction Stop
        }
    } catch {
        foreach ($process in $started) {
            if (-not $process.HasExited) { $process.Kill(); $null = $process.WaitForExit(10000) }
        }
        throw
    }
} finally {
    if ($owned) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
