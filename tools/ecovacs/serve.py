#!/usr/bin/env python3

import subprocess
from flask import Flask
app = Flask(__name__)

@app.route('/ecovacs', defaults={'name': '', 'cmd':''})
@app.route('/ecovacs/<name>/<cmd>')
def ecovacs(name='', cmd=''):
	return subprocess.check_output(f'./run.sh {name} {cmd}', shell=True)

if __name__ == '__main__':
	app.run(host='0.0.0.0', port=8883)

