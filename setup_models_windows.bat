@echo off
setlocal
cd /d "%~dp0"
where ollama >nul 2>nul
if errorlevel 1 (
 echo Install local Ollama from https://ollama.com/download/windows first.
 pause
 exit /b 1
)
if not exist .env copy .env.example .env
echo Downloading local 9B reasoning model and local embedder one time.
ollama pull qwen3.5:9b
if errorlevel 1 goto failed
ollama pull qwen3-embedding:0.6b
if errorlevel 1 goto failed
echo READY. Run run_windows.bat
pause
exit /b 0
:failed
echo Model download failed. Check that Ollama is running and internet is available for first-time setup.
pause
exit /b 1
