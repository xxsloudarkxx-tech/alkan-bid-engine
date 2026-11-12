param(
  [Parameter(Mandatory=$true)][ValidateSet('inventario','alcance','hoja','takeoff','rfq','supuestos')][string]$Phase,
  [Parameter(Mandatory=$true)][string]$InputFile,
  [string]$SourcesFile,
  [string[]]$Image = @(),
  [switch]$TextMode
)
$ErrorActionPreference = 'Stop'
$env:PYTHONPATH = Join-Path $PSScriptRoot 'src'
$alkanAgentPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $alkanAgentPython)) { $alkanAgentPython = 'python' }
$alkanAgentArgs = @('-m','bidkit.rfq_agent','--root',$PSScriptRoot,'--phase',$Phase,'--input',$InputFile)
if ($SourcesFile) { $alkanAgentArgs += @('--sources',$SourcesFile) }
foreach ($alkanAgentImage in $Image) { $alkanAgentArgs += @('--image',$alkanAgentImage) }
if ($TextMode) { $alkanAgentArgs += '--text-mode' }
& $alkanAgentPython @alkanAgentArgs
exit $LASTEXITCODE
