@echo off
setlocal EnableExtensions EnableDelayedExpansion

:: --- 0) Find or install Python ---
where py >NUL 2>NUL
if %ERRORLEVEL% NEQ 0 (
  echo [setup] Python launcher not found. Attempting install via winget...
  where winget >NUL 2>NUL
  if %ERRORLEVEL% NEQ 0 (
    echo [setup] winget not found. Please install Python 3.12+ manually then re-run setup.bat
    exit /b 1
  )
  winget install -e --id Python.Python.3.12 -h
)
for /f "tokens=2 delims= " %%v in ('py -3 -V') do set PYVER=%%v
echo [setup] Using Python %PYVER%

:: --- 1) Create venv ---
if not exist .venv (
  echo [setup] Creating virtual environment .venv
  py -3 -m venv .venv || (echo [setup] venv creation failed & exit /b 1)
)

call .venv\Scripts\activate

:: --- 2) Upgrade pip & install deps ---
python -m pip install -U pip wheel setuptools
if exist requirements.txt (
  python -m pip install -U -r requirements.txt
) else (
  echo [setup] requirements.txt not found, installing core deps...
  python -m pip install -U "pipecat-ai[deepgram,cartesia,groq,local]" python-dotenv gradio pyinstaller
)

:: --- 3) Audio dependency (Windows) ---
:: PyAudio wheels are provided on PyPI for Windows; this usually just works.
python -m pip install -U pyaudio

:: --- 4) Verify imports (no audio devices required) ---
set NO_AUDIO=1
python - << "PY"
import importlib, os, sys
mods = [
  "pipecat",
  "pipecat.services.deepgram.stt",
  "pipecat.services.groq.llm",
  "pipecat.services.cartesia.tts",
  "pipecat.processors.filters.stt_mute_filter",
  "gradio",
  "pyaudio",
]
for m in mods:
    importlib.import_module(m)
print("[verify] core imports ok")

# Optional: confirm server.py imports cleanly in headless mode
os.environ["NO_AUDIO"]="1"
import server
print("[verify] server module import ok (headless)")
PY

if %ERRORLEVEL% NEQ 0 (
  echo [setup] Verification failed.
  exit /b 1
)

echo [setup] All good. Activate with:  call .venv\Scripts\activate
endlocal
