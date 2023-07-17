# This file is executed on every boot (including wake-boot from deepsleep)
#import esp
#esp.osdebug(None)
import os, machine, gc, network, time
#os.dupterm(None, 1) # disable REPL on UART(0)

sta_if = network.WLAN(network.STA_IF)
ap_if = network.WLAN(network.AP_IF)
sta_if.active(False)
ap_if.active(False)

if True:
	sta_if.active(True)
	import webrepl
	webrepl.start()

gc.collect()

DBPin = machine.Pin(12, machine.Pin.IN, machine.Pin.PULL_UP)
mains = [f for f in os.listdir() if f.startswith('main')]

if mains:
	exec(f'from {mains[0].split(".")[0]} import *')
	if DBPin():
		run()
