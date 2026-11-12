param(
  [string]$Tool = 'esquemas',
  [string]$InputFile,
  [string]$OutputFile
)
$ErrorActionPreference = 'Stop'
$env:PYTHONPATH = Join-Path $PSScriptRoot 'src'
$alkanRfqArgs = @('-m', 'bidkit.rfq_cli', $Tool)
if ($InputFile) { $alkanRfqArgs += @('--input', $InputFile) }
if ($OutputFile) { $alkanRfqArgs += @('--output', $OutputFile) }
$alkanRfqPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $alkanRfqPython)) { $alkanRfqPython = 'python' }
& $alkanRfqPython @alkanRfqArgs
exit $LASTEXITCODE
