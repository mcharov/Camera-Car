from fastapi import FastAPI, File, UploadFile, Form
from fastapi.responses import JSONResponse, FileResponse
from starlette.background import BackgroundTask
import whisper
import tempfile
import os
import subprocess
from pathlib import Path

# Run "uvicorn whisper_piper_server:app --host 0.0.0.0 --port 8000" to start the server (make sure to be in the working directory)
# Then get ollama, add it to path and pull ollama3
# Run "set OLLAMA_HOST=0.0.0.0"
#      "ollama serve" after

# -------------------------------------------------------------------------------------------------------------------- #
#
# INIT APP
#
# -------------------------------------------------------------------------------------------------------------------- #

app = FastAPI()

# -------------------------------------------------------------------------------------------------------------------- #
#
# WHISPER CONFIG
#
# -------------------------------------------------------------------------------------------------------------------- #

model = whisper.load_model("large")  # Or "base", "small", etc.

# -------------------------------------------------------------------------------------------------------------------- #
#
# PIPER CONFIG
#
# -------------------------------------------------------------------------------------------------------------------- #

PIPER_BINARY = Path("piper") / "piper.exe"
PIPER_MODEL = Path("piper") / "voices" / "en" / "en_GB-northern_english_male-medium.onnx"
PIPER_CONFIG = Path(str(PIPER_MODEL) + ".json")
OUTPUT_DIR = Path("tts_output")
OUTPUT_DIR.mkdir(exist_ok=True)


# -------------------------------------------------------------------------------------------------------------------- #
#
# TRANSCRIBE ENDPOINT
#
# -------------------------------------------------------------------------------------------------------------------- #

@app.post("/transcribe")
async def transcribe(file: UploadFile = File(...)):
    try:
        # Create a temporary file but don't delete it automatically
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            temp_path = tmp.name
            contents = await file.read()
            tmp.write(contents)

        # At this point, the file is closed and ffmpeg/whisper can access it
        print(f"Uploaded audio size: {os.path.getsize(temp_path)} bytes")
        result = model.transcribe(temp_path)

        # Clean up
        os.remove(temp_path)
        return JSONResponse(content={"transcript": result["text"]})

    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse(content={"error": str(e)}, status_code=500)


# -------------------------------------------------------------------------------------------------------------------- #
#
# TTS ENDPOINT
#
# -------------------------------------------------------------------------------------------------------------------- #

@app.post("/speak")
async def speak(text: str = Form(...)):
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            temp_path = tmp.name

        command = [str(PIPER_BINARY), "--model", str(PIPER_MODEL), "--config", str(PIPER_CONFIG), "--output_file",
                   temp_path]
        result = subprocess.run(command, input=text.encode("utf-8"), stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        if result.returncode != 0:
            os.remove(temp_path)
            return JSONResponse(content={"error": result.stderr.decode()}, status_code=500)

        # Return audio file
        task = BackgroundTask(os.remove, temp_path)
        return FileResponse(temp_path, media_type="audio/wav", filename="piper_output.wav",
                            background=task)

    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)
