#!/usr/bin/env python3

import traceback, argparse, math, requests, string, json
import os, sys, subprocess, random, time, threading
import pinyin, vlc, pykakasi
from urllib.parse import unquote
from flask import Flask, request
from unidecode import unidecode
from pydub import AudioSegment
from gtts import gTTS
from lingua import Language, LanguageDetectorBuilder

from lib.an2cn import num2zh
from device_config import *

app = Flask(__name__)
KKS = pykakasi.kakasi()
video_file_exts = ['.mp4', '.mkv', '.avi', '.mpg', '.mpeg']
to_pinyin = lambda t: pinyin.get(t, format='numerical')
to_romaji = lambda t: ' '.join([its['hepburn'] for its in KKS.convert(t)])
get_alpha = lambda t: ''.join([c for c in t if c in string.ascii_letters])
get_alnum = lambda t: ''.join([c for c in t if c in string.ascii_letters+string.digits])
get_volume = lambda: RUN("amixer get Master | awk -F'[][]' '/Left:/ { print $2 }'").rstrip('%\n')
mrl2path = lambda mrl: unquote(mrl).replace('file://', '') if mrl.startswith('file://') else mrl
filepath2songtitle = lambda fn: os.path.basename(unquote(fn)).split('.')[0].lower().strip()
lang2id = {Language.ENGLISH: 'en', Language.CHINESE: 'zh', Language.JAPANESE: 'ja', Language.KOREAN: 'ko'}

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
isVideo = None
subtitle = True
CANCEL_FLAG = False
isJustAfterBoot = True if sys.platform=='darwin' else float(open('/proc/uptime').read().split()[0])<120
random.seed(time.time())
ASR_server_running = ASR_cloud_running = False
lang_detector = LanguageDetectorBuilder.from_languages(*lang2id.keys()).build()

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

load_config = lambda: Try(json.load(open('.config.json')), {})
save_config = lambda obj: exec("with open('.config.json','w') as fp: json.dump(obj, fp, indent=1)")

# Detect language, invoke Google-translate TTS and play the speech audio
def play_TTS(txt):
	txts = txt if type(txt)==list else [txt]
	for seg in txts:
		lang_id = lang2id[lang_detector.detect_language_of(seg)]
		tts = gTTS(seg, lang=lang_id)
		tts.save(DEFAULT_SPEECH_FILE)
		play_audio(DEFAULT_SPEECH_FILE, True)

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

def str_search(name, name_list, mode=3):
	# 1. exact full match
	if name in name_list:
		return name_list.index(name)

	# 2. exact substring match
	res = [[ii, len(it)-len(name)] for ii,it in enumerate(name_list) if name in it]
	return sorted(res, key=lambda t:t[1])[0][0] if res else -1

def findSong(name, lang=None):
	global filelist
	name = name.lower().strip()
	name_list = [filepath2songtitle(fn) for fn in filelist]

	# 1. exact full match of original form
	if name in name_list:
		return name_list.index(name)

	# 2. match by pinyin if Chinese or unknown
	if lang in [None, 'zh']:
		# 3. pinyin full match
		pinyin_list = [get_alnum(to_pinyin(num2zh(n))) for n in name_list]
		pinyin_name = get_alnum(to_pinyin(num2zh(name)))
		res = str_search(pinyin_name, pinyin_list)
		if pinyin_name and res>=0:
			return res

	# 3. match by romaji if Japanese or unknown
	if lang in [None, 'ja']:
		# 5. romaji full match
		romaji_list = [get_alpha(to_romaji(n)) for n in name_list]
		romaji_name = get_alpha(to_romaji(name))
		res = str_search(romaji_name, romaji_list)
		if romaji_name and res>=0:
			return res

	# 4. substring match
	res = str_search(name, name_list)
	if res>=0:
		return res
	
	# 5. match by transliteration
	translit_list = [get_alpha(unidecode(n)) for n in name_list]
	translit_name = get_alpha(unidecode(name))
	res = str_search(translit_name, translit_list)
	if translit_name and res>=0:
		return res

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

def on_media_opening(_):
	global isFirst, isVideo
	print(f'Starting to play: {mrl2path(mplayer.get_media().get_mrl())}', file=sys.stderr)
	if isVideo:
		wait_tm = (3 if isJustAfterBoot else 2) if isFirst else 1
		threading.Timer(wait_tm, lambda:mplayer.set_fullscreen(False)).start()
		threading.Timer(wait_tm+.2, lambda:mplayer.set_fullscreen(True)).start()
		threading.Timer(wait_tm+.8, lambda:ensure_fullscreen()).start()
		threading.Timer(wait_tm+2, show_subtitle).start()
		isFirst = False

@app.route('/play/<path:name>')
def play(name=''):
	global player, playlist, mplayer, isVideo
	try:
		name = os.path.expanduser(name if name.startswith('~') else ('~/'+name))
		isVideo = create(name) if name.lower().endswith('.m3u') else add_song(name)
		mplayer = player.get_media_player()
		mplayer.event_manager().event_attach(event.MediaPlayerOpening, on_media_opening)
		if isVideo:
			set_audio_device(MP4_SPEAKER)
		else:
			set_audio_device(MP3_SPEAKER)
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

def get_bak_fn(fn):
	dirname = os.path.dirname(fn)
	Try(os.makedirs(dirname+'/orig'))
	return f'{dirname}/orig/{os.path.basename(fn)}'

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
		sid = filelist.index(mrl) if mrl in filelist else filelist.index(mrl2path(mrl))
		player.stop()
	fn = fn if sid<0 else mrl2path(filelist[sid])
	assert os.path.isfile(fn)
	play_audio('voice/processing.m4a')
	audio = AudioSegment.from_file(fn)
	if isVideoFile(fn):
		if not os.path.exists(get_bak_fn(fn+'.m4a')):
			audio.export(get_bak_fn(fn+'.m4a'), format='ipod')
		audio += 10*math.log10((4096/audio.rms)**2)
		audio.export(fn+'.m4a', format='ipod')
		os.system(f'ffmpeg -y -i {fn} -i {fn}.m4a -c copy -map 0 -map -0:a -map 1:a {fn}.tmp.mp4')
		os.system('sync')
		os.rename(f'{fn}.tmp.mp4', fn)
		os.system('sync')
		os.remove(fn+'.m4a')
	else:
		if not os.path.exists(get_bak_fn(fn+'.m4a')):
			os.rename(fn, get_bak_fn(fn+'.m4a'))
		audio += 10*math.log10((4096/audio.rms)**2)
		audio.export(fn, format=('mp3' if fn.lower().endswith('.mp3') else 'ipod'))
	if sid>=0:
		player.play_item_at_index(sid)

@app.route('/normalize_vol')
@app.route('/normalize_vol/<path:song>')
def normalize_vol(song=''):
	global remote_addr
	remote_addr = request.remote_addr
	threading.Timer(0, lambda: _normalize_vol(song)).start()
	return 'OK'

@app.route('/playFrom/<name>')
def playFrom(name='', lang=None):
	global player
	try:
		ii = findSong(name, lang=lang)
		assert ii!=None
		player.play_item_at_index(ii)
	except Exception as e:
		return str(e)
	return 'OK'

def _play_spoken_song(search_list=''):
	global player, playlist, mplayer, asr_model, asr_finished
	if player == None:
		play_audio('voice/playlist_empty.m4a')
		return 'NA'

	# preserve environment
	cur_sta = player.is_playing()
	if cur_sta:
		player.set_pause(True)
	cur_vol = get_volume()

	# record speech
	set_volume(VOICE_VOL)
	play_audio('voice/speak_title.m4a', True)
	record_audio()
	time.sleep(0)

	asr_finished = CANCEL_FLAG = False
	reply_wait = True
	if ASR_CLOUD and not ASR_cloud_running:
		threading.Thread(target=ASR_cloud_thread).start()
		reply_wait = False
	if asr_model!=None and not ASR_server_running:
		threading.Thread(target=ASR_server_thread).start()

	if reply_wait:
		play_audio('voice/wait_for_asr.m4a', True)

	# restore environment
	set_volume(cur_vol)
	if cur_sta:
		player.set_pause(False)

@app.route('/play_spoken_song')
@app.route('/play_spoken_song/<path:search_list>')
def play_spoken_song(search_list=''):
	threading.Thread(target=_play_spoken_song, args=(search_list,)).start()
	return 'OK'

@app.route('/play_drama')
@app.route('/play_drama/<path:name>')
def play_drama(name=None):
	if name==None:
		load_config()
	return 'OK'

def _report_song_title():
	songtitle = filepath2songtitle(mrl2path(mplayer.get_media().get_mrl()))
	cur_sta = False
	if mplayer.is_playing():
		mplayer.set_pause(True)
		cur_sta = True
	cur_vol = get_volume()
	set_volume(VOICE_VOL)

	play_audio('voice/cur_song_title.mp3', True)
	play_TTS(songtitle)

	set_volume(cur_vol)
	if cur_sta:
		mplayer.set_pause(False)

@app.route('/report_song_title')
def report_song_title():
	threading.Thread(target=_report_song_title).start()
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
		if type(cmd) in [int, float] or cmd.isdigit():
			ret = os.system(f'amixer sset Master {int(cmd)}%' if sys.platform=='linux' else f'osascript -e "set volume output volume {int(cmd)}"')
		elif cmd=='up':
			ret = os.system('amixer sset Master 10%+' if sys.platform=='linux' else 'osascript -e "set volume output volume (output volume of (get volume settings) + 10)"')
		elif cmd=='down':
			ret = os.system('amixer sset Master 10%-' if sys.platform=='linux' else 'osascript -e "set volume output volume (output volume of (get volume settings) - 10)"')
		return get_volume()
	except Exception as e:
		return str(e)

@app.route('/vlcvolume/<cmd>')
def vlcvolume(cmd=''):
	global mplayer
	try:
		if type(cmd) in [int, float] or cmd.isdigit():
			mplayer.audio_set_volume(int(cmd))
		elif cmd=='up':
			mplayer.audio_set_volume(mplayer.audio_get_volume()+10)
		elif cmd=='down':
			mplayer.audio_set_volume(mplayer.audio_get_volume()-10)
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
	p.audio_set_volume(100)
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
	elif playFrom(obj['text'], obj['language'])=='OK':
		asr_finished = True
		play_audio('voice/asr_found.m4a')
	else:
		play_audio('voice/asr_not_found.m4a')

def ASR_server_thread():
	global ASR_server_running
	ASR_server_running = True
	try:
		obj = asr_model.transcribe(os.path.expanduser(asr_input), cancel_func=cancel_requested)
		handle_ASR(obj)
	except Exception as e:
		traceback.print_exc()
		play_audio('voice/asr_error.m4a')
	ASR_server_running = False

def ASR_cloud_thread():
	global ASR_cloud_running
	ASR_cloud_running = True
	try:
		with open(os.path.expanduser(asr_input), 'rb') as f:
			r = requests.post(ASR_CLOUD, files={'file': f}, timeout=4)
		if r.status_code==200:
			cancel_transcription()
		handle_ASR(json.loads(r.text))
	except Exception as e:
		traceback.print_exc()
		play_audio('voice/asr_error.m4a')
	ASR_cloud_running = False


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

	app.url_map.strict_slashes = False
	app.run(host='0.0.0.0', port=port)

