@echo off
setlocal
set NAME=local_voice_agent

pyinstaller ^
  --name %NAME% ^
  --onefile ^
  --add-data ".env;." ^
  --hidden-import pipecat.services.deepgram.stt ^
  --hidden-import pipecat.services.cartesia.tts ^
  --hidden-import pipecat.services.groq.llm ^
  --hidden-import pipecat.transports.local.audio ^
  server.py

echo Built dist\%NAME%.exe
endlocal
