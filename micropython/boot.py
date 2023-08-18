import os, sys, machine, gc, network, time
from machine import Pin

ap_if = network.WLAN(network.AP_IF)
ap_if.active(False)
sta_if = network.WLAN(network.STA_IF)

if machine.reset_cause() == machine.PWRON_RESET:
	LED = Pin(2, Pin.OUT)
	LED(0)
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
else:
	sta_if.active(False)

mains = [f for f in os.listdir() if f.startswith('main')]

if not mains:
	sys.exit()

try:
	gc.collect()
	exec(f'from {mains[0].split(".")[0]} import *')
	gc.collect()
	p16 = Pin(16, Pin.OUT)
	p16(1)
	time.sleep(0.1)
	if True or not Pin(16, Pin.IN)():
		sys.exit()
	run()
	machine.reset()
except Exception as e:
	machine.UART(0, 115200, tx=Pin(1), rx=Pin(3))
	print(e)
