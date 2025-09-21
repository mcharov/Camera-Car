# Camera-Car

# Operation
The Camera Car project has two modes of operation: manual with a keyboard and mouse or voice-controlled. 

The manual-controlled mode involves using the keyboard (WASD keys) to move the car around. Also, one can use their mouse to move the camera around. The car provides a live feed through a computer screen so you can see what is going on.
The voice-controlled mode involves using spoken words to control the car. One can say "go forward" and the car goes forward, and so on. Also, the car can speak to you through a LLM model. The car listens to your voice, and upon hearing the wake word computer with Porcupine, it starts a voice activity detection stream, and listens to you until you stop speaking. It sends your voice request as a file to a local computer, where it then transcribes it using Whisper API and feeds it into an Ollama Model (llama3, in this case). The Ollama model then sends the response into a TTS software (PiperTTS), and subsequently sends the the audio file of the TTS output back to the car which plays the audio out loud.

# Usage
To use the manual mode:
1. Run the camera_car_controls_final_tts.py (having index_tts.html in the same directory) script along with the camera_stream_sever.py script. 
2. On your local computer, open a browser to the location of the flask server (printed out in console). It is in the form of "http://raspberry pi ip:5000/".

To use the voice-controlled mode:
1. Simply run the launch_camera_car_rpi.sh on the RaspberryPi and the launch_camera_car_windows.bat on your local computer (must be windows). Make sure to be in the current working directory for both.
