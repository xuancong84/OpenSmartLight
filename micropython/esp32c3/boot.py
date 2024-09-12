from machine import Pin, reset_cause, reset

try:	# initialize
	fp = open('rc-codes.txt')
	L = fp.readline().split('\t')
	if L[0]=='__preinit__':
		exec(L[-1])
	fp.close()
	del L, fp
except:
	pass

# To enter rescue mode, create a Wifi hotspot with SSID 'RESCUE-ESP' and password 'rescue-esp'
try:
	open('debug').close()
except:
	import gc, rescue
	rescue.rescue()
	del rescue
	gc.collect()

from main import *
gc.collect()

if not isFile('debug') or reset_cause()==1:
	run()
	reset()
