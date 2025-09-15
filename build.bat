@echo off
setlocal
set NAME=local_voice_agent

if not exist .venv (
  echo [build] Please run setup.bat first.
  exit /b 1
)
call .venv\Scripts\activate

:: Clean old builds
if exist build rd /s /q build
if exist dist rd /s /q dist
if exist __pycache__ rd /s /q __pycache__

:: Build
pyinstaller ^
  --name %NAME% ^
  --onefile ^
  --collect-data pipecat ^
  --hidden-import pipecat.services.deepgram.stt ^
  --hidden-import pipecat.services.cartesia.tts ^
  --hidden-import pipecat.services.groq.llm ^
  --hidden-import pipecat.processors.filters.stt_mute_filter ^
  --hidden-import pipecat.transports.local.audio ^
  --add-data ".env;.\" ^
  --add-data ".env.example;.\" ^
  server.py

if %ERRORLEVEL% NEQ 0 (
  echo [build] PyInstaller failed.
  exit /b 1
)

echo [build] Built dist\%NAME%.exe
echo [build] Tip: if HTTPS certs error, add --collect-data certifi
endlocal
