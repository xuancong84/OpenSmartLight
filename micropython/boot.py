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

# To enter rescue mode, create a Wifi hotspot with SSID 'RESCUE-ESP' and password 'rescue-esp'
try:
	open('debug').close()
except:
	import rescue
	rescue.rescue()
	del rescue

# try:
from main import *
gc.collect()

if isFile('debug') and reset_cause():
	sys.exit()
run()
machine.reset()
# except Exception as e:
# 	machine.UART(0, 115200, tx=Pin(1), rx=Pin(3))
# 	sys.print_exception(e)
