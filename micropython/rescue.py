import os, sys, esp, machine, time, network
from machine import Pin


def rescue():
	LED = Pin(2, Pin.OUT)
	LED(0)
	sta_if = network.WLAN(network.STA_IF)
	sta_if.active(True)
	if b'RESCUE-ESP' in [i[0] for i in sta_if.scan()]:
		sta_if.connect('RESCUE-ESP', 'RESCUE-ESP')
		x = 0
		while not sta_if.isconnected():
			x += 1
			LED(x&1)
			time.sleep(0.25)
		import webrepl
		webrepl.start()
		Pin(2, Pin.IN)
		sys.exit()
		