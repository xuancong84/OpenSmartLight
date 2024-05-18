import os, sys, esp, machine, time, network
from machine import Pin


def rescue():
	LED1 = Pin(12, Pin.OUT)
	LED2 = Pin(13, Pin.OUT)
	sta_if = network.WLAN(network.STA_IF)
	sta_if.active(True)
	if b'RESCUE-ESP' in [i[0] for i in sta_if.scan()]:
		sta_if.connect('RESCUE-ESP', 'rescue-esp')
		x = 0
		while not sta_if.isconnected():
			x += 1
			LED1(x&1)
			LED2(not x&1)
			time.sleep(0.25)
		Pin(12, Pin.IN)
		Pin(13, Pin.IN)
		os.dupterm(None, 1)
		import webrepl
		webrepl.start()
		sys.exit()
	else:
		Pin(12, Pin.IN)
		Pin(13, Pin.IN)
		sta_if.active(False)
		