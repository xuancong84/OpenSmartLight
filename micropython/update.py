import os, sys, esp, machine, time
from machine import Pin

def fwupdate(fn):
	from machine import WDT
	esp.setn(0)
	with open(fn, 'rb') as fp:
		while fp.read(4096):pass

	blks, offs = esp.showblks()
	nblks = esp.getn()
	esp.setn(-1)
	rem_fs = os.stat(fn)[6]
	print(f'Verifying sector data:{blks} {offs}')
	with open(fn, 'rb') as fp:
		for ii,blkid in enumerate(blks):
			sz = min(rem_fs, 4096-offs[ii])
			L2 = esp.flash_read(esp.flash_user_start()+blkid*4096+offs[ii], sz)
			L1 = fp.read(sz)
			if L1!=L2:
				print(f'Data is different at {ii} {blkid}')
				return
			del L1, L2
			rem_fs -= sz
			print(f'{ii}/{len(blks)}', end='\r')
	print('Success, starting firmware update, please wait ...')
	esp.setn(nblks)
	esp.DFU()

def rescue(sta_if):
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