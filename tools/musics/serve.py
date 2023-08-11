#!/usr/bin/env python3

import os, sys, vlc, subprocess, random, time
from flask import Flask
app = Flask(__name__)

inst = vlc.Instance()
player = None
playlist = None

def create(fn):
	global inst, player, playlist
	filelist = [L.strip() for L in open(fn) if not L.startswith('#')]
	random.seed(time.time())
	random.shuffle(filelist)
	playlist = inst.media_list_new(filelist)
	player = inst.media_list_player_new()
	player.set_media_list(playlist)

@app.route('/play/<path:name>')
def play(name=''):
	global player, playlist
	try:
		stop()
		if not name.startswith('/'):
			name = os.getenv('HOME')+'/'+name
		if player == None:
			create(name)
		player.set_playback_mode(vlc.PlaybackMode.loop)
		player.play()
	except Exception as e:
		return str(e)
	return 'OK'

@app.route('/pause')
def pause():
	global player
	try:
		if player.is_playing():
			player.pause()
	except Exception as e:
		return str(e)
	return 'OK'

@app.route('/resume')
def resume():
	global player
	try:
		if not player.is_playing():
			player.pause()
	except Exception as e:
		return str(e)
	return 'OK'

@app.route('/stop')
def stop():
	global player
	ret = 'OK'
	try:
		player.stop()
		player.release()
	except Exception as e:
		ret = str(e)
	player = None
	return ret

if __name__ == '__main__':
	app.run(host='0.0.0.0', port=8883)
