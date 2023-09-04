from machine import Pin, reset_cause

try:	# initialize
	L = open('rc-codes.txt').readline().split('\t')
	if L[0]=='__preinit__':
		exec(L[-1])
	del L
except:
	pass

import sys, machine, gc, network
gc.collect()

ap_if = network.WLAN(network.AP_IF)
ap_if.active(False)
sta_if = network.WLAN(network.STA_IF)

# To enter rescue mode, create a Wifi hotspot with both SSID and password being 'RESCUE-ESP'
if reset_cause() == machine.PWRON_RESET:
	import update
	update.rescue()
else:
	sta_if.active(False)

# try:
from main import *
gc.collect()

if reset_cause()>4:
	sys.exit()
run()
machine.reset()
# except Exception as e:
# 	machine.UART(0, 115200, tx=Pin(1), rx=Pin(3))
# 	sys.print_exception(e)
