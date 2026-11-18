param(
    [string]$BindHost = "0.0.0.0",
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$env:PYTHONPATH = Join-Path $Root "src"
$env:BIDKIT_ROOT = $Root

Write-Host "Iniciando ALKAN Bid Engine Mobile API en http://${BindHost}:${Port}" -ForegroundColor Cyan
python -m bidkit.mobile_api --root $Root --host $BindHost --port $Port
