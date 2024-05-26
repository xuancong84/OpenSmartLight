#!/usr/bin/env python3
# coding=utf-8

import os, sys, argparse, string, time

run = os.system

if __name__=='__main__':
	parser = argparse.ArgumentParser(usage='$0 arg1 1>output 2>progress', description='what this program does',
			formatter_class=argparse.ArgumentDefaultsHelpFormatter)
	parser.add_argument('payload', help='the payload hex string to advertise')
	parser.add_argument('-t', '--duration', help='advertise duration (in seconds)', default=1, type=float)
	#nargs='?': optional positional argument; action='append': multiple instances of the arg; type=; default=
	opt=parser.parse_args()
	globals().update(vars(opt))

	s = payload.lower()
	assert len(s)%2==0
	assert all(c in string.hexdigits for c in s)
	data = ' '.join([s[i:i+2] for i in range(0, len(s), 2)])

	run('hciconfig hci0 up')
	run(f'hcitool -i hci0 cmd 0x08 0x0008 {"%02x"%(len(s)//2)} {data}')
	run('hcitool -i hci0 cmd 0x08 0x0006 a0 00 a0 00 03 00 00 00 00 00 00 00 00 07 00')
	run('hcitool -i hci0 cmd 0x08 0x000a 01')
	time.sleep(duration)
	run('hcitool -i hci0 cmd 0x08 0x000a 00')
