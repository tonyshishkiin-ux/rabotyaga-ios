param(
    [ValidateSet('serve', 'pair', 'devices', 'revoke')]
    [string]$Action = 'serve',
    [string]$DeviceName = 'iPhone Работяги',
    [string]$DeviceId = ''
)

$ErrorActionPreference = 'Stop'
$gatewayHermesHome = Join-Path $env:LOCALAPPDATA 'hermes'
$facts = Get-ChildItem -LiteralPath (Join-Path $gatewayHermesHome 'installs') -Filter 'facts.json' -Recurse |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
if (-not $facts) { throw 'Hermes dependency environment was not found.' }

$metadata = Get-Content -LiteralPath $facts.FullName -Raw | ConvertFrom-Json
$venv = [string]$metadata.packages.venv.environment
$python = Join-Path $venv 'Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'The active Hermes Python environment is missing.' }

$projectRoot = Split-Path -Parent $PSScriptRoot
$env:HERMES_HOME = $gatewayHermesHome
$env:PYTHONPATH = "$(Join-Path $projectRoot 'gateway');$(Join-Path $gatewayHermesHome 'hermes-agent')"

$arguments = @('-m', 'rabotyaga_gateway', $Action)
if ($Action -eq 'pair') { $arguments += @('--name', $DeviceName) }
if ($Action -eq 'revoke') {
    if (-not $DeviceId) { throw 'DeviceId is required for revoke.' }
    $arguments += $DeviceId
}

& $python @arguments
