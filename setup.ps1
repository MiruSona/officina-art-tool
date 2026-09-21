# ArtTool setup : create .venv in this folder, install the tool, run a smoke test.
# Text is English on purpose : PowerShell 5.1 breaks on UTF-8 Korean without BOM.

$root = $PSScriptRoot
$venv = Join-Path $root ".venv"
$venvPython = Join-Path $venv "Scripts\python.exe"
$stamp = Join-Path $venv ".setup-stamp"

# pyproject says requires-python = ">=3.11". Ask the interpreter itself, do not trust the name.
$probe = 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'
$exe = $null
$exeArgs = @()

$found = Get-Command python -ErrorAction SilentlyContinue
if ($found) {
   & $found.Source -c $probe 2>$null
   if ($LASTEXITCODE -eq 0) { $exe = $found.Source }
}

if (-not $exe) {
   # python may be missing from PATH (or be an old one). The launcher can still find a good 3.x.
   $found = Get-Command py -ErrorAction SilentlyContinue
   if ($found) {
      & $found.Source -3 -c $probe 2>$null
      if ($LASTEXITCODE -eq 0) { $exe = $found.Source; $exeArgs = @("-3") }
   }
}

if (-not $exe) {
   Write-Host "ERROR: no Python 3.11 or newer found (tried 'python' and 'py -3'). Install Python 3.11+ first."
   exit 1
}
Write-Host "Using Python: $exe $exeArgs"

if (-not (Test-Path $venvPython)) {
   Write-Host "Creating venv in $venv"
   & $exe @exeArgs -m venv $venv
   if ($LASTEXITCODE -ne 0) {
      Write-Host "ERROR: venv creation failed."
      exit 1
   }
}

Write-Host "Installing arttool (editable, dev extras)"
& $venvPython -m pip install -e "$root[dev]"
if ($LASTEXITCODE -ne 0) {
   Write-Host "ERROR: pip install failed. If you are offline, run it again when the network is back."
   exit 1
}

Write-Host "Smoke test: python -m arttool --help"
& $venvPython -m arttool --help | Out-Null
if ($LASTEXITCODE -ne 0) {
   Write-Host "ERROR: smoke test failed."
   exit 1
}

# The game repo's health check reads this stamp to tell whether the venv is stale.
Set-Content -Path $stamp -Value (Get-Date -Format "o") -Encoding ascii
Write-Host "Done. Call the tool with: $venv\Scripts\arttool <command>"
