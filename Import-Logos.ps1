param([Parameter(Mandatory = $true)][string]$Origen)
# Importa el pack de logos (.zip o carpeta). Cada imagen se asigna al cliente cuyo id o alias
# aparece en el nombre del archivo (p.ej. diaz_logo.png, JC-Granite.jpg, PJ Roofing.png),
# se recorta el borde blanco y queda en profiles\assets\<cliente>.png.
$ErrorActionPreference = 'Stop'
$env:PYTHONPATH = Join-Path $PSScriptRoot 'src'
$py = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $py)) { $py = 'python' }
& $py -m bidkit.contrato logos --origen $Origen
exit $LASTEXITCODE
