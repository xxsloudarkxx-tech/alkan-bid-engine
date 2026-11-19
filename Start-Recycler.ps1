<#
.SYNOPSIS
    Ejecuta el Reciclador y Purgador de Estimados de ALKAN Bid Engine.
.DESCRIPTION
    Purga borradores repetidos u obsoletos, cargas temporales y optimiza el almacenamiento.
.PARAMETER Key
    Clave opcional de proyecto a purgar (ej. GONYEA). Si no se especifica, procesa todos los proyectos.
.PARAMETER Keep
    Número de borradores más recientes a conservar para cada proyecto (por defecto 1).
.PARAMETER DryRun
    Si se especifica, simula las operaciones sin borrar archivos ni carpetas.
#>
param(
    [string]$Key,
    [int]$Keep = 1,
    [switch]$DryRun
)

$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$env:PYTHONPATH = "$RepoRoot\src;$env:PYTHONPATH"
$Python = "python"
$ArgsList = @("-m", "bidkit.recycler", "--root", $RepoRoot, "--keep", $Keep)

if ($Key) {
    $ArgsList += @("--key", $Key)
}

if ($DryRun) {
    $ArgsList += "--dry-run"
}

Write-Host "Iniciando Reciclador de Estimados ALKAN..." -ForegroundColor Cyan
& $Python $ArgsList
