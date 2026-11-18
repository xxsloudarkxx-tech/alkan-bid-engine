param(
  [string]$InputFile,
  [string]$OutputDir,
  [string]$Changes,
  [string[]]$PriceList,
  [string]$Supplier,
  [switch]$Best,
  [switch]$AutoAssign,
  [switch]$Build,
  [switch]$ForcePct,
  [switch]$ListSuppliers
)
# Cambiar precios o proveedores de un estimado y volver a generar el paquete.
# Ejemplos:
#   .\Start-Reprice.ps1 -ListSuppliers
#   .\Start-Reprice.ps1 -InputFile examples\packages\hc3_ss.json -Changes examples\cambios\hc3_ss_cambios.csv -OutputDir ENTREGAS\HC3_R1 -Build
#   .\Start-Reprice.ps1 -InputFile examples\packages\wsj.json -PriceList examples\cambios\lista_precios_demo.csv -Best -OutputDir ENTREGAS\WSJ_R1 -Build
#   .\Start-Reprice.ps1 -InputFile examples\packages\orangegate.json -AutoAssign -OutputDir ENTREGAS\OG_PROV -Build
$ErrorActionPreference = 'Stop'
$env:PYTHONPATH = Join-Path $PSScriptRoot 'src'
$alkanPy = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $alkanPy)) { $alkanPy = 'python' }
$alkanArgs = @('-m', 'bidkit.reprice')
if ($ListSuppliers) { $alkanArgs += '--list-suppliers' }
if ($InputFile) { $alkanArgs += $InputFile }
if ($OutputDir) { $alkanArgs += @('--out', $OutputDir) }
if ($Changes) { $alkanArgs += @('--changes', $Changes) }
foreach ($p in $PriceList) { $alkanArgs += @('--price-list', $p) }
if ($Supplier) { $alkanArgs += @('--supplier', $Supplier) }
if ($Best) { $alkanArgs += '--best' }
if ($AutoAssign) { $alkanArgs += '--auto-assign' }
if ($Build) { $alkanArgs += '--build' }
if ($ForcePct) { $alkanArgs += '--force-pct' }
& $alkanPy @alkanArgs
exit $LASTEXITCODE
