#!/usr/bin/env python3

import os, sys, whisper, traceback, argparse
from flask import Flask, request, jsonify

UPLOAD_FOLDER = '/dev/shm/'
ALLOWED_EXTENSIONS = {'m4a', 'mp3', 'wav'}

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 1024*1024
M = None

def allowed_file(filename):
	return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@app.route('/run_asr/<model>', methods=['POST'])
def upload_file(model):
	global M, UPLOAD_FOLDER, FILENAME
	# check if the post request has the file part
	if 'file' not in request.files:
		return ''
	file = request.files['file']
	# If the user does not select a file, the browser submits an
	# empty file without a filename.
	if file and allowed_file(file.filename):
		file.save(os.path.join(app.config['UPLOAD_FOLDER'], file.filename))
		try:
			obj = M.transcribe(UPLOAD_FOLDER+file.filename)
			print(obj, file=sys.stderr)
			return jsonify(obj), 200
		except Exception as e:
			traceback.print_exc()
			return str(e), 500


if __name__ == '__main__':
	parser = argparse.ArgumentParser(usage='$0 [options]', description='launch the smart home server',
			formatter_class=argparse.ArgumentDefaultsHelpFormatter)
	parser.add_argument('--ip', '-i', default='0.0.0.0', help='select the interface to listen on')
	parser.add_argument('--port', '-p', type=int, default=8883, help='server port number')
	parser.add_argument('--asr-model', '-am', default='medium', help='ASR model to load')
	opt=parser.parse_args()
	globals().update(vars(opt))

	M = whisper.load_model(asr_model)

	app.run(host='0.0.0.0', port=port)