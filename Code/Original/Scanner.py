from machine import Pin
import micropython
import time
from mfrc522 import MFRC522

'''
The state variable keeps track of the current state of the device.
It is used for checking what the previous state was.
Ready: No Card - Waiting for one to be inserted 
Reading: Card Inserted - Reading the ID
Working: Card Inserted - Waiting for removal
Cleanup: No Card - Cleanup
'''
#State Encoding
READY = 0 
READING = 1
WORKING = 2
CLEANUP = 3

#Default values
state = 0
cardIn = False   #bool for the state of the card
success = False  #bool for the state of card read
target = 209451056 #ID Number of valid card
reader = MFRC522(spi_id=0,sck=2,miso=4,mosi=3,cs=1,rst=0)
start = time.time() #debug var
reader.init()

# when the pin changes, set cardin to true if switch pressed down, false otherwise
def cardChange(pinNum):
    global cardIn
    cardIn = True if (limit_switch.value() == 0) else False

#limit switch triggers interrupt on rising or falling edge
limit_switch = Pin(27, Pin.IN, Pin.PULL_UP)
limit_switch.irq(handler=cardChange, trigger = Pin.IRQ_RISING | Pin.IRQ_FALLING)

#outputBit will power on equipment
outputBit = Pin(28, Pin.OUT)
outputBit.value(0)

#RGB LED for feedback
RGB = [Pin(18, Pin.OUT), Pin(17, Pin.OUT), Pin(16, Pin.OUT)]

#function to output to RGB LED
def RGBOutput(color):
    for i in range(len(RGB)):
        RGB[i].value(color[i])
      
#funciton that reads from the RFID, it takes n reads and if the number of correct reads
#(hits) is greater than k, return a success, otherwise failure. Set RGB depending on outcome.
        
def read(n = 6, k = 3):
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
        RGBOutput([0,0,1])
        outputBit.value(1)
    else:
        RGBOutput([1,0,0])
    return result

#Unused state, planned for future 
def cleanup():
    print('Clean')

while True:
    #print(time.time() - start)
    time.sleep(0.05)
    if cardIn:
        if state == READY:
            state = READING
        elif state == READING:
            success = read()
            state = 2
        elif state == WORKING:
            print('Wait After Read')
        else:
            print("UNKNOWN STATE - CARD")
            
    else:
        outputBit.value(0)
        if success:
            state = CLEANUP
        else:
            state = READY
            
        if state == READY:
            RGBOutput([0,1,0])
            print('Nothing')
        
        elif state == CLEANUP:
            cleanup()
            success = False
            state = 0
        else:
            print("UNKNOWN STATE - NO CARD")