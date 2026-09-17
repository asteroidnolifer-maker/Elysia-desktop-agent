<#
    Elysia installer - Windows (PowerShell 5.1+ or PowerShell 7+).
    Thin shim: locates Python 3.8+ and runs the universal installer.

        .\install.ps1                 check prerequisites, create dirs/config
        .\install.ps1 -Deps           also install missing prerequisites
        .\install.ps1 -Build          build agent-core (needs Go)
        .\install.ps1 -WithModel      fetch llama-server + a GGUF model
        .\install.ps1 -DryRun         show every action, change nothing

    If PowerShell blocks the script, run once:
        powershell -ExecutionPolicy Bypass -File .\install.ps1
    or just double-click install.cmd
#>
[CmdletBinding()]
param(
    [switch]$Deps,
    [switch]$Build,
    [switch]$WithModel,
    [switch]$NoVerify,
    [switch]$DryRun,
    [switch]$Yes,
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
    Write-Host '         (or https://www.python.org/downloads/ - tick "Add python.exe to PATH")'
    exit 1
}

$bootArgs = @("$Root\scripts\elysia_boot.py", 'install')
if ($Deps)      { $bootArgs += '--deps' }
if ($Build)     { $bootArgs += '--build' }
if ($WithModel) { $bootArgs += '--with-model' }
if ($NoVerify)  { $bootArgs += '--no-verify' }
if ($DryRun)    { $bootArgs += '--dry-run' }
if ($Yes)       { $bootArgs += '--yes' }
if ($Rest)      { $bootArgs += $Rest }

& $pyExe @pyPre @bootArgs
exit $LASTEXITCODE
