from machine import Pin
import micropython
import time
from mfrc522 import MFRC522

#Default values
state = 0
cardIn = False   #bool for the state of the card
success = False  #bool for the state of card read
target = 1111111 #ID Number of valid card
reader = MFRC522(spi_id=0,sck=2,miso=4,mosi=3,cs=1,rst=0)
start = time.time() #debug var
reader.init()

#limit switch triggers interrupt on rising or falling edge
limit_switch = Pin(27, Pin.IN, Pin.PULL_UP)

#outputBit will power on equipment
outputBit = Pin(28, Pin.OUT)
outputBit.value(0)

#RGB LED for feedback
RGB = [Pin(18, Pin.OUT), Pin(17, Pin.OUT), Pin(16, Pin.OUT)]

#function to output to RGB LED
def RGBOutput(color):
    for i in range(len(RGB)):
        RGB[i].value(color[i])
      
while True:
    print(time.time() - start)
    time.sleep(1)
    print("LED Test")
    print("Blue")
    RGBOutput([0,0,1])
    time.sleep(1)
    print("Green")
    RGBOutput([1,0,0])
    time.sleep(1)
    print("Red")
    RGBOutput([0,1,0])
    
    print("RFID TEST")
    for i in range(5):
        (stat, tag_type) = reader.request(reader.REQIDL)
        if stat == reader.OK:
            (stat, uid) = reader.SelectTagSN()
            if stat == reader.OK:
                card = int.from_bytes(bytes(uid),"little",False)
                print("CARD ID: "+str(card))
    time.sleep(1)
    print("Limit Switch Test")
    
    for i in range(10):
        print("Limit Switch", limit_switch.value())
        time.sleep(1)
        
    