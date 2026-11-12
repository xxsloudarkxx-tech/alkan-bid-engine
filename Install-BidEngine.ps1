$ErrorActionPreference = 'Stop'
& python -m venv (Join-Path $PSScriptRoot '.venv')
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$alkanInstallPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
& $alkanInstallPython -m pip install -e "$($PSScriptRoot)[test]"
exit $LASTEXITCODE
