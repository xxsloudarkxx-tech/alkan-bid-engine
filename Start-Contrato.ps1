param(
  [Parameter(Mandatory = $true)][string]$Cliente,
  [Parameter(Mandatory = $true)][string[]]$Paquete,
  [string]$OutputDir = 'ENTREGAS\CONTRATOS',
  [switch]$Estricto
)
# Contrato con alcance preconfigurado: el perfil del cliente pone marca, logo, tarifas,
# markups, exclusiones y supuestos; el paquete pone cantidades, horas y alcance.
# Ejemplos:
#   .\Start-Contrato.ps1 -Cliente diaz -Paquete examples\packages\madison_carpinteria.json
#   .\Start-Contrato.ps1 -Cliente "jc granite" -Paquete 'examples\packages\*.json' -Estricto
#   .\Start-Contrato.ps1 -Cliente listar -Paquete x      (o:  python -m bidkit.contrato listar)
$ErrorActionPreference = 'Stop'
$env:PYTHONPATH = Join-Path $PSScriptRoot 'src'
$py = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $py)) { $py = 'python' }
if ($Cliente -eq 'listar') { & $py -m bidkit.contrato listar; exit $LASTEXITCODE }
$files = @()
foreach ($p in $Paquete) { $files += (Get-ChildItem -Path $p -File | ForEach-Object { $_.FullName }) }
$cmd = @('-m', 'bidkit.contrato', 'hacer', '--cliente', $Cliente, '--out', $OutputDir, '--paquete') + $files
if ($Estricto) { $cmd += '--estricto' }
& $py @cmd
exit $LASTEXITCODE
