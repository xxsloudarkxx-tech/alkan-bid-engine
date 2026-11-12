param(
  [Parameter(Mandatory = $true)][string[]]$InputFile,
  [string]$OutputDir = 'ENTREGAS\PAQUETES'
)
# Paquete ALKAN de 3 documentos: 01 Cost Analysis, 02 Material List, 03 Estimate/Proposal.
# Ejemplo:  .\Start-Package.ps1 -InputFile examples\packages\wsj.json -OutputDir ENTREGAS\WSJ
#           .\Start-Package.ps1 -InputFile 'examples\packages\*.json'
$ErrorActionPreference = 'Stop'
$env:PYTHONPATH = Join-Path $PSScriptRoot 'src'
$alkanPkgPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $alkanPkgPython)) { $alkanPkgPython = 'python' }
$alkanPkgArgs = @('-m', 'bidkit.package_build') + $InputFile + @('--out', $OutputDir)
& $alkanPkgPython @alkanPkgArgs
exit $LASTEXITCODE
