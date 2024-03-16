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

gc.collect()
from main import *
