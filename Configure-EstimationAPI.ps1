param(
  [Parameter(Mandatory=$true)][string]$BaseUrl,
  [Parameter(Mandatory=$true)][string]$Model,
  [string]$AuditModel,
  [switch]$Vision
)
$ErrorActionPreference = 'Stop'
$alkanApiSecret = Read-Host 'Clave de la API (no se guarda en archivos)' -AsSecureString
$alkanApiPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($alkanApiSecret)
try { $env:BIDKIT_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($alkanApiPointer) }
finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($alkanApiPointer) }
$env:BIDKIT_API_BASE = $BaseUrl
$env:BIDKIT_MODEL = $Model
$env:BIDKIT_AUDIT_MODEL = $AuditModel
$env:BIDKIT_VISION = if ($Vision) { '1' } else { '0' }
Write-Output 'Configuración cargada en esta sesión de PowerShell. Inicie el motor desde esta misma ventana.'
