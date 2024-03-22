#!/usr/bin/env python3

import os, sys, whisper, traceback, argparse, threading
from flask import Flask, request, jsonify, send_file

import time, shutil, subprocess, tarfile

import numpy as np
import soundfile as sf
import torch
from tqdm import tqdm

from lib import dataset
from lib import nets
from lib import spec_utils
import librosa


UPLOAD_FOLDER = '/dev/shm/'
ALLOWED_EXTENSIONS = {'m4a', 'mp3', 'wav'}

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 64*1024*1024
M_ASR = M_VOS = args = None
g_threads = {}


@app.route('/run_asr/<model>', methods=['POST'])
def upload_file(model):
	global M_ASR, UPLOAD_FOLDER
	# check if the post request has the file part
	if 'file' not in request.files:
		return ''
	file = request.files['file']
	file.save(os.path.join(app.config['UPLOAD_FOLDER'], file.filename))
	try:
		obj = M_ASR.transcribe(UPLOAD_FOLDER+file.filename)
		print(obj, file=sys.stderr)
		return jsonify(obj), 200
	except Exception as e:
		traceback.print_exc()
		return str(e), 500


@app.route('/run_task/<path:cmdline>')
def run_task(cmdline):
	thread = threading.Thread(target=lambda: os.system(cmdline))
	thread.start()
	while thread.ident==None: pass
	g_threads[thread.ident] = thread
	return str(thread.ident)

@app.route('/query_task/<int:task_id>')
def query_task(task_id):
	return str(g_threads[task_id].is_alive()).lower()


class Separator(object):
	def __init__(self, model, device=None, batchsize=1, cropsize=256, postprocess=False):
		self.model = model
		self.offset = model.offset
		self.device = device
		self.batchsize = batchsize
		self.cropsize = cropsize
		self.postprocess = postprocess

	def _postprocess(self, X_spec, mask):
		if self.postprocess:
			mask_mag = np.abs(mask)
			mask_mag = spec_utils.merge_artifacts(mask_mag)
			mask = mask_mag * np.exp(1.j * np.angle(mask))

		y_spec = X_spec * mask
		v_spec = X_spec - y_spec

		return y_spec, v_spec

	def _separate(self, X_spec_pad, roi_size):
		X_dataset = []
		patches = (X_spec_pad.shape[2] - 2 * self.offset) // roi_size
		for i in range(patches):
			start = i * roi_size
			X_spec_crop = X_spec_pad[:, :, start:start + self.cropsize]
			X_dataset.append(X_spec_crop)

		X_dataset = np.asarray(X_dataset)

		self.model.eval()
		with torch.no_grad():
			mask_list = []
			# To reduce the overhead, dataloader is not used.
			for i in tqdm(range(0, patches, self.batchsize)):
				X_batch = X_dataset[i: i + self.batchsize]
				X_batch = torch.from_numpy(X_batch).to(self.device)

				mask = self.model.predict_mask(X_batch)

				mask = mask.detach().cpu().numpy()
				mask = np.concatenate(mask, axis=2)
				mask_list.append(mask)

			mask = np.concatenate(mask_list, axis=2)

		return mask

	def separate(self, X_spec):
		n_frame = X_spec.shape[2]
		pad_l, pad_r, roi_size = dataset.make_padding(n_frame, self.cropsize, self.offset)
		X_spec_pad = np.pad(X_spec, ((0, 0), (0, 0), (pad_l, pad_r)), mode='constant')
		X_spec_pad /= np.abs(X_spec).max()

		mask = self._separate(X_spec_pad, roi_size)
		mask = mask[:, :, :n_frame]

		y_spec, v_spec = self._postprocess(X_spec, mask)

		return y_spec, v_spec

	def separate_tta(self, X_spec):
		n_frame = X_spec.shape[2]
		pad_l, pad_r, roi_size = dataset.make_padding(n_frame, self.cropsize, self.offset)
		X_spec_pad = np.pad(X_spec, ((0, 0), (0, 0), (pad_l, pad_r)), mode='constant')
		X_spec_pad /= X_spec_pad.max()

		mask = self._separate(X_spec_pad, roi_size)

		pad_l += roi_size // 2
		pad_r += roi_size // 2
		X_spec_pad = np.pad(X_spec, ((0, 0), (0, 0), (pad_l, pad_r)), mode='constant')
		X_spec_pad /= X_spec_pad.max()

		mask_tta = self._separate(X_spec_pad, roi_size)
		mask_tta = mask_tta[:, :, roi_size // 2:]
		mask = (mask[:, :, :n_frame] + mask_tta[:, :, :n_frame]) * 0.5

		y_spec, v_spec = self._postprocess(X_spec, mask)

		return y_spec, v_spec

def ffm_wav2m4a(input_fn, output_fn, br = '128k'):
	input_fn, output_fn = [fn.replace('"', '\\"') for fn in [input_fn, output_fn]]
	subprocess.run(['ffmpeg', '-y', '-i', input_fn, '-c:a', 'aac', '-b:a', br, output_fn])

def ffm_video2wav(input_fn, output_fn):
	# The built-in DNN model is trained on 44100 sampling rate, it can still run but does not work on other sampling rates
	input_fn, output_fn = [fn.replace('"', '\\"') for fn in [input_fn, output_fn]]
	subprocess.run(['ffmpeg', '-y', '-i', input_fn, '-f', 'wav', '-ar', '44100', output_fn])

def split_vocal_by_dnn(in_wav, out_wav_nonvocal, out_wav_vocal):
	global args
	print('Loading wave source ...', end = ' ', flush = True)
	X, sr = librosa.load(in_wav, sr=args.sr, mono=False, dtype = np.float32, res_type = 'kaiser_fast')
	print('done', flush = True)

	if X.ndim == 1:
		# mono to stereo
		X = np.asarray([X, X])

	print('STFT of wave source ...', end = ' ', flush = True)
	X_spec = spec_utils.wave_to_spectrogram(X, args.hop_length, args.n_fft)
	print('done', flush = True)

	sp = Separator(args.model, args.device, args.batchsize, args.cropsize)

	if args.tta:
		y_spec, v_spec = sp.separate_tta(X_spec)
	else:
		y_spec, v_spec = sp.separate(X_spec)

	print('Inverse STFT of instruments ...', end = ' ', flush = True)
	wave = spec_utils.spectrogram_to_wave(y_spec, hop_length = args.hop_length)
	print('done', flush = True)
	sf.write(out_wav_nonvocal, wave.T, sr)

	if out_wav_vocal:
		print('Inverse STFT of vocals ...', end = ' ', flush = True)
		wave = spec_utils.spectrogram_to_wave(v_spec, hop_length = args.hop_length)
		print('done', flush = True)
		sf.write(out_wav_vocal, wave.T, sr)

def ffm_wav2m4a(input_fn, output_fn, br = '128k'):
	input_fn, output_fn = [fn.replace('"', '\\"') for fn in [input_fn, output_fn]]
	subprocess.run(['ffmpeg', '-y', '-i', input_fn, '-c:a', 'aac', '-b:a', br, output_fn])

def ffm_video2wav(input_fn, output_fn):
	# The built-in DNN model is trained on 44100 sampling rate, it can still run but does not work on other sampling rates
	input_fn, output_fn = [fn.replace('"', '\\"') for fn in [input_fn, output_fn]]
	subprocess.run(['ffmpeg', '-y', '-i', input_fn, '-f', 'wav', '-ar', '44100', output_fn])

@app.route('/split_vocal', methods=['POST'])
def split_vocal():
	global M_ASR, UPLOAD_FOLDER
	fullname = os.path.join(app.config['UPLOAD_FOLDER'], 'split_vocal.m4a')
	outprefix = os.path.join(app.config['UPLOAD_FOLDER'], 'split_vocal')
	request.files['file'].save(fullname)
	ffm_video2wav(fullname, fullname+'.wav')
	split_vocal_by_dnn(fullname+'.wav', fullname+'.nonvocal.wav', fullname+'.vocal.wav')
	ffm_wav2m4a(fullname+'.nonvocal.wav', outprefix+'.nonvocal.m4a')
	ffm_wav2m4a(fullname+'.vocal.wav', outprefix+'.vocal.m4a')
	with tarfile.open(outprefix+'.tar.gz', "w:gz") as tar:
		tar.add(outprefix+'.nonvocal.m4a', arcname='nonvocal.m4a')
		tar.add(outprefix+'.vocal.m4a', arcname='vocal.m4a')
	return send_file(outprefix+'.tar.gz', as_attachment=True)


if __name__ == '__main__':
	parser = argparse.ArgumentParser(usage='$0 [options]', description='launch the smart home server',
			formatter_class=argparse.ArgumentDefaultsHelpFormatter)
	parser.add_argument('--ip', '-i', default='0.0.0.0', help='select the interface to listen on')
	parser.add_argument('--port', '-p', type=int, default=8882, help='server port number')
	parser.add_argument('--asr-model', '-am', default='medium', help='ASR model to load')
	parser.add_argument('--vocal-splitter', '-vs', help='whether to load vocal splitter model', action='store_true')
	parser.add_argument('--gpu', '-g', type = int, help = 'CUDA device ID for GPU inference, set to -1 to force to use CPU (default will try to use GPU if available)', default = None)
	parser.add_argument('--pretrained_model', '-P', type = str, default = 'models/baseline.pth')
	parser.add_argument('--sr', '-r', type = int, default = 44100)
	parser.add_argument('--n_fft', '-f', type = int, default = 2048)
	parser.add_argument('--hop_length', '-H', type = int, default = 1024)
	parser.add_argument('--batchsize', '-B', type = int, default = 4)
	parser.add_argument('--cropsize', '-c', type = int, default = 256)
	parser.add_argument('--postprocess', '-pp', action = 'store_true')
	parser.add_argument('--tta', '-t', action = 'store_true')

	args=parser.parse_args()
	globals().update(vars(args))

	print('Loading OpenAI-Whisper model ...', end = ' ', flush = True)
	M_ASR = whisper.load_model(asr_model)
	print('done', flush = True)

	if vocal_splitter:
		# Determine the GPU device and load the DNN model
		print('Loading vocal-splitter model ...', end = ' ', flush = True)
		device = torch.device('cpu')
		M_VOS = nets.CascadedNet(args.n_fft, args.hop_length, 32, 128, True)
		M_VOS.load_state_dict(torch.load(args.pretrained_model, map_location = device))
		if (args.gpu is None or args.gpu >= 0) and torch.cuda.is_available():
			device = torch.device(f'cuda:{0 if args.gpu is None else args.gpu}')
			M_VOS.to(device)
		args.model = M_VOS
		args.device = device
		print('done', flush = True)

	app.run(host='0.0.0.0', port=port)