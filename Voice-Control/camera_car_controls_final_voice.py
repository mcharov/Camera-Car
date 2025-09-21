from flask import Flask, render_template, Blueprint
from flask_sock import Sock
from picarx import Picarx
from robot_hat import Music, TTS
import threading
import time

px = Picarx()
music = Music()
tts = TTS()

app = Flask(__name__)

app = Flask("")
sock = Sock(app)

flag_bgm = False
music.music_set_volume(20)
tts.lang("en-US")

# ------------------------------------------------------------ #
# ESTABLISH WEBSITE                                            #
# ------------------------------------------------------------ #

@app.route('/')
def index():
    return render_template('index_voice.html')

# ------------------------------------------------------------ #
# FUNCTIONS FOR MOVEMENT                                       #
# ------------------------------------------------------------ #

def moveForward(speed):
    speed = speed + 0.25
    px.forward(speed)
    
def moveBackward(speed):
    speed = speed + 0.25
    px.backward(speed)
    
def rightTurn():
    px.set_dir_servo_angle(30)
    
def leftTurn():
    px.set_dir_servo_angle(-30)

def resetTurn():
    px.set_dir_servo_angle(0)

# ------------------------------------------------------------ #
# FUNCTIONS FOR CAMERA MOVEMENT                                #
# ------------------------------------------------------------ #

def remap_value(oldVal, oldMin, oldMax, newMin, newMax):
    oldRange = oldMax - oldMin
    newRange = newMax - newMin
    newVal = (((oldVal - oldMin) * newRange) / oldRange) + newMin
    return newVal

def move_camera(dataList):
    if (dataList[0] == "mm"):
        coordinates = dataList[1].split(" ")
        Mouse_X = int(coordinates[0])
        OldMax_X = int(coordinates[2])
        OldMin_X = 0
        NewMax_X = 180
        NewMin_X = -180
        NewValue_X = remap_value(Mouse_X, OldMin_X, OldMax_X, NewMin_X, NewMax_X)
        print(NewValue_X)
        Mouse_Y = int(coordinates[1])
        OldMax_Y = 0
        OldMin_Y = int(coordinates[3])
        NewMax_Y = 180
        NewMin_Y = -180
        NewValue_Y = remap_value(Mouse_Y, OldMin_Y, OldMax_Y, NewMin_Y, NewMax_Y)
        px.set_cam_pan_angle(NewValue_X)
        px.set_cam_tilt_angle(NewValue_Y)
        print(NewValue_Y)
    else:
        pass

# ------------------------------------------------------------ #
# TTS FUNCTION                                                 #
# ------------------------------------------------------------ #

def speak(dataList):
    if dataList[0] == "sent":
        if dataList[1] == "music":
            music.music_play("cameraCarSounds/tunak.mp3")
        elif dataList[1] == "stop":
            music.music_stop()
        else:
            tts.say(dataList[1])
    
keyHistory = []
speed = 0

@sock.route('/echo')
def echo(sock):
    while True:
        print(keyHistory)
        data = sock.receive().strip()
        print("GOT data: " + data)
        sock.send(data + " from Python!!")
        dataList = data.split(":")
        
        # ------------------------------------------------------------ #
        # TTS SPEECH                                                   #
        # ------------------------------------------------------------ #
        
        speak(dataList)
        
        # ------------------------------------------------------------ #
        # CAMERA MOVEMENT                                              #
        # ------------------------------------------------------------ #
        
        move_camera(dataList)
        
        # ------------------------------------------------------------ #
        # MOVE FORWARD                                                 #
        # ------------------------------------------------------------ #
        
        if data == 'forward:1':
            if not 'forward:1' in keyHistory:
                keyHistory.append('forward:1')
                moveForward(speed)
        
        # Launch a thread to stop after 3 seconds
        def stop_forward():
            time.sleep(3)
            if 'forward:1' in keyHistory:
                keyHistory.pop(keyHistory.index('forward:1'))
                print("Auto-stopping forward")
                px.stop()
                
        threading.Thread(target=stop_forward).start()
        
        # ------------------------------------------------------------ #
        # MOVE BACKWARD                                                #
        # ------------------------------------------------------------ #
        
        if data == 'backward:1':
            if not 'backward:1' in keyHistory:
                keyHistory.append('backward:1')
                moveBackward(speed)
        
        # Launch a thread to stop after 3 seconds
        def stop_backward():
            time.sleep(3)
            if 'backward:1' in keyHistory:
                keyHistory.pop(keyHistory.index('backward:1'))
                print("Auto-stopping backward")
                px.stop()
                
        threading.Thread(target=stop_backward).start()
           

        # ------------------------------------------------------------ #
        # RIGHT TURN                                                   #
        # ------------------------------------------------------------ #
        
        # Receive data
        if data == 'right:1':
            if not 'right:1' in keyHistory:
                keyHistory.append('right:1')
                rightTurn()
                
        #Remove right from list so other actions dont get activated
        elif data == 'right:0':
            if 'right:1' in keyHistory:
                keyHistory.pop(keyHistory.index('right:1'))
        else:
            pass
        

        
        # ------------------------------------------------------------ #
        # LEFT TURN                                                    #
        # ------------------------------------------------------------ #
            
        #Turn wheels left
        if data == 'left:1':
            if not 'left:1' in keyHistory:
                keyHistory.append('left:1')
                leftTurn()
                
        #Remove left from list so other actions dont get activated
        elif data == 'left:0':
            if 'left:1' in keyHistory:
                keyHistory.pop(keyHistory.index('left:1'))
        else:
            pass
            
        # ------------------------------------------------------------ #
        # NO TURN                                                      #
        # ------------------------------------------------------------ #
        
        if not keyHistory:
            resetTurn()

            
app.run(host="raspberry pi ip")
