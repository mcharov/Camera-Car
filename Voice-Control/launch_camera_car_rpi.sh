#!/bin/bash

echo "=== Starting Flask Car Control Server ==="
lxterminal -e "bash -c 'cd /home/pi/PiProjects/programs/CameraCar && python3 camera_car_controls_final_voice.py'" &

echo "=== Starting Camera Stream ==="
lxterminal -e "bash -c 'cd /home/pi/PiProjects/programs/CameraCar && python3 camera_stream_server.py'" &

echo "=== Starting Voice Control ==="
lxterminal -e "bash -c 'cd /home/pi/PiProjects/programs/CameraCar && python3 whisper_ollama_client_command_final_aec.py'" &
