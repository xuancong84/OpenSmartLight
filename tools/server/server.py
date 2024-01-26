#!/usr/bin/env python3

import traceback, argparse, math, requests, string, json
import os, sys, subprocess, random, time, threading
import pinyin, vlc
from urllib.parse import unquote
from flask import Flask, request
from unidecode import unidecode
from pydub import AudioSegment

from device_config import *

app = Flask(__name__)
video_file_exts = ['.mp4', '.mkv', '.avi', '.mpg', '.mpeg']
to_pinyin = lambda t: pinyin.get(t, format='numerical')
get_alpha = lambda t: ''.join([c for c in t if c in string.ascii_letters])
get_alnum = lambda t: ''.join([c for c in t if c in string.ascii_letters+string.digits])
get_volume = lambda: RUN("amixer get Master | awk -F'[][]' '/Left:/ { print $2 }'").rstrip('%\n')

inst = vlc.Instance()
event = vlc.EventType()
asr_finished = False
asr_model = None
asr_input = DEFAULT_RECORDING_FILE
player = None
playlist = None
mplayer = None
filelist = []
P_ktv = None
isFirst = True
subtitle = True
CANCEL_FLAG = False
isJustAfterBoot = True if sys.platform=='darwin' else float(open('/proc/uptime').read().split()[0])<120
random.seed(time.time())

def Try(fn, default=None):
	try:
		return fn()
	except Exception as e:
		return str(e) if default=='ERROR_MSG' else default

def Eval(cmd, default=None):
	try:
		return eval(cmd, globals(), globals())
	except:
		return default

def RUN(cmd, shell=True, timeout=3, **kwargs):
	ret = subprocess.check_output(cmd, shell=shell, **kwargs)
	return ret if type(ret)==str else ret.decode()

# Abort transcription thread
def cancel_transcription():
    global CANCEL_FLAG
    CANCEL_FLAG = True

# Function to check if cancellation is requested
def cancel_requested():
	global CANCEL_FLAG
	if CANCEL_FLAG:
		CANCEL_FLAG = False
		return True
	return False

def isVideoFile(fn):
	for ext in video_file_exts:
		if fn.lower().endswith(ext):
			return True
	return False

def create(fn):
	global inst, player, playlist, filelist
	stop()
	filelist = [L.strip() for L in open(fn) if L.strip() and not L.strip().startswith('#')]
	random.shuffle(filelist)
	playlist = inst.media_list_new(filelist)
	if player == None:
		player = inst.media_list_player_new()
	player.set_media_list(playlist)
	videos = [fn for fn in filelist if isVideoFile(fn)]
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
	videos = [fn for fn in filelist if isVideoFile(fn)]
	return videos

def findSong(name):
	global filelist
	name = name.lower().strip()
	name_list = [os.path.basename(unquote(fn)).split('.')[0].lower().strip() for fn in filelist]

	# 1. exact full match
	if name in name_list:
		return name_list.index(name)

	# 2. exact substring match
	for ii,it in enumerate(name_list):
		if name in it:
			return ii

	# 3. pinyin full match
	pinyin_list = [get_alnum(to_pinyin(n)) for n in name_list]
	pinyin_name = get_alnum(to_pinyin(name))
	if pinyin_name in pinyin_list:
		return pinyin_list.index(pinyin_name)

	# 4. pinyin substring match
	for ii,it in enumerate(pinyin_list):
		if pinyin_name in it:
			return ii
	
	# 5. transliteration full match
	translit_list = [get_alpha(unidecode(n)) for n in name_list]
	translit_name = get_alpha(unidecode(name))
	if translit_name in translit_list:
		return translit_list.index(translit_name)

	# 6. transliteration substring match
	for ii,it in enumerate(pinyin_list):
		if translit_name in it:
			return ii

	return None

@app.route('/subtitle/<show>')
def show_subtitle(show=None):
	global subtitle
	subtitle = subtitle if show==None else eval(show)
	mplayer.video_set_spu(2 if (subtitle and mplayer.video_get_spu_count()>=2) else -1)
	print(f'Set subtitle = {subtitle}', file=sys.stderr)
	return 'OK'

def ensure_fullscreen():
	while True:
		try:
			txt = RUN('DISPLAY=:0.0 xprop -name "VLC media player"')
		except:
			time.sleep(0.5)
			continue
		if '_NET_WM_STATE_FULLSCREEN' in txt:
			return
		mplayer.set_fullscreen(False)
		time.sleep(0.2)
		mplayer.set_fullscreen(True)

def keep_fullscreen(_):
	global isFirst
	wait_tm = (3 if isJustAfterBoot else 2) if isFirst else 1
	threading.Timer(wait_tm, lambda:mplayer.set_fullscreen(False)).start()
	threading.Timer(wait_tm+.2, lambda:mplayer.set_fullscreen(True)).start()
	threading.Timer(wait_tm+.8, lambda:ensure_fullscreen()).start()
	threading.Timer(wait_tm+2, show_subtitle).start()
	isFirst = False

@app.route('/play/<path:name>')
def play(name=''):
	global player, playlist, mplayer
	try:
		name = os.path.expanduser(name if name.startswith('~') else ('~/'+name))
		isvideo = create(name) if name.lower().endswith('.m3u') else add_song(name)
		mplayer = player.get_media_player()
		if isvideo:
			set_audio_device(MP4_SPEAKER)
			mplayer.event_manager().event_attach(event.MediaPlayerOpening, keep_fullscreen)
		else:
			set_audio_device(MP3_SPEAKER)
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
			player.set_pause(True)
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

remote_addr = None
def _normalize_vol(song):
	global player
	if song.startswith('~'):
		fn = os.path.expanduser(song)
		sid = -1
	elif song:
		sid = findSong(song)
	else:
		mrl = mplayer.get_media().get_mrl()
		sid = filelist.index(mrl) if mrl in filelist else filelist.index(unquote(mrl).replace('file://', ''))
		player.stop()
	fn = fn if sid<0 else unquote(filelist[sid]).replace('file://', '')
	assert os.path.isfile(fn)
	requests.get(f'http://{remote_addr}/asr_write?aa558155aa')
	audio = AudioSegment.from_file(fn)
	if isVideoFile(fn):
		if not os.path.exists(fn+'.orig.m4a'):
			audio.export(fn+'.orig.m4a', format='ipod')
		audio += 10*math.log10((4096/audio.rms)**2)
		audio.export(fn+'.m4a', format='ipod')
		os.system(f'ffmpeg -y -i {fn} -i {fn}.m4a -c copy -map 0 -map -0:a -map 1:a {fn}.tmp.mp4')
		os.rename(f'{fn}.tmp.mp4', fn)
		os.remove(fn+'.m4a')
	else:
		if not os.path.exists(fn+'.orig'):
			os.rename(fn, fn+'.orig')
		audio += 10*math.log10((4096/audio.rms)**2)
		audio.export(fn, format=('mp3' if fn.lower().endswith('.mp3') else 'ipod'))
	if sid>=0:
		player.play_item_at_index(sid)

@app.route('/normalize_vol/')
@app.route('/normalize_vol/<path:song>')
def normalize_vol(song=''):
	global remote_addr
	remote_addr = request.remote_addr
	threading.Timer(0, lambda: _normalize_vol(song)).start()
	return 'OK'

@app.route('/playFrom/<name>')
def playFrom(name=''):
	global player
	try:
		if name:
			ii = findSong(name)
			assert ii!=None
			player.play_item_at_index(ii)
	except Exception as e:
		return str(e)
	return 'OK'

@app.route('/play_spoken_song')
def play_spoken_song():
	global player, playlist, mplayer, asr_model, asr_finished
	try:
		# preserve environment
		cur_sta = player.is_playing()
		if cur_sta:
			player.set_pause(True)
		cur_vol = get_volume()

		# record speech
		set_volume(70)
		play_audio('./voice/speak_title.m4a', True)
		record_audio()
		time.sleep(0)

		asr_finished = CANCEL_FLAG = False
		if ASR_CLOUD:
			threading.Thread(target=ASR_cloud_thread).start()
		if asr_model!=None:
			threading.Thread(target=ASR_server_thread).start()

		# play_audio('./voice/wait_for_asr.m4a', True)

		# restore environment
		set_volume(cur_vol)
		if cur_sta:
			player.set_pause(False)
	except Exception as e:
		traceback.print_exc()
		return str(e)
	return 'OK'

@app.route('/resume')
def resume():
	global player
	try:
		if not player.is_playing():
			player.set_pause(False)
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
def connectble(dev_mac):
	ret = os.system(f'bluetoothctl connect {dev_mac}' if sys.platform=='linux' else f'blueutil --connect {dev_mac}')
	return str(ret)

@app.route('/disconnectble/<device>')
def disconnectble(dev_mac):
	ret = os.system(f'bluetoothctl disconnect {dev_mac}' if sys.platform=='linux' else f'blueutil --disconnect {dev_mac}')
	return str(ret)

@app.route('/volume/<cmd>')
def set_volume(cmd=None):
	try:
		if cmd=='up':
			ret = os.system('amixer sset Master 10%+' if sys.platform=='linux' else 'osascript -e "set volume output volume (output volume of (get volume settings) + 10)"')
		elif cmd=='down':
			ret = os.system('amixer sset Master 10%-' if sys.platform=='linux' else 'osascript -e "set volume output volume (output volume of (get volume settings) - 10)"')
		elif cmd.isdigit() or type(cmd)==int:
			ret = os.system(f'amixer sset Master {int(cmd)}%' if sys.platform=='linux' else f'osascript -e "set volume output volume {int(cmd)}"')
		return get_volume()
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

list_sinks = lambda: RUN('pactl list sinks short')
list_sources = lambda: RUN('pactl list sources short')

# For audio
@app.route('/speaker/<cmd>/<name>')
def speaker(cmd, name):
	if name.endswith('_SPEAKER'):
		name = Eval(name, name)
	return str(set_audio_device(name) if cmd=='on' else unset_audio_device(name))

def set_audio_device(devs, wait=3):
	for dev in (devs if type(devs)==list else [devs]):
		for i in range(wait+1):
			patn = dev
			if dev.count(':')==5:
				connectble(dev)
				patn = dev.replace(':', '_')
			out = [L.split() for L in list_sinks().splitlines()]
			res = [its[0] for its in out if patn in its[1]]
			if res:
				return os.system(f'pactl set-default-sink {res[0]}')==0
			time.sleep(1)
	return (os.system(f'pactl set-default-sink {out[0][0]}')==0) if out else False

def unset_audio_device(devs):
	for dev in (devs if type(devs)==list else [devs]):
		if dev.count(':')==5:
			disconnectble(dev)
	return True

def get_recorder(devs, wait=3):
	for dev in (devs if type(devs)==list else [devs]):
		for i in range(wait+1):
			patn = dev
			if dev.count(':')==5:
				connectble(dev)
				patn = dev.replace(':', '_')
			out = [L.split() for L in list_sources().splitlines()]
			res = sorted([its for its in out if patn in its[1]], key=lambda t: int(t[0]))
			if res:
				os.system(f'pactl set-default-source {res[-1][0]}')
				return res[-1][1]
			time.sleep(1)
	res = sorted(out, key=lambda t: int(t[0]))
	if res:
		os.system(f'pactl set-default-source {res[-1][0]}')
		return res[-1][1]
	return '0'

def play_audio(fn, block=False):
	p = vlc.MediaPlayer(fn)
	p.play()
	if block:
		while not p.is_playing():pass
		while p.is_playing():pass

def record_audio(tm_sec=5, file_path=DEFAULT_RECORDING_FILE):
	os.system(f'ffmpeg -y -f pulse -i {get_recorder(MIC_RECORDER)} -ac 1 -t {tm_sec} {file_path}')


# For ASR server
def handle_ASR(obj):
	global asr_finished
	if (not obj) or asr_finished: return
	print(f'ASR result: {obj}', file=sys.stderr)
	if not obj['text']:
		play_audio('voice/asr_fail.m4a')
	elif playFrom(obj['text'])=='OK':
		asr_finished = True
		play_audio('voice/asr_found.m4a')
	else:
		play_audio('voice/asr_not_found.m4a')

def ASR_server_thread():
	try:
		obj = asr_model.transcribe(os.path.expanduser(asr_input), cancel_func=cancel_requested)
		handle_ASR(obj)
	except Exception as e:
		traceback.print_exc()
		play_audio('voice/asr_error.m4a')

def ASR_cloud_thread():
	try:
		with open(os.path.expanduser(asr_input), 'rb') as f:
			r = requests.post(ASR_CLOUD, files={'file': f}, timeout=4)
		if r.status_code==200:
			cancel_transcription()
		handle_ASR(json.loads(r.text))
	except Exception as e:
		traceback.print_exc()
		play_audio('voice/asr_error.m4a')


# For pikaraoke
@app.route('/KTV/<cmd>')
def KTV(cmd):
	try:
		if cmd=='on':
			stop()
			set_audio_device(KTV_SPEAKER)
			P_ktv = subprocess.Popen(['~/projects/pikaraoke/run-no-vocal.sh'], shell=True)
		elif cmd=='off':
			P_ktv.kill()
			unset_audio_device(KTV_SPEAKER)
		return 'OK'
	except Exception as e:
		return str(e)


if __name__ == '__main__':
	parser = argparse.ArgumentParser(usage='$0 [options]', description='launch the smart home server',
			formatter_class=argparse.ArgumentDefaultsHelpFormatter)
	parser.add_argument('--port', '-p', type=int, default=8883, help='server port number')
	parser.add_argument('--asr', '-a', help='host ASR server', action='store_true')
	parser.add_argument('--asr-model', '-am', default='base', help='ASR model to load')
	parser.add_argument('--hide-subtitle', '-nosub', help='ASR model to load', action='store_true')
	opt=parser.parse_args()
	globals().update(vars(opt))

	subtitle = not hide_subtitle

	if asr:
		import whisper
		asr_model = whisper.load_model(asr_model)
		print('Offline ASR model loaded successfully ...', file=sys.stderr)
	else:
		asr_model = None

	app.run(host='0.0.0.0', port=port)

