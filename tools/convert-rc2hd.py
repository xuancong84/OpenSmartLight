#!/usr/bin/env python3
# coding=utf-8

import os, sys, argparse, re, gzip, random, string
from collections import defaultdict

def RANDOM(len=20):
	return ''.join(random.choices(string.ascii_letters + string.digits, k=len))

def Open(fn, mode='r', **kwargs):
	if fn == '-':
		return sys.stdin if mode.startswith('r') else sys.stdout
	fn = os.path.expanduser(fn)
	return gzip.open(fn, mode, **kwargs) if fn.lower().endswith('.gz') else open(fn, mode, **kwargs)

def get_3lists(rc_):
	# filter out unwanted
	rc = [its for its in rc_ if len(its)>1 and not its[0].startswith('__')]
	assert len(set([len(its) for its in rc]))==1, 'inconsistent number of columns'

	# split between voice commands and voice sentence IDs
	lst_vcmd = [its for its in rc if not its[0].isdigit()]
	lst_vsid = [its[:2] for its in rc if its[0].isdigit()]

	# output 1: voice speech ID
	ids_vsid = [its[0] for its in lst_vsid]
	assert len(set(ids_vsid))==len(ids_vsid), 'duplicate voice speech IDs'
	sid2int = defaultdict(lambda: -1, {vs:(1000+int(ii)) for ii,vs in lst_vsid})
	for its in lst_vcmd:
		vs = its[2]
		if vs and vs not in sid2int:
			sid2int[vs] = max(sid2int.values())+1

	out_vsid = [[str(ii), vs] for vs,ii in sid2int.items()]

	# expand lst_vcmd by |
	get_options = lambda t: t.replace('｜', '|').split('|')
	lst_vcmd = [its[:1]+[desc]+its[2:] for its in lst_vcmd for desc in get_options(its[1])]

	# output 2: voice command list
	out_vcmd = [*map(lambda t:t[1], lst_vcmd)]

	# output 3: combined list = [[UART:str, ReqL:str, reply:int, SetL:int]]
	out_full = [[its[0], its[3], sid2int[its[2]], its[4]] for its in lst_vcmd]
	SPL = set([its[3] for its in out_full if its[3]])	# special level
	SPL2int = {name:ii+100 for ii, name in enumerate(SPL)}	# special level map
	cmd2int = {its[0]:ii for ii, its in enumerate(out_full)} 	# voice command map

	for its in out_full:
		setL = its[3]
		its[3] = SPL2int[setL] if setL else -1
		reqL = its[1]
		if len(reqL)>1:
			out = []
			for p in reqL.split():
				s,t = p.split('_')
				assert s in SPL2int, 'src (source) must be in SPL2int (special level map)'
				assert t in cmd2int, 'tgt (target) must be in SPL2int (special level map)'
				out += [str(SPL2int[s]*1000 + cmd2int[t])]
			its[1] = ' '.join(out)

	return out_vcmd, out_vsid, out_full

def locate(full_str, key, start, stop):
	pos_key = full_str.find(key)
	stt_key = full_str[:pos_key].rfind(start)
	end_key = full_str[pos_key:].find(stop)+len(stop)+pos_key
	return stt_key, end_key

def inject(rc, hd):
	lst_vcmd, lst_vsid, lst_full = get_3lists(rc)

	stt_vcmd0, end_vcmd0 = locate(hd, 'VCMD0', '<block', '<next>')
	stt_vsid0, end_vsid0 = locate(hd, 'VSID0', '<block', '<next>')
	stt_fdata, end_fdata = hd.find('FDATA0'), hd.find('FDATA0')+6
	ins_blknx = stt_fdata + hd[stt_fdata:].find('</block></next>')

	s_out = hd[:stt_vcmd0] \
		+ ''.join([f'<block type="asr_id" id="{RANDOM()}"><field name="ASR">{cmd}</field><field name="leibie">命令词</field><field name="huifu"></field><field name="id">{ii}</field><next>' for ii,cmd in enumerate(lst_vcmd)])\
		+ ''.join([f'<block type="asr_add_id" id="{RANDOM()}"><field name="NAME">{vs}</field><field name="id">{ii}</field><next>' for ii,vs in lst_vsid])\
		+ hd[end_vsid0:stt_fdata] \
		+ '　'.join(['\t'.join([*map(str,its)]) for its in lst_full]) \
		+ hd[end_fdata:ins_blknx] \
		+ '</block></next>'*(len(lst_vcmd+lst_vsid)-2) \
		+ hd[ins_blknx:]
	
	return s_out


if __name__=='__main__':
	parser = argparse.ArgumentParser(usage='$0 input-rc-code.txt input.hd 1>output 2>progress',
			description='This injects voice commands data from input-rc-code.txt into input.hd',
			formatter_class=argparse.ArgumentDefaultsHelpFormatter)
	parser.add_argument('rc_file', help='input file rc-code.txt')
	parser.add_argument('hd_file', help='input file twenblock-project.hd')
	parser.add_argument('-optional', help='optional argument')
	#nargs='?': optional positional argument; action='append': multiple instances of the arg; type=; default=
	opt=parser.parse_args()
	globals().update(vars(opt))

	rc_data = [L.split('\t') for L in Open(rc_file).read().splitlines()]
	hd_data = Open(hd_file).read()

	print(inject(rc_data, hd_data))
