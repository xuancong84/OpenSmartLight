#!/usr/bin/env python3

import torch, os, whisper, argparse

if __name__ == '__main__':
	parser = argparse.ArgumentParser(usage='$0 [options]', description='launch the smart home server',
			formatter_class=argparse.ArgumentDefaultsHelpFormatter)
	parser.add_argument('--model', '-m', default='base', help='ASR model to load')
	parser.add_argument('--file', '-f', default='/dev/shm/speech.m4a', help='speech file location')
	opt=parser.parse_args()
	globals().update(vars(opt))

	M = whisper.load_model('tiny')
	obj = M.transcribe(os.path.expanduser('/dev/shm/speech.m4a'))
	print(obj)
