param(
  [Parameter(Mandatory = $true)][string]$InputFile,
  [string]$OutputDir
)
# Revisar un estimado con el criterio de Don Miguel (no cambia precios).
#   .\Start-Criterio.ps1 -InputFile examples\packages\hc3_ss.json -OutputDir ENTREGAS\HC3_CRITERIO
$ErrorActionPreference = 'Stop'
$env:PYTHONPATH = Join-Path $PSScriptRoot 'src'
$alkanPy = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $alkanPy)) { $alkanPy = 'python' }
$alkanArgs = @('-m', 'bidkit.criterio', $InputFile)
if ($OutputDir) { $alkanArgs += @('--out', $OutputDir) }
& $alkanPy @alkanArgs
exit $LASTEXITCODE
