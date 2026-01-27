#! /usr/bin/python3
import Jetson.GPIO as GPIO

hut_reset_pin = 29 # BOARD numbering scheme

GPIO.setmode(GPIO.BOARD)
GPIO.setwarnings(False)
GPIO.setup(hut_reset_pin, GPIO.OUT, initial=GPIO.HIGH)
