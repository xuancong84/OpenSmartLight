# This file is executed on every boot (including wake-boot from deepsleep)
#import esp
#esp.osdebug(None)
import os, machine, gc, network, time
#os.dupterm(None, 1) # disable REPL on UART(0)

sta_if = network.WLAN(network.STA_IF)
ap_if = network.WLAN(network.AP_IF)
sta_if.active(False)
ap_if.active(False)

gc.collect()

mains = [f for f in os.listdir() if f.startswith('main')]

try:
	if mains:
		exec(f'from {mains[0].split(".")[0]} import *')
		gc.collect()
		p16 = machine.Pin(16, machine.Pin.OUT)
		p16(1)
		time.sleep(0.1)
		if machine.Pin(16, machine.Pin.IN)():
			run()
except:
	ap_if.active(True)
	import webrepl
	webrepl.start()