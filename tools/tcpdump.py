#!/usr/bin/env python3

import argparse, os, sys, subprocess, gzip, json
from select import select

def Open(fn, mode='r', **kwargs):
        if fn == '-':
                return (sys.stdout.buffer if 'b' in mode else sys.stdout) if 'w' in mode else (sys.stdin.buffer if 'b' in mode else sys.stdin)
        fn = os.path.expanduser(fn)
        return gzip.open(fn, mode, **kwargs) if fn.lower().endswith('.gz') else open(fn, mode, **kwargs)

over_cap_line = b''
def get_packet():
	global over_cap_line
	ret = over_cap_line
	over_cap_line = b''
	ret += P.stdout.readline()
	while True:
		rlist, _, _ = select([P.stdout], [], [], 5)
		if not rlist: break
		L = P.stdout.readline()
		if L.startswith(b'\t'):
			ret += L
		else:
			over_cap_line = L
			break
	return ret.splitlines()

def split_ip_port(t):
	its = t.decode().strip(':').split('.')
	return '.'.join(its[0:4]), int(its[4])

ip_to_int = lambda ip: int(''.join([('%02x'%int(i)) for i in ip.split('.')]), 16)

def parse_tcp(pkt):
	try:
		Ls = pkt
		its = Ls[0].split(b' ')
		assert Ls[0][0:1].isdigit() and its[1]==b'IP'
		srcAddr, _, dstAddr = its[2:5]
		srcPort, dstPort = ['%04x'%(int(a.strip(b':').split(b'.')[-1])) for a in [srcAddr, dstAddr]]
		data = [t[i:i+2] for L in Ls[1:] for t in L[10:50].split() for i in [0,2]]
		bdata = bytes.fromhex(b''.join(data).decode())
		marker = bytes.fromhex(srcPort+dstPort)
		posi = bdata.find(marker)
		pair = bdata[posi+12]
		dw_len = pair>>4
		assert (pair&0xf)==0
		srcIP, srcPort = split_ip_port(srcAddr)
		dstIP, dstPort = split_ip_port(dstAddr)
		return {'from_ip':srcIP, 'to_ip':dstIP, 'from_port':srcPort, 'to_port':dstPort, 'firstline': Ls[0].decode(),
			'srcIPint': ip_to_int(srcIP), 'dstIPint': ip_to_int(dstIP), 'data': bdata[posi+dw_len*4:]}
	except Exception as e:
		return None


def split_packets(txt):
	chunks, chunk = [], []
	for L in txt.splitlines():
		if not L.strip(): continue
		if L.startswith(b'\t'):
			chunk += [L]
		else:
			if chunk:
				chunks += [chunk]
			chunk = [L]
	if chunk:
		chunks += [chunk]
	return chunks


def apply_filter(obj):
	global from_ip, to_ip, from_port, to_port, netmask
	intmask = eval(format((0xffffffff>>netmask)^0xffffffff, '#032b'))
	if from_ip and obj['from_ip']!=from_ip:
		return True
	if to_ip and obj['to_ip']!=to_ip:
		return True
	if from_port and obj['from_port']!=from_port:
		return True
	if to_port and obj['to_port']!=to_port:
		return True
	if netmask and obj['srcIPint']&intmask != obj['dstIPint']&intmask:
		return True
	return False


def print_split(bs, chk_sz, fp):
	if chk_sz<len(bs):
		for i in range(0, len(bs), chk_sz):
			print(bs[i:i+chk_sz], file=fp)
	else:
		print(bs, file=fp)


if __name__ == "__main__":
	parser = argparse.ArgumentParser(usage = '$0 arg1 1>output 2>progress', description = 'this program extract TCP data sent to an appliance',
	                                 formatter_class = argparse.ArgumentDefaultsHelpFormatter)
	parser.add_argument('--console', '-C', help = 'Take input from STDIN console', action='store_true')
	parser.add_argument('--cmd', '-c', help = 'The command line for tcpdump', default = 'sudo tcpdump -n -XX')
	parser.add_argument('--interface', '-i', help = 'Network interface to listen to (if not specified in --cmd)', default = 'wlan0')
	parser.add_argument('--finput', '-in', help = 'input file to with tcpdump content; default: - (STDIN)', default = '-')
	parser.add_argument('--output', '-o', help = 'output file to save to; default: - (STDOUT)', default = '-')
	parser.add_argument('--netmask', '-m', help = 'only capture LAN packets (srcIP & dstIP must have the same network address), e.g., 24 means 255.255.255.0', type=int, default=0)
	parser.add_argument('--to-port', '-tp', help = 'only capture packets from the specified port', type=int, default=0)
	parser.add_argument('--from-port', '-fp', help = 'only capture packets to the specified port', type=int, default=0)
	parser.add_argument('--to-ip', '-ti', help = 'only capture packets from the specified IP', default='')
	parser.add_argument('--from-ip', '-fi', help = 'only capture packets to the specified IP', default='')
	parser.add_argument('--chunk-size', '-s', help = 'chunk size for sending TCP packets', type=int, default=999999999)
	# nargs='?': optional positional argument; action='append': multiple instances of the arg; type=; default=
	opt = parser.parse_args()
	globals().update(vars(opt))

	# data,info = parse_tcp(b'''17:05:19.631471 IP 10.42.0.56.58846 > 10.42.0.118.1883: Flags [P.], seq 2187042920:2187043110, ack 3328138612, win 65535, length 190
	# 0x0000:  c8ff 7782 04fc a057 e3b8 1a27 0800 4500  ..w....W...'..E.
	# 0x0010:  00e6 7e40 4000 4006 a6d0 0a2a 0038 0a2a  ..~@@.@....*.8.*
	# 0x0020:  0076 e5de 075b 825b a068 c65f 5d74 5018  .v...[.[.h._]tP.
	# 0x0030:  ffff 6f29 0000 32bb 0100 1b34 3338 2f45  ..o)..2....438/E
	# 0x0040:  3147 2d53 472d 4e47 4130 3330 3141 2f63  1G-SG-NGA0301A/c
	# 0x0050:  6f6d 6d61 6e64 000b 7b0a 2020 2264 6174  ommand..{..."dat
	# 0x0060:  6122 3a20 7b0a 2020 2020 2266 7077 7222  a":.{....."fpwr"
	# 0x0070:  3a20 224f 4646 220a 2020 7d2c 0a20 2022  :."OFF"...},..."
	# 0x0080:  6822 3a20 2234 3338 2f45 3147 2d53 472d  h":."438/E1G-SG-
	# 0x0090:  4e47 4130 3330 3141 2f63 6f6d 6d61 6e64  NGA0301A/command
	# 0x00a0:  222c 0a20 2022 6d6f 6465 2d72 6561 736f  ",..."mode-reaso
	# 0x00b0:  6e22 3a20 224c 4150 5022 2c0a 2020 226d  n":."LAPP",..."m
	# 0x00c0:  7367 223a 2022 5354 4154 452d 5345 5422  sg":."STATE-SET"
	# 0x00d0:  2c0a 2020 2274 696d 6522 3a20 2232 3032  ,..."time":."202
	# 0x00e0:  332d 3037 2d31 3954 3039 3a30 353a 3139  3-07-19T09:05:19
	# 0x00f0:  5a22 0a7d                                Z".}''')

	fp = Open(output, 'w')

	if console:	# paste in mode
		pkts = split_packets(Open(finput, 'rb').read())
		if len(pkts) > 1:
			header = True
			for ii, pkt in enumerate(pkts):
				L1 = pkt[0].decode()
				if ' IP ' not in L1 or ' Flags ' not in L1 or L1.endswith('length 0'):
					continue
				obj = parse_tcp(pkt)
				if obj == None: continue
				if not header and to_ip and to_port and obj['from_ip']==to_ip and obj['from_port']==to_port:
					print(len(obj['data']), file=fp)
					continue
				if apply_filter(obj): continue
				if header:
					header = False
					print({'protocol':'TCP', 'IP':obj['to_ip'], 'PORT':obj['to_port']}, file=fp)
				print_split(obj['data'], chunk_size, fp)
				# print(obj['data'], file=fp)
		else:
			obj = parse_tcp(pkts[0])
			print({'IP':obj['to_ip'], 'PORT':obj['to_port'], 'data': obj['data']}, file=fp)
			print({'protocol':'TCP', 'IP':obj['to_ip'], 'PORT':obj['to_port'], 'data': obj['data']}, file=sys.stderr)

	else:	# spawn process mode
		if '-i ' not in cmd and '--interface' not in cmd:
			cmd += f' -i {interface}'

		with subprocess.Popen(cmd.split(), stdout=subprocess.PIPE) as P:
			while True:
				try:
					pkt = get_packet()
					obj = parse_tcp(pkt)
					if apply_filter(obj):
						break
				except:
					continue
			P.kill()
	
			print({'IP':obj['to_ip'], 'PORT':obj['to_port'], 'data': obj['data']}, file=fp)
			print({'protocol':'TCP', 'IP':obj['to_ip'], 'PORT':obj['to_port'], 'data': obj['data']}, file=sys.stderr)

	fp.close()

