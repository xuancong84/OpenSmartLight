from machine import Pin, reset_cause

try:	# initialize
	with open('rc-codes.txt') as fp:
		L = fp.readline().split('\t')
		if L[0]=='__preinit__':
			exec(L[-1])
		del L
except:
	pass

import sys, machine, gc, network
gc.collect()

network.WLAN(network.AP_IF).active(False)
network.WLAN(network.STA_IF).active(False)

# To enter rescue mode, create a Wifi hotspot with both SSID and password being 'RESCUE-ESP'
if reset_cause() == machine.PWRON_RESET:
	import rescue
	rescue.rescue()
	import lib_common as g
	g.SMART_CTRL = False

# try:
from main import *
gc.collect()

if isFile('debug') and reset_cause()>4:
	sys.exit()
run()
machine.reset()
# except Exception as e:
# 	machine.UART(0, 115200, tx=Pin(1), rx=Pin(3))
# 	sys.print_exception(e)
