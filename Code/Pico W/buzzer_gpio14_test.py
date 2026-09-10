"""Standalone passive-piezo test for a Pico W.

Wire the piezo positive lead to GP14 and the negative lead to GND.
Save this file to the Pico W as main.py to run it by itself.
"""

from machine import PWM, Pin
import time


BUZZER_PIN = 14
VOLUME = 49152  # 75% PWM duty cycle

buzzer = PWM(Pin(BUZZER_PIN))
buzzer.duty_u16(0)


def tone(frequency, duration_ms):
    buzzer.freq(frequency)
    buzzer.duty_u16(VOLUME)
    time.sleep_ms(duration_ms)
    buzzer.duty_u16(0)
    time.sleep_ms(35)


def startup_jingle():
    # A short, distinctive test sequence rather than a reader status signal.
    for frequency, duration_ms in (
        (523, 120),
        (659, 120),
        (784, 120),
        (1047, 220),
    ):
        tone(frequency, duration_ms)


def frequency_sweep():
    for frequency in range(300, 1801, 100):
        tone(frequency, 35)


try:
    print("GPIO 14 piezo test running")
    while True:
        startup_jingle()
        frequency_sweep()
        print("Test complete; repeating in 3 seconds")
        time.sleep(3)
finally:
    buzzer.duty_u16(0)
    buzzer.deinit()
