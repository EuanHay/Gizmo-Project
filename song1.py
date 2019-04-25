
import os
import RPi.GPIO as GPIO
import time
import pygame
import board
import neopixel
from gpiozero import Servo

#Neopixel setup
PIXEL_PIN = board.D21
ORDER = neopixel.RGB
COLOR = (0,255,255)
newCOLOR = (255, 50, 50)
CLEAR = (5,5,5)
DELAY = 0.03
pixel = neopixel.NeoPixel(PIXEL_PIN, 60, brightness=0.1, pixel_order = ORDER)
order_list = []

#Button setup
GPIO.setwarnings(False)
GPIO.setmode(GPIO.BCM)

GPIO.setup(20, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
GPIO.setup(16, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
GPIO.setup(26, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
GPIO.setup(19, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
GPIO.setup(13, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)

#Stepper motor setup
enable_pin = 24
A1Pin = 23
A2Pin = 22
B1Pin = 27
B2Pin = 17

GPIO.setup(enable_pin, GPIO.OUT)
GPIO.setup(A1Pin, GPIO.OUT)
GPIO.setup(A2Pin, GPIO.OUT)
GPIO.setup(B1Pin, GPIO.OUT)
GPIO.setup(B2Pin, GPIO.OUT)

GPIO.output(enable_pin, 1)

def setStep(w1,w2,w3,w4):
    GPIO.output(A1Pin, w1)
    GPIO.output(A2Pin, w2)
    GPIO.output(B1Pin, w3)
    GPIO.output(B2Pin, w4)

def backwards (list, count):
    w1 = list[count][0]
    w2 = list[count][1]
    w3 = list[count][2]
    w4 = list[count][3]

    setStep(w1,w2,w3,w4)
    count += 1
    if count >= 8:
        count = 0
    return count

def forward (list, count):
    w1 = list[count][0]
    w2 = list[count][1]
    w3 = list[count][2]
    w4 = list[count][3]

    setStep(w1,w2,w3,w4)
    count -= 1
    if count <= -1:
        count = 7
    return count

stepList = [(1,0,0,0),(1,1,0,0),(0,1,0,0),(0,1,1,0),(0,0,1,0),(0,0,1,1),(0,0,0,1),(1,0,0,1)]
stepperCount = 0
stepperIndicator = 0

#Microservo setup
min_pulse = 0.000544
max_pulse = 0.0024

pos = -1.0
servoCount = 0
servo = Servo(2, pos, min_pulse, max_pulse, 20/1000, None)

posList1 = []
posList2 = []
for pos in range(0,100,1):
    posList1.append(pos*0.01-1)
for pos in range(100,-1,-1):
    posList2.append(pos*0.01-1)

#Song data
totalBeats = 425
beatDivision = totalBeats//6

button1Region = range(0,beatDivision)
button2Region = range(beatDivision, 2*beatDivision)
button3Region = range(2*beatDivision, 3*beatDivision)
button4Region = range(3*beatDivision, 4*beatDivision)
button5Region = range(4*beatDivision, 5*beatDivision)
button6Region = range(5*beatDivision, 6*beatDivision)

#Parse Candidate string into integer list
candidatesList = []

f = open('candidates1.txt','r')
for line in f:
    candidate = []
    a = (line[1:len(line)-2])
    b = a.split()
    for i in b:
        if ',' in i:
            candidate.append(int(i[:len(i)-1]))
        else:
            candidate.append(int(i))
    candidatesList.append(candidate)

#Parsing beat_id
beat_id = []

f = open('beat_id1.txt','r')
for line in f:
    beat_id.append(int(line))

#Parsing time_of_beat
time_of_beat = []

f = open('time_of_beat1.txt','r')
for line in f:
    a = float(line)
    time_of_beat.append(a)

#Parsing Positions
positions = []

f = open('positions1.txt')
for line in f:
    positions.append(int(line))

#Variables
time1 = time.time()
score = 0
count = 0
songLength = 178
pastIndex = 0
pastLEDS = []
fadeLEDS = []
buttonPressed = 0
indicator = 0

#LED Fade function
def fade(position):
    if position[1][0] > 5:
         position[1][0] -= 10
    if position[1][1] > 5:
         position[1][1] -= 10
    if position[1][2] > 5:
         position[1][2] -= 10
    return position

#Activation sequence
for i in range(60):
    pixel[i] = CLEAR
    time.sleep(0.03)

#PyGame Setup
pygame.mixer.init()
pygame.mixer.music.load("wonderwallMix.mp3")
pygame.mixer.music.play(loops = 0, start = 0.0)

#Button press loop
startTime = time.time()
stepperTimeStart = startTime
stepperTimeEnd = startTime
newTime = 0

#Main Loop - While music is playing
while pygame.mixer.music.get_busy():

    time1 = time.time()
    currentTime = (pygame.mixer.music.get_pos())/1000 #Where in the song are we?
    currentIndex = int((currentTime/songLength)*totalBeats)#What index of the lists does that time correspond to?

    pixelIndex = positions[currentIndex]
    pixel[positions[currentIndex]] = COLOR #Light up the corresponding neopixel

    if beat_id[currentIndex] != beat_id[pastIndex]: #If we have moved to a different beat

        #Check whether we have if we have moved forwards by one, if we have jumped forwards or if we have jumped backwards
        beatGap = beat_id[currentIndex] - beat_id[pastIndex]
        if (beat_id[pastIndex]) != 0 and beatGap > 2:
            if beatGap > 0:
                print ("JUMP FORWARDS - " + str(abs(beatGap)))
                stepperIndicator += 1
            elif beatGap < 0:
                print ("JUMP BACKWARDS - " + str(abs(beatGap)))
                stepperIndicator += 2
                print ("INDICATOR - " + str(stepperIndicator))

    if pixelIndex != positions[pastIndex]: #If the new index lit up a new LED
        pastLEDS.append(pastIndex)

        #We want one leading LED and two trailing LEDs
        #Check each previously visitied LED
        for i in pastLEDS:
            difference = ((positions[i] - positions[currentIndex]))
            #If an LED is no longer within 2 index places of the leading LED, start fading it
            if abs(difference) > 2:
                 fadeLEDS.append([i,[0,255,255]])
                 pastLEDS.remove(i)
    pastIndex = currentIndex

    #Fade LEDs in a gradual manner
    for position in fadeLEDS:
        fade(position)
        pixel[positions[position[0]]] = (position[1][0], position[1][1], position[1][2])
        if position[1][0] == 5 and position[1][1] == 5 and position[1][2] == 5:
            fadeLEDS.remove(position)

    #Are we already looking for a jump location
    if GPIO.input(19) == 1 or GPIO.input(13) == 1 or GPIO.input(19) == 1 or GPIO.input(26) == 1 or GPIO.input(26) and count == 0:
        indicator = 1
        print("INDICATOR +1")

    #There are two types of button presses; short presses and long presses
    #Short presses start the search for a jump location in the corresponding area
    #Long presses exit the program and returns to the menu program

    #If Button 1 is held, return to home screen
    if indicator == 1 and GPIO.input(19) == 1:
        indicator = 0
        score += gap
        if score >= 2:
            pygame.mixer.music.pause()
            print ("Long Press")
            os.system("sudo python3 buttonFunction.py")

        #Else if its a short press and we're not already looking for a jump location, start looking for a jump location
        elif score < 2 and score > 0 and GPIO.input(19) != 1 and count != 1:
            print("Short Press")
            buttonPressed = 2
            for i in range(int(1*beatDivision*60/425) ,int(2*beatDivision*60/425)): #Light up the region we are jumping to
                pixel[i] = newCOLOR
                time.sleep(0.01)
            count = 1
            currentTime = (pygame.mixer.music.get_pos())/1000
            newTime = currentTime
            currentIndex = int((currentTime/songLength)*totalBeats)
            print(candidatesList[currentIndex])
            for candidate in candidatesList[currentIndex]:
                #Is the candidate appropriate? If yes - jump, If no - Keep searching
                if candidate in range(int(1*beatDivision*60/425),int(2*beatDivision*60/425)):
                    if candidate in beat_id:
                         print (candidate)
                         currentIndex = (beat_id.index(candidate))
                         beatGap = beat_id[currentIndex] - beat_id[pastIndex]
                         if beatGap < 0:
                             stepperIndicator += 2
                         elif beatGap > 0:
                             stepperIndicator += 1
                         #start playing the song from the new position
                         pygame.mixer.music.pause()
                         pygame.mixer.music.play(loops = 0, start = time_of_beat[currentIndex])
                         count = 0
                         print ("MATCHED")
                         for i in range(int(1*beatDivision*60/425), int(2*beatDivision*60/425)): #Clear the LEDs that were marking the region
                             pixel[i] = CLEAR
                             time.sleep(0.01)

    #Repeat lines 232 - 270 for the other buttons (skip to line 437)
    if indicator == 1 and GPIO.input(13) == 1:
        indicator = 0
        score += gap
        if score >= 2:
            pygame.mixer.music.pause()
            print ("Long Press")
            os.system("sudo python3 buttonFunction.py")
        elif score < 2 and score > 0 and GPIO.input(13) != 1 and count != 1:
            print("Short Press")
            buttonPressed = 2
            for i in range(int(1*beatDivision*60/425) ,int(2*beatDivision*60/425)):
                pixel[i] = newCOLOR
                time.sleep(0.01)
            count = 1
            currentTime = (pygame.mixer.music.get_pos())/1000
            newTime = currentTime
            #print ("TIME - " + str(currentTime))
            currentIndex = int((currentTime/songLength)*totalBeats)
            #print("INDEX - " + str(currentIndex))
            print(candidatesList[currentIndex])
            for candidate in candidatesList[currentIndex]:
                if candidate in range(int(1*beatDivision*60/425),int(2*beatDivision*60/425)):
                    if candidate in beat_id:
                         print (candidate)
                         currentIndex = (beat_id.index(candidate))
                         beatGapCopy = beat_id[currentIndex] - beat_id[pastIndex]
                         if beatGapCopy < 0:
                             stepperIndicator += 2
                         elif beatGapCopy > 0:
                             stepperIndicator += 1
                         print ("New Index - " + str(currentIndex))
                         print ("New Time - " + str(time_of_beat[currentIndex]))
                         pygame.mixer.music.pause()
                         pygame.mixer.music.play(loops = 0, start = time_of_beat[currentIndex])
                         count = 0
                         print ("MATCHED")
                         for i in range(int(0*beatDivision*60/425), int(1*beatDivision*60/425)):
                             pixel[i] = CLEAR
                             time.sleep(0.01)

    if indicator == 1 and GPIO.input(26) == 1:
        indicator = 0
        score += gap
        if score >= 2:
            pygame.mixer.music.pause()
            print ("Long Press")
            os.system("sudo python3 buttonFunction.py")
        elif score < 2 and score > 0 and GPIO.input(26) != 1 and count != 1:
            print("Short Press")
            buttonPressed = 1
            for i in range(int(0*beatDivision*60/425) ,int(1*beatDivision*60/425)):
                pixel[i] = newCOLOR
                time.sleep(0.01)
            count = 1
            currentTime = (pygame.mixer.music.get_pos())/1000
            newTime = currentTime
            #print ("TIME - " + str(currentTime))
            currentIndex = int((currentTime/songLength)*totalBeats)
            #print("INDEX - " + str(currentIndex))
            print(candidatesList[currentIndex])
            for candidate in candidatesList[currentIndex]:
                if candidate in range(int(2*beatDivision*60/425),int(3*beatDivision*60/425)):
                    if candidate in beat_id:
                         print (candidate)
                         currentIndex = (beat_id.index(candidate))
                         beatGapCopy = beat_id[currentIndex] - beat_id[pastIndex]
                         if beatGapCopy < 0:
                             stepperIndicator += 2
                         elif beatGapCopy > 0:
                             stepperIndicator += 1
                         print ("New Index - " + str(currentIndex))
                         print ("New Time - " + str(time_of_beat[currentIndex]))
                         pygame.mixer.music.pause()
                         pygame.mixer.music.play(loops = 0, start = time_of_beat[currentIndex])
                         count = 0
                         print ("MATCHED")
                         for i in range(int(2*beatDivision*60/425), int(3*beatDivision*60/425)):
                             pixel[i] = CLEAR
                             time.sleep(0.01)

    if indicator == 1 and GPIO.input(16) == 1:
        indicator = 0
        score += gap
        if score >= 2:
            pygame.mixer.music.pause()
            print ("Long Press")
            os.system("sudo python3 buttonFunction.py")
        elif score < 2 and score > 0 and GPIO.input(16) != 1 and count != 1:
            print("Short Press")
            buttonPressed = 5
            for i in range(int(2*beatDivision*60/425) ,int(3*beatDivision*60/425)):
                pixel[i] = newCOLOR
                time.sleep(0.01)
            count = 1
            currentTime = (pygame.mixer.music.get_pos())/1000
            newTime = currentTime
            #print ("TIME - " + str(currentTime))
            currentIndex = int((currentTime/songLength)*totalBeats)
            #print("INDEX - " + str(currentIndex))
            print(candidatesList[currentIndex])
            for candidate in candidatesList[currentIndex]:
                if candidate in range(int(4*beatDivision*60/425),int(5*beatDivision*60/425)):
                    if candidate in beat_id:
                         print (candidate)
                         currentIndex = (beat_id.index(candidate))
                         beatGapCopy = beat_id[currentIndex] - beat_id[pastIndex]
                         if beatGapCopy < 0:
                             stepperIndicator += 2
                         elif beatGapCopy > 0:
                             stepperIndicator +=1
                         print ("New Index - " + str(currentIndex))
                         print ("New Time - " + str(time_of_beat[currentIndex]))
                         pygame.mixer.music.pause()
                         pygame.mixer.music.play(loops = 0, start = time_of_beat[currentIndex])
                         count = 0
                         print ("MATCHED")
                         for i in range(int(4*beatDivision*60/425), int(5*beatDivision*60/425)):
                             pixel[i] = CLEAR
                             time.sleep(0.01)

    if indicator == 1 and GPIO.input(20) == 1:
        indicator = 0
        score += gap
        if score >= 2:
            pygame.mixer.music.pause()
            print ("Long Press")
            os.system("sudo python3 buttonFunction.py")
        elif score < 2 and score > 0 and GPIO.input(20) != 1 and count != 1:
            print("Short Press")
            buttonPressed = 6
            for i in range(int(5*beatDivision*60/425) ,int(6*beatDivision*60/425)):
                pixel[i] = newCOLOR
                time.sleep(0.01)
            count = 1
            currentTime = (pygame.mixer.music.get_pos())/1000
            newTime = currentTime
            #print ("TIME - " + str(currentTime))
            currentIndex = int((currentTime/songLength)*totalBeats)
            #print("INDEX - " + str(currentIndex))
            print(candidatesList[currentIndex])
            for candidate in candidatesList[currentIndex]:
                if candidate in range(int(5*beatDivision*60/425),int(6*beatDivision*60/425)):
                    if candidate in beat_id:
                         print (candidate)
                         currentIndex = (beat_id.index(candidate))
                         beatGapCopy = beat_id[currentIndex] - beat_id[pastIndex]
                         if beatGapCopy < 0:
                             stepperIndicator += 2
                         elif beatGapCopy > 0:
                             stepperIndicator += 1
                         print ("New Index - " + str(currentIndex))
                         print ("New Time - " + str(time_of_beat[currentIndex]))
                         pygame.mixer.music.pause()
                         pygame.mixer.music.play(loops = 0, start = time_of_beat[currentIndex])
                         count = 0
                         print ("MATCHED")
                         for i in range(int(5*beatDivision*60/425), int(6*beatDivision*60/425)):
                             pixel[i] = CLEAR
                             time.sleep(0.01)


    # If we didn't immediately find a match, we need to search for a match until we find one
    if count == 1 and indicator == 0:
        currentTime = (pygame.mixer.music.get_pos())/1000
        currentIndex = int((currentTime/songLength)*totalBeats)

        #Find an appropriate candidate
        for candidate in candidatesList[currentIndex]:
            if candidate in range(int((buttonPressed-1)*beatDivision*60/425),int(beatDivision*buttonPressed*60/425)):
                if candidate in beat_id:
                    # An appropriate candidate was found
                    print ("Candidate found")
                    count = 0

                    currentIndex = (beat_id.index(candidate))
                    print("New Index - " + str(currentIndex))
                    print ("New Time - " + str(time_of_beat[currentIndex]))
                    pygame.mixer.music.pause()
                    pygame.mixer.music.play(loops = 0, start = time_of_beat[currentIndex])
                    for i in range(int((buttonPressed-1)*beatDivision*60/425),int(beatDivision*buttonPressed*60/425)):
                        pixel[i] = CLEAR
                        time.sleep(0.01)
        print (currentTime - newTime)
        if currentTime - newTime > 7:
            # If we searched for more than 7 seconds, cancel the search and keep playing normally
            print("Waited too long")
            print ("SCORE | " + str(score))
            score =0
            for i in range(int((buttonPressed-1)*beatDivision*60/425),int(beatDivision*buttonPressed*60/425)):
                pixel[i] = CLEAR
                time.sleep(0.02)
            count = 0
            buttonPressed = 0

    servoCount = 0
    if stepperIndicator > 0: # If we have jumped, raise the servo
        for i in range(len(posList1)):
            servo.value = posList1[i]
            time.sleep(0.003)

    stepperTimeEnd = time.time()
    stepperDifference = stepperTimeEnd - stepperTimeStart
    delayFactor = 10 # In testing, it was found that going forward was easier going backwards, delayFactor2 is the scale factor for backwards rotation
    delayFactor2 = 14

    if stepperIndicator == 0:
        # If we aren't jumping, play back normally
        stepperCount = forward(stepList, stepperCount)
        time.sleep(0.019)
    elif stepperIndicator == 1:
        # If we are jumping forwards (e.g. beat 101 - beat 175)
        delayAmount = int(beatGap*delayFactor)
        for i in range(delayAmount):
            stepperCount = forward(stepList, stepperCount)
            time.sleep(0.002)
    elif stepperIndicator == 2:
        # If we are jumping backwards (e.g beat 242 - beat 32)
        beatGap = beatGap *-1
        delayAmount = int(beatGap*delayFactor2)
        for i in range(delayAmount):
             stepperCount = backwards(stepList, stepperCount)
             time.sleep(0.002)
    stepperTimeStart = time.time()

    # Lower the servo now we have moved
    if stepperIndicator > 0:
        for i in range(len(posList2)):
            servo.value = posList2[i]
        stepperIndicator = 0
    #Reset the timings at the end of each loop
    time2 = time.time()
    gap = time2-time1

