import time
import socket
import network

ssid = "ATT-WIFI-9z26"
password = '29QzM6s2'
server_ip = '192.168.1.59'
port = 5000
server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

class ScannerStatus:
    def __init__(self, isOn):
        self.machineID = 12345
        self.isOn = isOn

def wifi_connect():
    global wlan
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    wlan.connect(ssid, password)

    max_wait = 10
    print('Attempting To Connect.')
    while max_wait > 0:
        if wlan.status() < 0 or wlan.status() >= 3:
            break
        max_wait -= 1
        
        time.sleep(1)

    if wlan.status() == 3:
        print('Connected to Wifi')
        status = wlan.ifconfig()
        print( 'ip = ' + status[0])
        return True
    else:
        #raise RuntimeError('Network Connection Failed')
        print('Network Connection Failed')
        return False 
        
def connectSocket(machineID = "Test ID"):
    global server
    try:
        ai = socket.getaddrinfo("192.168.56.1", 80) # Address of Web Server
        print(ai)
        server.connect((server_ip, port))
        return sendToServer(machineID)
        return True
    except:
        print('Failed To Connect to Server: OFFLINE MODE')
        return False
    
#function to send a message to the server
def sendToServer(msg):
    try:
        server.sendall(bytearray(msg, 'utf-8'))
        return True
    except:
        return False
    
def sendStatus(status):
    try:
        msg = "125467-" + status
        server.sendall(bytearray(msg, 'utf-8'))
        return True
    except:
        return False
      

if __name__ == "__main__":
    runTime = time.time()
    
    #wifi setup & connection to server
    #online = wifi_connect()
    online = connectSocket(machineID = "PC TEST")
    socket_time = time.time()
    
    
    while True:
        #print(time.time() - start)
        time.sleep(0.05)
        if not online and time.time()-socket_time > 600: #Every 10 Minutes
            online = connectSocket(machineID = "PC TEST")
            socket_time=time.time()
