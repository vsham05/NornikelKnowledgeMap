@echo off
cd /d "%~dp0"
call "%~dp0start-infra.bat"
if errorlevel 1 exit /b 1
call "%~dp0stop-backend.bat"
cd /d "%~dp0nornikel-backend"
if not exist .venv python -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install -e . -q
set PYTHONPATH=src
set API_RELOAD=false
echo.
echo Ensure Ollama is running with models:
echo   scripts\pull-ollama-models.ps1 -Tier premium   REM ~90%% Yandex parity
echo   scripts\pull-ollama-models.ps1 -Tier standard  REM default balance
echo   ollama pull mxbai-embed-large
echo.
echo Starting backend at http://localhost:8000
echo Verify: http://localhost:8000/health should show build rag-v4-professional
python run.py
