import os
import RPi.GPIO as GPIO
import time
import neopixel
import board

GPIO.setwarnings(False)
GPIO.setmode(GPIO.BCM)

GPIO.setup(20, GPIO.IN, pull_up_down=GPIO.PUD_DOWN) #Setup button pins
GPIO.setup(16, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
GPIO.setup(26, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
GPIO.setup(19, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
GPIO.setup(13, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)

enable_pin = 24 #Setup stepper motor pins
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

pixel_pin = board.D21 #Setup Neopixels
num_pixels = 60
ORDER = neopixel.GRB
CLEAR = (0,0,0)
pixels = neopixel.NeoPixel(pixel_pin, num_pixels, brightness=0.03, auto_write=False,
                           pixel_order=ORDER)
pixel = neopixel.NeoPixel(pixel_pin, num_pixels, brightness = 0.1, pixel_order = ORDER)

def setStep(w1,w2,w3,w4): #Send instructions to the stepper motor
    GPIO.output(A1Pin, w1)
    GPIO.output(A2Pin, w2)
    GPIO.output(B1Pin, w3)
    GPIO.output(B2Pin, w4)

def wheel(pos): #Function to generate a wheel on NeoPixels, taken from Adafruit
    # Input a value 0 to 255 to get a color value.
    # The colours are a transition r - g - b - back to r.
    if pos < 0 or pos > 255:
        r = g = b = 0
    elif pos < 85:
        r = int(pos * 3)
        g = int(255 - pos*3)
        b = 0
    elif pos < 170:
        pos -= 85
        r = int(255 - pos*3)
        g = 0
        b = int(pos*3)
    else:
        pos -= 170
        r = 0
        g = int(pos*3)
        b = int(255 - pos*3)
    return (r, g, b) if ORDER == neopixel.RGB or ORDER == neopixel.GRB else (r, g, b, 0)

def rainbow_cycle(wait): #Function to make the wheel transition through the entire colour spectrum, taken from Adafruit
    for j in range(255):
        for i in range(num_pixels):
            pixel_index = (i * 256 // num_pixels) + j
            pixels[i] = wheel(pixel_index & 255)
        pixels.show()
        time.sleep(wait)

stepList = [(1,0,0,0),(1,1,0,0),(0,1,0,0),(0,1,1,0),(0,0,1,0),(0,0,1,1),(0,0,0,1),(1,0,0,1)] #List of positions for stepper motor
count = 0
def backwards(list, count): #Function to turn the motor backwards by sending the stepList in a certian way
    w1 = list[count][0]
    w2 = list[count][1]
    w3 = list[count][2]
    w4 = list[count][3]
    setStep(w1,w2,w3,w4)
    count+=1
    if count >= 8:
        count = 0
    return count

for i in range(60): #Loading circle, shows Gizmo is ready to use
    pixel[i] = (200,100,0)
    time.sleep(0.02)
while True:
    for j in range(255): #NeoPixels transistion through rainbow colours
        for i in range(num_pixels):
            pixel_index = (i * 256 // num_pixels) + j
            pixels[i] = wheel(pixel_index & 255)
        pixels.show()
        time.sleep(0.005)
        if GPIO.input(20) == GPIO.HIGH: # Button 1 turns the pointer back to the start position
            count = backwards(stepList, count)
            print ("Pin 20")
        if GPIO.input(13) == GPIO.HIGH: # The other buttons select the songs
            print ("Here comes the sun")
            os.system("python3 song2.py")
        if GPIO.input(19) == GPIO.HIGH:
            print ("Button - September")
            os.system("python3 song4.py")
        if GPIO.input(26) == GPIO.HIGH:
            print ("Button (26) 4 - Wonderwall")
            os.system("python3 song1.py")
        if GPIO.input(16) == GPIO.HIGH:
            print ("Button (16) 6 - Shape of You")
            os.system("python3 song5.py")
