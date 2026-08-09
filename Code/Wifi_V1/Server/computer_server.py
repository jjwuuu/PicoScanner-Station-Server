import socket             
import asyncio
import threading
import time
import pickle
from kasa import Discover, SmartStrip

async def switchSmartPlug(strip):
    while True:
        try:
            pico, addr = s.accept()
            data = pico.recv(2048).decode() #Pico ID
            #Enters loop where pico data is received
            #Decodes message sent by Pico
            id = data.split("-")[0]
            state = data.split("-")[1]
            print(data)
            if state == 'True':
                await strip.children[0].turn_on()
            elif state == 'False':
                await strip.children[0].turn_off()
            pico.close()
            print("Connection Closed")
        except Exception as e:
            print(e)
            pico.close()
            print("Exception")
    

found_devices = asyncio.run(Discover.discover())
strip = SmartStrip("192.168.1.61")
asyncio.run(strip.update())
print(strip.alias)
print(found_devices)
[print(dev.alias) for dev in found_devices]

hostname = socket.gethostname()
ip = socket.gethostbyname(hostname)

print(hostname)
print(ip)
s = socket.socket()       
print ("Socket successfully created") 
  
port = 12345


addr = socket.getaddrinfo('0.0.0.0', 80)[0][-1]

s = socket.socket()
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(("", 5000))
print("Socket:", s.getsockname())

s.listen(1)
machineID = ""

asyncio.run(switchSmartPlug(strip))