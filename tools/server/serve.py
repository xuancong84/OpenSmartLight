#!/usr/bin/env python3

import traceback
import os, sys, vlc, subprocess, random, time, threading
from urllib.parse import unquote
from flask import Flask
app = Flask(__name__)

video_file_exts = ['.mp4', '.mkv', '.avi', '.mpg', '.mpeg']

inst = vlc.Instance()
event = vlc.EventType()
player = None
playlist = None
mplayer = None
filelist = []
isFirst = True
isJustAfterBoot = float(open('/proc/uptime').read().split()[0])<120

def RUN(cmd, shell=True, timeout=3, **kwargs):
	ret = subprocess.check_output(cmd, shell=shell, **kwargs)
	return ret if type(ret)==str else ret.decode()

def create(fn):
	global inst, player, playlist, filelist
	stop()
	filelist = [L.strip() for L in open(fn) if not L.startswith('#')]
	random.seed(time.time())
	random.shuffle(filelist)
	playlist = inst.media_list_new(filelist)
	if player == None:
		player = inst.media_list_player_new()
	player.set_media_list(playlist)
	videos = [fn for fn in filelist for ext in video_file_exts if fn.lower().endswith(ext)]
	return videos

def add_song(fn):
	global player, playlist, mplayer, filelist
	filelist += [fn]
	if playlist==None:
		playlist = inst.media_list_new([])
	playlist.add_media(fn)
	if player==None:
		player = inst.media_list_player_new()
		player.set_media_list(playlist)
	player.play_item_at_index(playlist.count()-1)
	videos = [fn for fn in filelist for ext in video_file_exts if fn.lower().endswith(ext)]
	return videos

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

def keep_fullscreen(_):
	global isFirst
	wait_tm = (3 if isJustAfterBoot else 2) if isFirst else 1
	threading.Timer(wait_tm, lambda:mplayer.set_fullscreen(False)).start()
	threading.Timer(wait_tm+.2, lambda:mplayer.set_fullscreen(True)).start()
	isFirst = False

@app.route('/play/<path:name>')
def play(name=''):
	global player, playlist, mplayer
	try:
		if not name.startswith('/'):
			name = os.getenv('HOME')+'/'+name
		isvideo = create(name) if name.lower().endswith('.m3u') else add_song(name)
		mplayer = player.get_media_player()
		if isvideo:
			disconnectble('marshall')
			set_audio_device(['hdmi','audio.stereo'], 1)
			mplayer.event_manager().event_attach(event.MediaPlayerOpening, keep_fullscreen)
		else:
			connectble('marshall')
			set_audio_device('bluez', 2)
			mplayer.event_manager().event_detach(event.MediaPlayerOpening)
		player.set_playback_mode(vlc.PlaybackMode.loop)
		player.play()
		threading.Timer(1, lambda:mplayer.audio_set_volume(100)).start()
	except Exception as e:
		traceback.print_exc()
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
		return RUN("amixer get Master | awk -F'[][]' '/Left:/ { print $2 }'")
	except Exception as e:
		return str(e)

@app.route('/vlcvolume/<cmd>')
def vlcvolume(cmd=None):
	global mplayer
	try:
		if cmd=='up':
			mplayer.audio_set_volume(mplayer.audio_get_volume()+10)
		elif cmd=='down':
			mplayer.audio_set_volume(mplayer.audio_get_volume()-10)
		elif cmd.isdigit():
			mplayer.audio_set_volume(int(cmd))
		return str(mplayer.audio_get_volume())
	except Exception as e:
		traceback.print_exc()
		return str(e)


# For Ecovacs
@app.route('/ecovacs', defaults={'name': '', 'cmd':''})
@app.route('/ecovacs/<name>/<cmd>')
def ecovacs(name='', cmd=''):
	return RUN(f'./ecovacs-cmd.sh {name} {cmd}')


# For LG TV
@app.route('/lgtv/<name>/<cmd>')
def lgtv(name='', cmd=''):
	return RUN(f'./miniconda3/bin/lgtv --name {name} {cmd}')

@app.route('/lgtvVolume/<name>/<vol>')
def lgtvVolume(name='', vol=''):
	try:
		value = int(vol)
		if not vol[0].isdigit():
			ret = RUN(f'./miniconda3/bin/lgtv --name {name} audioVolume')
			L = ret[ret.find('"volume":'):]
			value += int(L[L.find(' '):L.find(',')])
		return RUN(f'./miniconda3/bin/lgtv --name {name} setVolume {value}')
	except Exception as e:
		return str(e)

list_audio = lambda: RUN('pactl list sinks short')

# For audio
def set_audio_device(devs, wait=10):
	for dev in (devs if type(devs)==list else [devs]):
		for i in range(wait+1):
			out = [L.split() for L in list_audio().splitlines()]
			res = [its[0] for its in out if dev in its[1]]
			if res:
				return os.system(f'pactl set-default-sink {res[0]}')==0
			time.sleep(1)
	return (os.system(f'pactl set-default-sink {out[0][0]}')==0) if out else False


if __name__ == '__main__':
	app.run(host='0.0.0.0', port=8883)

