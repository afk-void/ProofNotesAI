@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
 echo Python 3.10+ required from https://python.org
 pause
 exit /b 1
)
if not exist .venv py -3 -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install -r requirements.txt
if not exist .env copy .env.example .env
where ollama >nul 2>nul
if errorlevel 1 (
 echo Install Ollama from https://ollama.com/download/windows then run setup_models_windows.bat
 pause
 exit /b 1
)
start "" http://127.0.0.1:8765
python -m uvicorn app.main:app --host 127.0.0.1 --port 8765
pause
