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

#Colors
BLACK = [0,0,0]
BLUE = [0,0,1]
GREEN = [0,1,0]
RED = [1,0,0]
PURPLE = [1,0,1]
CYAN = [0,1,1]
YELLOW = [1,1,0]
WHITE = [1,1,1]

