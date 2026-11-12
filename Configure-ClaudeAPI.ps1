param(
  [string]$Model = 'claude-fable-5-2'
)
# Carga la clave de la API de Anthropic SOLO en esta ventana de PowerShell (no se guarda en archivos).
# Obtenga la clave en https://console.anthropic.com  ->  API Keys.
$ErrorActionPreference = 'Stop'
$alkanClaudeSecret = Read-Host 'Clave de la API de Anthropic (no se guarda)' -AsSecureString
$alkanClaudePtr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($alkanClaudeSecret)
try { $env:ANTHROPIC_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($alkanClaudePtr) }
finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($alkanClaudePtr) }
$env:BIDKIT_CLAUDE_MODEL = $Model
Write-Output "Listo. Modelo: $Model. Ejecute .\Start-EstimateAgent.ps1 desde esta misma ventana."
