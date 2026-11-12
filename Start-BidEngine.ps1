param([int]$Port = 8765, [switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$alkanVenvPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$alkanCommand = Get-Command python -ErrorAction SilentlyContinue
$alkanPython = if ($alkanCommand) { $alkanCommand.Source } else { Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' }
if (Test-Path -LiteralPath $alkanVenvPython) { $alkanPython = $alkanVenvPython }
if (-not (Test-Path -LiteralPath $alkanPython)) { throw 'Python 3.11+ no encontrado. Instale Python y las dependencias de pyproject.toml.' }
$alkanArgs = @((Join-Path $PSScriptRoot 'run_bidkit.py'), 'estimate-ui', '--root', $PSScriptRoot, '--port', "$Port")
if ($NoBrowser) { $alkanArgs += '--no-browser' }
& $alkanPython @alkanArgs
exit $LASTEXITCODE
