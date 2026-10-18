$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$py = $null
if (Get-Command py -ErrorAction SilentlyContinue) { $py = "py"; $args = @("-3", "$here\install.py") }
elseif (Get-Command python -ErrorAction SilentlyContinue) { $py = "python"; $args = @("$here\install.py") }
elseif (Get-Command python3 -ErrorAction SilentlyContinue) { $py = "python3"; $args = @("$here\install.py") }
else { throw "Python not found. Install Python 3 and ensure py/python is on PATH." }
& $py @args
if (Get-Command magpie -ErrorAction SilentlyContinue) {
  magpie library sync
} else {
  Write-Host "magpie not on PATH — open Magpie and use Library sync, or add magpie.exe to PATH."
}
