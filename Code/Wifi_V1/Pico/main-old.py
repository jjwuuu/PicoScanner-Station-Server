from machine import Pin
import neopixel
import micropython
import time
from mfrc522 import MFRC522
from wifi_info import wifi_connect, connectSocket, sendToServer, sendStatus
import network
import socket
from constants import *

#Default values
state = READY
cardIn = False   #bool for the state of the card
success = False  #bool for the state of card read
target = 209451056 #ID Number of valid card
reader = MFRC522(spi_id=0,sck=2,miso=4,mosi=3,cs=1,rst=0)
start = time.time() #debug var
reader.init()
online = False

# when the pin changes, set cardin to true if switch pressed down, false otherwise
def cardChange(pinNum):
    global cardIn
    cardIn = True if (limit_switch.value() == 0) else False
    print(cardIn)

#limit switch triggers interrupt on rising or falling edge
limit_switch = Pin(27, Pin.IN, Pin.PULL_UP)
limit_switch.irq(handler=cardChange, trigger = Pin.IRQ_RISING | Pin.IRQ_FALLING)

#outputBit will power on equipment
outputBit = Pin(28, Pin.OUT)
outputBit.value(0)

#RGB LED for feedback
np = neopixel.NeoPixel(machine.Pin(18), 1)
RGB = {
    "RED": (255, 0, 0),
    "GREEN": (0, 255, 0),
    "BLUE": (0, 0, 255),
    "YELLOW": (255, 255, 0),
    "PURPLE": (255, 0, 255)
}

#function to output to RGB LED
def RGBOutput(color):
    np[0] = RGB[color]
    np.write()
     
def sendInfo(msg):
    global online
    if online:
        online = sendStatus(msg)
    
#funciton that reads from the RFID, it takes n reads and if the number of correct reads
#(hits) is greater than k, return a success, otherwise failure. Set RGB depending on outcome.
        
def read(n = 6, k = 3):
    global online
    hits = 0
    for i in range(n):
        (stat, tag_type) = reader.request(reader.REQIDL)
        if stat == reader.OK:
            (stat, uid) = reader.SelectTagSN()
            if stat == reader.OK:
                card = int.from_bytes(bytes(uid),"little",False)
                print("CARD ID: "+str(card))
                if (card == target):
                    hits += 1
                    
    result = True if (hits >= k) else False
    
    if result:
        RGBOutput("BLUE")
        outputBit.value(1)
        connectSocket("True")
    else:
        RGBOutput("RED")
    return result

#Unused state, planned for future 
def cleanup():
    global online
    elapsedTime = round((time.time()-runTime)/60, 1)
    if elapsedTime > 0:
        sendInfo("Work Ended: "+  str(elapsedTime) +' mins.')
    
    
if __name__ == "__main__":
    runTime = time.time()
    RGBOutput("YELLOW")
    
    #wifi setup & connection to server
    online = wifi_connect()
    socket_time = time.time()
    
    
    while True:
        #print(time.time() - start)
        time.sleep(0.05)
        #if not online and time.time()-socket_time > 600: #Every 10 Minutes
            #online = connectSocket(machineID = "Test ID")
            #socket_time=time.time()
            
        if cardIn:
            if state == READY:
                state = READING
            elif state == READING:
                success = read()
                if success:
                    runTime = time.time()
                state = WORKING
            elif state == WORKING:
                continue
            else:
                print("UNKNOWN STATE - CARD")
                
        else:
            outputBit.value(0)
            if success:
                state = CLEANUP
            else:
                state = READY
                
            if state == READY:
                if online:
                    RGBOutput("GREEN")
                else:
                    RGBOutput("PURPLE")
            
            elif state == CLEANUP:
                #cleanup()
                connectSocket("False")
                success = False
                state = 0
            else:
                print("UNKNOWN STATE - NO CARD")

