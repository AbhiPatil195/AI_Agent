@echo off
setlocal ENABLEEXTENSIONS
set "PROJ=%~dp0"
set "PY=%PROJ%.venv\Scripts\python.exe"

if not exist "%PY%" (
  echo [INFO] Virtual environment not found. Creating .venv ...
  where py >nul 2>nul
  if %ERRORLEVEL%==0 (
    py -3.10 -m venv "%PROJ%.venv" 2>nul || py -3 -m venv "%PROJ%.venv"
  ) else (
    python -m venv "%PROJ%.venv"
  )
)

set "PY=%PROJ%.venv\Scripts\python.exe"

rem Upgrade pip quietly
"%PY%" -m pip install --upgrade pip >nul 2>nul

rem Ensure Streamlit is installed
"%PY%" -c "import streamlit" >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
  echo [INFO] Installing requirements ...
  "%PY%" -m pip install -r "%PROJ%requirements.txt"
)

set "PORT=%1"
if "%PORT%"=="" set "PORT=8501"

start "" "%PY%" -m streamlit run "%PROJ%src\ui\app.py" --server.address 127.0.0.1 --server.port %PORT%
echo [OK] Streamlit launching on http://127.0.0.1:%PORT%
endlocal

