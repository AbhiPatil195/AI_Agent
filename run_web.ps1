Param(
  [int]$Port = 8501,
  [switch]$Headless
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# Project root = script location
$proj = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -Path $proj

# Resolve venv Python
$venvPy = Join-Path $proj ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
  Write-Host "Virtual environment not found. Creating .venv with Python launcher..." -ForegroundColor Yellow
  if (Get-Command py -ErrorAction SilentlyContinue) {
    try { py -3.10 -m venv .venv } catch { py -3 -m venv .venv }
    $venvPy = Join-Path $proj ".venv\Scripts\python.exe"
  } elseif (Get-Command python -ErrorAction SilentlyContinue) {
    python -m venv .venv
    $venvPy = Join-Path $proj ".venv\Scripts\python.exe"
  } else {
    throw "Python not found. Install Python 3.10+ and re-run."
  }
}

# Ensure base tooling
& $venvPy -m pip install --upgrade pip | Out-Null

# Ensure Streamlit (and other deps) are installed
try {
  & $venvPy -c "import streamlit" 2>$null | Out-Null
} catch {
  Write-Host "Installing requirements..." -ForegroundColor Yellow
  & $venvPy -m pip install -r requirements.txt
}

# Build argument list
$args = @('-m','streamlit','run','src/ui/app.py','--server.address','127.0.0.1','--server.port',"$Port")
if ($Headless.IsPresent) { $args += @('--server.headless','true') }

Start-Process -FilePath $venvPy -ArgumentList $args -WorkingDirectory $proj | Out-Null
Write-Host "Streamlit launching on http://127.0.0.1:$Port" -ForegroundColor Green

