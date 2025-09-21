import wave
import tempfile
import requests
import time
import os
import webrtcvad
import collections
import threading
import numpy as np
from scipy.signal import resample
import websocket
import pvporcupine
import sounddevice as sd
import re
import subprocess
from aec import aec_process
import io
from scipy.io import wavfile
import array
from collections import deque


# -------------------------------------------------------------------- #
# AUDIO CONFIG                                                         #
# -------------------------------------------------------------------- #
MIC_SAMPLE_RATE = 48000 # Mic sample rate

# For Porcupine
PORCUPINE_DURATION = 32 # ms
PORCUPINE_BLOCK_SIZE = 1536 # block size for 512 samples (1536 * 16000 / 48000)
FRAME_SIZE = PORCUPINE_BLOCK_SIZE

# For VAD
VAD_DURATION = 30 # ms
VAD_FRAME_SIZE = int(MIC_SAMPLE_RATE * VAD_DURATION / 1000) # 1440
BUFFER_SIZE = 20 # for VAD detection

# To change volume, type "alsamixer" in the terminal
# Then press "F6" to change to your device (Hifiberry in this case)
# Use the arrow keys to change the volume
# Press "ESC" to exit

# -------------------------------------------------------------------- #
# VAD CONFIG                                                           #
# -------------------------------------------------------------------- #
vad = webrtcvad.Vad(3) # 0 = very sensitive, 3 = less sensitive

# -------------------------------------------------------------------- #
# SERVER CONFIG                                                        #
# -------------------------------------------------------------------- #

WHISPER_SERVER = "http://local computer ip:8000/transcribe" # FastAPI whisper server
PIPER_SERVER = "http://local computer ip:8000/speak" # FastAPI piper serverc
OLLAMA_SERVER = "http://local computer ip:11434/api/chat" # Ollama API on PC

# -------------------------------------------------------------------- #
# PORCUPINE CONFIG                                                     #
# -------------------------------------------------------------------- #
porcupine = pvporcupine.create(
		access_key="access key for porcupine",
		keywords=["computer"]
)
PORCUPINE_SAMPLE_RATE = porcupine.sample_rate # 16000 kHz
PORCUPINE_FRAME_LENGTH = porcupine.frame_length # 512 frames

# -------------------------------------------------------------------- #
# GLOBAL STATE                                                         #
# -------------------------------------------------------------------- #
processing = False
wake_detected = False
conversation_history = [{"role": "system", "content": "You are a helpful assistant, but you speak concisely. Your name is Edward."}]
MAX_HISTORY = 20
CHANNELS = 1
tts_process = None
stop_requested = False
tts_lock = threading.Lock()
current_far_audio = np.zeros(FRAME_SIZE, dtype=np.int16)
session_active = False
session_frames = []
TAIL_MS = 300
TAIL_SAMPLES = MIC_SAMPLE_RATE * TAIL_MS // 1000
far_primed = False

# -------------------------------------------------------------------- #
# AUDIO BUFFERS                                                        #
# -------------------------------------------------------------------- #
ring_buffer = collections.deque(maxlen=BUFFER_SIZE)
voiced_frames = []
resampled_audio_buffer = []
aec_buffer = []

# Far-end ring buffer
FAR_DELAY_MS = 40 # 20 - 80 ms
FAR_DELAY_SAMPLES = MIC_SAMPLE_RATE * FAR_DELAY_MS // 1000

far_lock = threading.Lock()
far_ref = deque(maxlen=MIC_SAMPLE_RATE * 5) # keep last ~5s of far-end
def far_write(pcm_int16: np.ndarray):
	with far_lock:
		far_ref.extend(pcm_int16.tolist())
		
def far_read(n: int) -> np.ndarray:
	global far_primed
	with far_lock:
		# Ensure delay: if there is not enough, pad with zeros
		if not far_primed:
			if len(far_ref) < FAR_DELAY_SAMPLES + n:
				return np.zeros(n, dtype=np.int16)
			# Skip "fresh" samples to introduce output latency compensation
			for _ in range(FAR_DELAY_SAMPLES):
				far_ref.popleft()
			far_primed = True
		
		# Read n samples
		take = min(n, len(far_ref))
		out = [far_ref.popleft() for _ in range(take)]
	if len(out) < n:
		out += [0] * (n-len(out))
	return np.asarray(out, dtype=np.int16)
	
# -------------------------------------------------------------------- #
# AUDIO MANIPULATION                                                   #
# -------------------------------------------------------------------- #
def resample_audio(audio_data, original_rate, target_rate):
	num_samples = int(len(audio_data) * target_rate / original_rate)
	return resample(audio_data, num_samples).astype(np.int16)

def reduce_volume(audio_bytes, scale=0.2):
    samples = np.frombuffer(audio_bytes, dtype=np.int16)
    scaled = np.clip(samples * scale, -32768, 32767).astype(np.int16)
    return scaled.tobytes()
    
def save_audio(audio_data, sample_rate, filename="resampled_output.wav"):
	with wave.open(filename, "wb") as wf:
		wf.setnchannels(1) # Mono
		wf.setsampwidth(2) # 16-bit PCM
		wf.setframerate(sample_rate)
		
		if isinstance(audio_data, np.ndarray):
			wf.writeframes(audio_data.tobytes())
		elif isinstance(audio_data, (bytes, bytearray)):
			wf.writeframes(audio_data)
		elif isinstance(audio_data, list):
			wf.writeframes(array.array("h", audio_data).tobytes())
		else:
			raise TypeError("Unsupported audio_data type for saving.")
			
def save_full_aec_buffer():
	global aec_buffer
	if aec_buffer:
		full_audio = np.concatenate(aec_buffer)
		save_audio(full_audio, MIC_SAMPLE_RATE, "aec_output.wav")
		aec_buffer.clear()

# -------------------------------------------------------------------- #
# AI-RELATED FUNCTIONS                                                 #
# -------------------------------------------------------------------- #
# Deal with conversation memory
def trim_memory():
	global conversation_history
	if len(conversation_history) > MAX_HISTORY * 2:
		conversation_history = [conversation_history[0]] + conversation_history[-MAX_HISTORY*2:]
	
# Send audio to whisper server
def send_audio_to_server(filepath):
	with open(filepath, "rb") as f:
		files = {"file": ("clip.wav", f, "audio/wav")}
		try:
			response = requests.post(WHISPER_SERVER, files=files)
			return response.json()
		except Exception as e:
			print("Error sending to whisper server:", e)
			return {"transcript": ""}

# Send transcript to Ollama server
def get_ollama_response(prompt):
	conversation_history.append({"role": "user", "content": prompt})
	trim_memory()
	
	try:
		response = requests.post(OLLAMA_SERVER, json={
			"model": "llama3",
			"messages": conversation_history,
			"stream": False
		})
		response.raise_for_status()
		
		# Parse clean JSON
		json_data = response.json()
		reply = json_data.get("message", {}).get("content", "").strip()
		conversation_history.append({"role": "assistant", "content": reply})
		return reply
	except Exception as e:
		print("Error contacting Ollama:", e)
		return ""
		
# Piper tts
def speak_with_piper(text):
	global tts_process, current_far_audio, far_primed
	
	current_far_audio = np.zeros(0, dtype=np.int16) # Global buffer
	
	def play_audio(wav_data):
		global tts_process, current_far_audio, session_active, session_frames, far_primed
		with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_wav:
			tmp_wav.write(wav_data)
			tmp_wav.flush()
			
			# Parse raw audio into numpy array
			try:
				sample_rate, pcm_data = wavfile.read(tmp_wav.name)
				if sample_rate != MIC_SAMPLE_RATE:
					pcm_data = resample_audio(pcm_data, sample_rate, MIC_SAMPLE_RATE)
				if pcm_data.ndim > 1:
					pcm_data = pcm_data[:, 0] # Convert to mono if stereo
				far_primed = False # reset delay
				far_write(pcm_data.astype(np.int16)) # enqueue full reference first
			except Exception as e:
				print("Failed to parse TTS wav for AEC:", e)
				
			with tts_lock:
				tts_process = subprocess.Popen(["aplay", tmp_wav.name])
			# Wait until finished or stop detected
			tts_process.wait()
			os.remove(tmp_wav.name)
			with tts_lock:
				tts_process = None
				
			if session_active:
				session_frames.append(np.zeros(TAIL_SAMPLES, dtype=np.int16))
				full = np.concatenate(session_frames) if session_frames else np.zeros(1, np.int16)
				save_audio(full, MIC_SAMPLE_RATE, "interaction_session.wav")
				session_active = False
				session_frames.clear()
				
				
	try:
		global stop_requested
		stop_requested = False
		response = requests.post(PIPER_SERVER, data={"text": text})
		if response.status_code != 200:
			print("TTS server error:", response.text)
			return
			
		# Extract PCM from WAV and store it
		wav_buf = io.BytesIO(response.content)
		sample_rate, pcm_data = wavfile.read(wav_buf)
		
		# Resample if needed
		if sample_rate != MIC_SAMPLE_RATE:
			pcm_data = resample_audio(pcm_data, sample_rate, MIC_SAMPLE_RATE)
			
		with tts_lock:
			current_far_audio = pcm_data.astype(np.int16)
		
		# Start playback
		threading.Thread(target=play_audio, args=(response.content,), daemon=True).start()

	except Exception as e:
		print("Error using TTS server:", e)

# Movement command detection
def parse_command(transcript):
	t = transcript.lower()
	
	# Tokenize into whole words using regex
	words = re.findall(r'\b\w+\b', t)
	
	# Match exact words only
	if "forward" in words:
		return "forward"
	elif "backward" in words:
		return "backward"
	elif "left" in words:
		return "left"
	elif "right" in words:
		return "right"
	elif "stop" in words and "turn" in words:
		return "stop turn"
	return None
	
# Send command to car for movement
def send_to_car(command):
	try:
		ws = websocket.create_connection("ws://raspberry pi ip:5000/echo")
		print("WebSocket connected.")
		if command == "forward":
			ws.send("forward:1")
			ws.send("backward:0")
		elif command == "backward":
			ws.send("backward:1")
			ws.send("forward:0")
		elif command == "left":
			ws.send("left:1")
			ws.send("right:0")
		elif command == "right":
			ws.send("right:1")
			ws.send("left:0")
		elif command == "stop turn":
			ws.send("left:0")
			ws.send("right:0")
	except Exception as e:
		print("Failed to send to car:", e)

# -------------------------------------------------------------------- #
# HANDLER FUNCTIONS                                                    #
# -------------------------------------------------------------------- #
def handle_voiced_frames():
	global processing, voiced_frames, stop_requested
	processing = True # Pause audio listening
	
	# Save Audio
	audio_bytes = b"".join(voiced_frames)
	save_audio(audio_bytes, MIC_SAMPLE_RATE, "mic_voiced_input.wav")
	
	# Save to WAV
	with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as wf:
		wf_name = wf.name
		wf = wave.open(wf_name, "wb")
		wf.setnchannels(CHANNELS)
		wf.setsampwidth(2) # 16-bit
		wf.setframerate(MIC_SAMPLE_RATE)
		wf.writeframes(b"".join(voiced_frames))
		wf.close()
		
	transcript_data = send_audio_to_server(wf_name)
	transcript = transcript_data.get("transcript", "").strip()
	print("Transcript:", transcript)
	
	command = parse_command(transcript)
	if command:
		print(f"Parsed command: {command}")
		send_to_car(command)
		speak_with_piper(f"Executing command: {command}")
	else:
		reply = get_ollama_response(transcript)
		print("Response:", reply)
		speak_with_piper(reply)
		
	if os.path.exists(wf_name):
		os.remove(wf_name)
	voiced_frames.clear()
	processing = False # Resume audio listening

def tts_watchdog():
	global tts_process, stop_requested
	while True:
		if stop_requested:
			with tts_lock:
				if tts_process is not None:
					print("[WATCHDOG] Killing TTS process...")
					try:
						tts_process.kill()
						tts_process.communicate()
					except Exception as e:
						print("[WATCHDOG] Error killing TTS:", e)
					tts_process = None
					stop_requested = False
		time.sleep(0.05)
		
def interrupt_tts(reason=""):
	global tts_process, stop_requested, far_primed
	with tts_lock:
		if tts_process is not None:
			print(f"[TTS] Interrupt: {reason}")
			try:
				tts_process.kill()
				tts_process.communicate()
			except Exception as e:
				print("[TTS] Error killing process:", e)
			tts_process = None
	# reset watchdog flag just in case
	stop_requested = False
	# clear far-end buffer so AEC doesn't keep feeding old TTS
	with far_lock:
		far_ref.clear()
		far_primed = False
		
# -------------------------------------------------------------------- #
# AUDIO FUNCTIONS                                                 	   #
# -------------------------------------------------------------------- #	
# Continuous audio streaming
def unified_audio_callback(indata, frames, time_info, status):
	global wake_detected, processing, voiced_frames, session_active, stop_requested
	
	# -----------------------------------------------------------------#
	# AEC PROCESSING                                        		   #
	# -----------------------------------------------------------------#
			
	mic = indata[:, 0].astype(np.int16) # mono channel
	far = far_read(len(mic))
	try:
		clean = aec_process(mic, far)
	except Exception as e:
		print("AEC Error:", e)
		clean = mic
	
	if session_active:
		session_frames.append(clean.copy())
		
	#aec_buffer.append(clean) # Accumulate AEC output	
	
	# -----------------------------------------------------------------#
	# WAKE WORD DETECTION                                              #
	# -----------------------------------------------------------------#
	
	# Only gate wake/VAD if in processing, no TTS gap
	skip_wake_vad = (processing and tts_process is None)
	
	# Resample to 16kHz for Porcupine
	if not skip_wake_vad:
		resampled = resample_audio(clean, MIC_SAMPLE_RATE, PORCUPINE_SAMPLE_RATE)
		if len(resampled) >= PORCUPINE_FRAME_LENGTH:
			# Process with Porcupine
			if len(resampled) >= PORCUPINE_FRAME_LENGTH:
				frame = resampled[:PORCUPINE_FRAME_LENGTH]
				result = porcupine.process(frame)
				if result >= 0 and not wake_detected:
					print("Wake word detected!")
					wake_detected = True
					ring_buffer.clear()
					voiced_frames.clear()
					
					# Start AEC session capture
					session_active = True
					session_frames.clear()
					
					if tts_process is not None:
						interrupt_tts("wake word")
						speak_with_piper("Yes?")
					else:
						speak_with_piper("Yes?")
						
					wake_detected = True
					ring_buffer.clear()
					voiced_frames.clear()
			
	# -----------------------------------------------------------------#
	# SPEECH DETECTION                                                 #
	# -----------------------------------------------------------------#
	if not skip_wake_vad and wake_detected and len(clean) >= VAD_FRAME_SIZE:
		vad_frame = clean[:VAD_FRAME_SIZE]
		vad_frame_volume_reduced = reduce_volume(vad_frame.tobytes(), scale=0.2)
		is_speech = vad.is_speech(vad_frame_volume_reduced, MIC_SAMPLE_RATE)
		
		ring_buffer.append((vad_frame_volume_reduced, is_speech))
		
		if sum(1 for _, s in ring_buffer if s) > 0.8 * BUFFER_SIZE and not voiced_frames:
			print("Speech started")
			voiced_frames.extend(f for f, _ in ring_buffer)
			ring_buffer.clear()
		elif voiced_frames:
			voiced_frames.append(vad_frame_volume_reduced)
			if sum(1 for _, s in ring_buffer if not s) > 0.9 * BUFFER_SIZE:
				print("Speech ended")
				wake_detected = False
				
				#save_full_aec_buffer()
				
				threading.Thread(target=handle_voiced_frames).start()

# -------------------------------------------------------------------- #
# MAIN LOOP                                                 	       #
# -------------------------------------------------------------------- #
def start_audio_loop():
	try:
		with sd.InputStream(
			samplerate=MIC_SAMPLE_RATE,
			blocksize=FRAME_SIZE,
			dtype="int16",
			channels=1,
			callback=unified_audio_callback
		):
			print("Stream started...")
			while True:
				time.sleep(0.1)
	except KeyboardInterrupt:
		print("Stopped by user.")
	finally:
		porcupine.delete()

# -------------------------------------------------------------------- #
# RUN                                                	               #
# -------------------------------------------------------------------- #
if __name__ == "__main__":
	start_audio_loop()
	threading.Thread(target=tts_watchdog, daemon=True).start()
