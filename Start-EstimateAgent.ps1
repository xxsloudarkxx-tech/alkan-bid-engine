param(
  [Parameter(Mandatory = $true)][string]$Docs,
  [Parameter(Mandatory = $true)][string]$Key,
  [string]$Profile = 'profiles\ss_custom_iron_works.json',
  [string]$OutputDir,
  [string]$Notes = '',
  [int]$MaxTurns = 120,
  [switch]$NoWeb
)
# Agente estimador ALKAN: planos/specs/addenda (carpeta o ZIP) -> 01 Cost Analysis, 02 Material List, 03 Proposal + reporte.
# Ejemplo: .\Start-EstimateAgent.ps1 -Docs 'C:\Users\...\Gonyea Playfield.zip' -Key GONYEA
$ErrorActionPreference = 'Stop'
if (-not $env:ANTHROPIC_API_KEY) { Write-Error 'Primero ejecute .\Configure-ClaudeAPI.ps1 en esta ventana.' }
if (-not $OutputDir) { $OutputDir = Join-Path 'ENTREGAS\AGENTE' $Key }
$env:PYTHONPATH = Join-Path $PSScriptRoot 'src'
$alkanAgentPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $alkanAgentPython)) { $alkanAgentPython = 'python' }
$alkanAgentArgs = @('-m', 'bidkit.estimator_agent.agent', '--docs', $Docs, '--key', $Key, '--profile', $Profile, '--out', $OutputDir, '--max-turns', $MaxTurns)
if ($Notes) { $alkanAgentArgs += @('--notes', $Notes) }
if ($NoWeb) { $alkanAgentArgs += '--no-web' }
& $alkanAgentPython @alkanAgentArgs
exit $LASTEXITCODE
