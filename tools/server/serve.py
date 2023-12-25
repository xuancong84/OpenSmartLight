#!/usr/bin/env python3

import os, sys, vlc, subprocess, random, time
from urllib.parse import unquote
from flask import Flask
app = Flask(__name__)


inst = vlc.Instance()
player = None
playlist = None
filelist = []

def create(fn):
	global inst, player, playlist, filelist
	filelist = [L.strip() for L in open(fn) if not L.startswith('#')]
	random.seed(time.time())
	random.shuffle(filelist)
	playlist = inst.media_list_new(filelist)
	player = inst.media_list_player_new()
	player.set_media_list(playlist)

def findSong(name):
	global filelist
	found = None
	for ii,it in enumerate(filelist):
		mrl = unquote(it)
		bn = os.path.basename(mrl)
		if name==bn.split('.')[0]:
			found = ii
			break
	if found==None:
		for ii,it in enumerate(filelist):
			mrl = unquote(it)
			bn = os.path.basename(mrl)
			if name in bn:
				found = ii
				break
	return found

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

@app.route('/next')
def play_next():
	global player
	try:
		if player.is_playing():
			player.next()
	except Exception as e:
		return str(e)
	return 'OK'

@app.route('/previous')
def play_previous():
	global player
	try:
		if player.is_playing():
			player.previous()
	except Exception as e:
		return str(e)
	return 'OK'

@app.route('/playFrom/<name>')
def playFrom(name=''):
	global player
	try:
		if name and player.is_playing():
			ii = findSong(name)
			assert ii!=None
			player.play_item_at_index(ii)
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

@app.route('/connectble/<device>')
def connectble(device=None):
	if device=='marshall':
		ret = os.system('bluetoothctl connect 54:b7:e5:9e:f4:14' if sys.platform=='linux' else 'blueutil --connect 54:b7:e5:9e:f4:14')
	return str(ret)

@app.route('/disconnectble/<device>')
def disconnectble(device=None):
	if device=='marshall':
		ret = os.system('bluetoothctl disconnect 54:b7:e5:9e:f4:14' if sys.platform=='linux' else 'blueutil --disconnect 54:b7:e5:9e:f4:14')
	return str(ret)

@app.route('/volume/<cmd>')
def volume(cmd=None):
	try:
		if cmd=='up':
			ret = os.system('amixer sset Master 10%+' if sys.platform=='linux' else 'osascript -e "set volume output volume (output volume of (get volume settings) + 10)"')
		elif cmd=='down':
			ret = os.system('amixer sset Master 10%-' if sys.platform=='linux' else 'osascript -e "set volume output volume (output volume of (get volume settings) - 10)"')
		elif cmd.isdigit():
			ret = os.system('amixer sset Master 50%' if sys.platform=='linux' else f'osascript -e "set volume output volume {int(cmd)}"')
		return str(ret)
	except Exception as e:
		return str(e)


# For Ecovacs
@app.route('/ecovacs', defaults={'name': '', 'cmd':''})
@app.route('/ecovacs/<name>/<cmd>')
def ecovacs(name='', cmd=''):
	return subprocess.check_output(f'./ecovacs-cmd.sh {name} {cmd}', shell=True)


if __name__ == '__main__':
	app.run(host='0.0.0.0', port=8883)
