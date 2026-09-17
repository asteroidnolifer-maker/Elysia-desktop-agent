<#
    Elysia launcher - Windows (PowerShell 5.1+ or PowerShell 7+).
    Thin shim around the universal launcher (scripts\elysia_boot.py).

        .\start.ps1                     start model API + agent-core + HUD
        .\start.ps1 -NoModel            start only agent-core + HUD
        .\start.ps1 -Bind 0.0.0.0       expose the HUD on your network
        .\start.ps1 -Action stop        stop everything this script started
        .\start.ps1 -Action status      ports, pids, board summary
        .\start.ps1 -Action doctor      repository health check

    If PowerShell blocks the script, run once:
        powershell -ExecutionPolicy Bypass -File .\start.ps1
    or just double-click start.cmd
#>
[CmdletBinding()]
param(
    [ValidateSet('start', 'stop', 'restart', 'status', 'doctor')]
    [string]$Action = 'start',
    [string]$Bind = '127.0.0.1',
    [int]$Port = 0,
    [switch]$NoModel,
    [switch]$NoAgent,
    [switch]$NoHud,
    [switch]$DryRun,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Rest
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path

# Find a Python 3.8+ launcher. `py -3` is checked first because the Windows
# Store `python.exe` stub exists but does not actually run Python.
$pyExe = $null
$pyPre = @()
foreach ($candidate in @('py', 'python', 'python3')) {
    if (-not (Get-Command $candidate -ErrorAction SilentlyContinue)) { continue }
    $probe = @()
    if ($candidate -eq 'py') { $probe = @('-3') }
    & $candidate @probe -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' 2>$null
    if ($LASTEXITCODE -eq 0) { $pyExe = $candidate; $pyPre = $probe; break }
}

if (-not $pyExe) {
    Write-Host '[elysia] Python 3.8+ is required but was not found on PATH.' -ForegroundColor Red
    Write-Host '         Install it with:  winget install -e --id Python.Python.3.12'
    exit 1
}

$bootArgs = @("$Root\scripts\elysia_boot.py", $Action)
if ($Action -eq 'start' -or $Action -eq 'restart') {
    if ($Bind) { $bootArgs += @('--host', $Bind) }
    if ($Port -gt 0) { $bootArgs += @('--port', "$Port") }
    if ($NoModel) { $bootArgs += '--no-model' }
    if ($NoAgent) { $bootArgs += '--no-agent' }
    if ($NoHud)   { $bootArgs += '--no-hud' }
}
if ($DryRun) { $bootArgs += '--dry-run' }
if ($Rest)   { $bootArgs += $Rest }

& $pyExe @pyPre @bootArgs
exit $LASTEXITCODE
