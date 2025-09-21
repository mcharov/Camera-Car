@echo off
echo === Starting Ollama ===
start cmd /k "set OLLAMA_HOST=0.0.0.0 && ollama serve"

echo === Starting Whisper + Piper server ===
start cmd /k "cd /d C:\data\dev\PycharmProjects\CameraCar && uvicorn whisper_piper_server:app --host 0.0.0.0 --port 8000"

pause