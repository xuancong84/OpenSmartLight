#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, sys, traceback, argparse, math, requests, json, re, webbrowser
import subprocess, random, time, threading, socket, scipy, sympy, mpmath
import vlc, signal, qrcode, qrcode.image.svg
import pandas as pd
from collections import *
from io import StringIO
from flask import Flask, Response, request, send_from_directory, send_file, render_template, render_template_string
from flask.logging import default_handler
from flask_sock import Sock
from unidecode import unidecode
from gtts import gTTS
from lingua import LanguageDetectorBuilder
from langcodes import Language as LC
from lib.DefaultRevisionDict import InfiniteDefaultRevisionDict
from lib.gTranslateTTS import gTransTTS
from lib.settings import *
from lib.NLP import *
from lib.chatGPT import *
from lib.FanLevelDNN import *
from device_config import *

_regex_ip = re.compile("^(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\\.(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\\.(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\\.(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$")
isIP = _regex_ip.match

app = Flask(__name__, template_folder='template')
app.url_map.strict_slashes = False
app.config['TEMPLATES_AUTO_RELOAD'] = True	##DEBUG
app.logger.removeHandler(default_handler)
logging.getLogger('werkzeug').setLevel(logging.ERROR)
sock = Sock(app)
get_volume = lambda: RUN("amixer get Master | awk -F'[][]' '/Left:/ { print $2 }'").rstrip('%\n')
ping = lambda ip: os.system(f'ping -W 1 -c 1 {ip}')==0

inst = vlc.Instance()
event = vlc.EventType()
ev_mutex = threading.Event()
ev_reply = None
asr_input = DEFAULT_S2T_SND_FILE
player = None
playlist = None
mplayer = None
filelist = []
P_ext = None
P_hidecursor = None
isFirst = True
isVideo = None
subtitle = True
last_get_file_ip = ''
g_last_speak_time = 0
g_last_speak_popen = None
isJustAfterBoot = True if sys.platform=='darwin' else float(open('/proc/uptime').read().split()[0])<120
random.seed(time.time())
M_ASR = []
ASR_server_running = ASR_cloud_running = False
lang_detector = LanguageDetectorBuilder.from_languages(*lang2id.keys()).build()

def get_local_IP():
	s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
	s.connect(('8.8.8.8', 1))
	return s.getsockname()[0]

local_IP = get_local_IP()
load_playstate = lambda: Try(lambda: InfiniteDefaultRevisionDict().from_json(Open(PLAYSTATE_FILE)), InfiniteDefaultRevisionDict())
last_save_time = time.time()
def save_playstate(obj, lazy=False):
	global last_save_time
	if (not lazy) or (time.time()-last_save_time>3600):
		obj.prune(max_items=PLAY_HISTORY_MAX_ITEMS, max_age=PLAY_HISTORY_RETENTION_SEC)
		with Open(PLAYSTATE_FILE+'.tmp.gz', 'wt') as fp:
			obj.to_json(fp, indent=1)
		last_save_time = time.time()
		os.rename(PLAYSTATE_FILE+'.tmp.gz', PLAYSTATE_FILE)

os.save_state = lambda: save_playstate(ip2tvdata)
get_base_url = lambda: f'{"https" if ssl else "http"}://{local_IP}:{port}'

IP2websock = IP_Dict()
ip2ydsock, ip2plsock = {}, {}
os.ip2ydsock = ip2ydsock
# ip2tvdata: {'IP':{'markers':{list1_json: [cur_ii1, time1],...},
#					'playlist':[], 'cur_ii':int,
# 					'T2Slang':'', 'T2Stext':'', 'S2Tlang':'', 'S2Ttext':''}}
os.sys_state = ip2tvdata = load_playstate()

@tool
def tv_list():
	"""List all available TVs in the house

	Returns:
		A dict of {TV_name: {"mac": MAC_address, "ip": IP_address}}
	"""
	return Try(lambda: json.load(Open(LG_TV_CONFIG_FILE)), {})
_tv2lginfo = tv_list()

def tv2lginfo(tv_name):
	ret = _tv2lginfo.get(tv_name, tv_name)
	if tv_name!=ret:
		os.lastTVname = tv_name
	return ret
get_tv_ip = lambda t: Try(lambda: tv2lginfo(t)['ip'], t)
get_tv_data = lambda t: ip2tvdata[ip_strip(Try(lambda: tv2lginfo(t)['ip'], t))]
def ip2tvname(t):
	# resolve a bare/port-suffixed IP (e.g. from a websocket peer address) back to its configured TV name
	if t in _tv2lginfo:
		return t
	ip = ip_strip(t)
	for tv_name, info in _tv2lginfo.items():
		if info.get('ip')==ip:
			return tv_name
	return t
get_hub_url = lambda name: HUBS.get(name, name if [s for s in HUBS.values() if url_is_ip(name, s)] else '')


# Pre-filter when multiple ASR hubs send the same request within RL_MAX_DELAY seconds
last_request_from, last_request_url, last_request_time = None, None, 0
@app.before_request
def common_prefilter():
	global last_request_from, last_request_url, last_request_time
	r, tms = request, str(pd.Timestamp.now())[:21]
	app.logger.critical(f'[{tms}] FROM:{r.remote_addr} {r.method} {r.path} DATA:{r.data[:20]}')
	if request.method=='GET':
		if last_request_from!=r.remote_addr and last_request_url==r.url and time.time()-last_request_time<RL_MAX_DELAY:
			app.logger.critical(f'[{tms}] IGNORED 204 lastReqFrom={last_request_from} lastReqTime={last_request_time}')
			return 'Ignored', 204
		last_request_from, last_request_url, last_request_time = r.remote_addr, r.url, time.time()

# Detect language, invoke Google-translate TTS and play the speech audio
def prepare_TTS(txt, lang_id=None, fn=DEFAULT_T2S_SND_FILE):
	lang_id = lang_id or Try(lambda: lang2id[lang_detector.detect_language_of(txt)], 'km')
	LOG(f'TTS txt="{txt}" lang_id={lang_id}')
	Try(lambda: os.makedirs(os.path.dirname(fn), exist_ok=True))
	try:
		tts = gTTS(txt, lang=lang_id)
		tts.save(fn+'.mp3')
	except:
		gTransTTS(txt, lang_id, fn+'.mp3')
	os.system(f'ffmpeg -y -i "{fn}.mp3" -af "adelay=300ms:all=true,volume=2" "{fn}"')
	return lang_id, txt
os.prepare_TTS = prepare_TTS

def play_TTS(txt, tv_name=None):
	txts = txt if type(txt)==list else [txt]
	for seg in txts:
		prepare_TTS(seg)
		play_audio(DEFAULT_T2S_SND_FILE, True, tv_name)


### Start handling of URL requests	###

@app.route('/custom_cmdline/<cmd>')
def custom_cmdline(cmd, wait=False):
	try:
		exec(open('device_config.py').read(), locals(), locals())
		cmdline = CUSTOM_CMDLINES[cmd]
		return RUN(cmdline+('' if wait else ' &'))
	except Exception as e:
		traceback.print_exc()
		return str(e)

@tool
@app.route('/py_exec/<path:cmd>')
def py_exec(cmd):
	"""Execute python code in the global context, i.e., exec(cmd, globals(), globals())

	Args:
		cmd (str): python command

	Returns:
		str: "OK" if no exception; stack trace if error
	"""
	try:
		exec(cmd, globals(), globals())
		return "OK"
	except:
		return traceback.format_exc()

@tool
@app.route('/py_eval/<path:cmd>')
def py_eval(cmd):
	"""Evaluate python code in the global context, i.e., eval(cmd, globals(), globals())

	Args:
		cmd (str): python expression

	Returns:
		str: string form of the output or stack trace if error, i.e., str(output)
	"""
	try:
		return eval(cmd, globals(), globals())
	except:
		return traceback.format_exc()

@app.route('/sh_exec/<path:cmd>')
def sh_exec(cmd):
	return str(runsys(cmd))

@app.route('/sh_exec_mp/<path:cmd>')
def sh_exec_mp(cmd):
	RUNSYS(cmd)
	return 'OK'

@app.route('/files')
@app.route('/files/<path:filename>')
def get_file(filename=''):
	global last_get_file_ip
	fn = os.path.join(SHARED_PATH, filename.strip('/'))
	if os.path.isdir(fn):
		return render_template('folder.html', rpath=request.path.rstrip('/'), folder=fn[len(SHARED_PATH):], files=showdir(fn))
	last_get_file_ip = request.remote_addr
	return send_from_directory(SHARED_PATH, filename.strip('/'), conditional=True)

@app.route('/favicon.ico')
def get_favicon():
	return send_file('template/favicon.ico')

@app.route('/')
def get_index_page():
	return render_template('index.html', hubs=HUBS)

@tool
@app.route('/get_http/<path:url>')
def get_http(url, timeout=None):
	"""Send HTTP request to the given URL

	Args:
		url (str): the URL

	Returns:
		(str, int): response text and status code
	"""
	try:
		res = requests.get(url if url.startswith('http://') else f'http://{url}', timeout=timeout)
	except:
		return '', 404
	return res.text, res.status_code
os.get_http = get_http

@app.route('/voice')
@app.route('/voice/<path:fn>')
def get_voice(fn=''):
	return send_from_directory('./voice', fn, conditional=True) if fn else send_file(DEFAULT_T2S_SND_FILE, conditional=True)

@app.route('/subtt/<path:fn>')
def subtt(fn='0.vtt'):
	rfp = os.path.realpath(os.path.join(SHARED_PATH, fn))
	return send_from_directory(os.path.join(TMP_DIR, '.subtitles'), rfp.lstrip('/'), conditional=True)

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

@app.route('/get_playlist')
def get_playlist():
	global filelist, player, mplayer
	obj = {
		'volume': Try(lambda: int(get_volume()), None),
		'cur_i': Try(lambda: filelist.index(mrl2path(mplayer.get_media().get_mrl())), -1),
		'paused': Try(lambda: not mplayer.is_playing(), None),
		'list': [] if player==None else [os.path.basename(f) for f in filelist],
		'timer': Timers[None].desc if (None in Timers and Timers[None].is_alive()) else None,
		'loopMode': Try(lambda: player.loop_mode, 0),
	}
	return json.dumps(obj)

def onPlaylistChanged(*args):
	for ip, ws in ip2plsock.items():
		ws.send('updatePlayList()')

def on_media_opening(*args):
	global isFirst, isVideo
	print(f'Starting to play: {mrl2path(mplayer.get_media().get_mrl())}', file=sys.stderr)
	onPlaylistChanged()
	if isVideo:
		wait_tm = (3 if isJustAfterBoot else 2) if isFirst else 1
		threading.Timer(wait_tm, lambda:mplayer.set_fullscreen(False)).start()
		threading.Timer(wait_tm+.2, lambda:mplayer.set_fullscreen(True)).start()
		threading.Timer(wait_tm+.8, lambda:ensure_fullscreen()).start()
		threading.Timer(wait_tm+2, show_subtitle).start()
		isFirst = False

def _play(tm_info, filename=''):
	global inst, player, playlist, filelist, mplayer, isVideo
	filelist, ii, tm_sec, is_random = load_playable(None, tm_info, filename)
	isVideo = bool([fn for fn in filelist if isVideoFileExt(fn)])

	stop()
	set_audio_device(MP4_SPEAKER if isVideo else MP3_SPEAKER)
	playlist = inst.media_list_new(filelist)
	if player == None:
		player = inst.media_list_player_new()
	player.set_media_list(playlist)

	mplayer = player.get_media_player()
	mplayer.event_manager().event_attach(event.MediaPlayerOpening, on_media_opening)
	loop_mode(0)
	player.play_item_at_index(ii)
	threading.Timer(1, lambda:mplayer.audio_set_volume(100)).start()
	if tm_sec>0:
		threading.Timer(1000, lambda:player.set_position(tm_sec)).start()

@app.route('/play/<tm_info>')
@app.route('/play/<tm_info>/<path:filename>')
def play(tm_info, filename=''):
	run_thread(_play, tm_info, filename)
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

@app.route('/togglePause')
def togglePause():
	global player
	try:
		player.pause()
	except Exception as e:
		return str(e)
	return 'OK'

@app.route('/set_timer/<tm>')
@app.route('/set_timer/<tm>/<name>')
@app.route('/set_timer/<tm>/<name>/<path:filename>')
def set_timer(tm='', name=None, filename=''):
	# each device can only have one on/off timer; if device is on, set timer to turn it off; otherwise, set timer to turn it on
	# if name is in `HUB`, it will send execRC command to the hub
	global player
	if tm==' ':
		DelTimer(name)
		if is_tv_wsock(name):
			tv_wscmd(name, 'clear_countdown()')
		return 'Timer deleted OK'
	if ':' in tm:
		tm_sec = (pd.Timestamp(tm)-pd.Timestamp.now()).total_seconds()
		tm_sec = tm_sec+3600*24 if tm_sec<0 else tm_sec
	else:
		tm_sec = Try(lambda: pd.to_timedelta(float(tm), unit='H').total_seconds(), lambda: pd.to_timedelta(tm).total_seconds(), None)
		if tm_sec==None:
			return f'Error: cannot parse time {tm}'
	tm_til = str(pd.Timestamp.now()+pd.to_timedelta(f'{tm_sec}s'))[:19]
	if name==None:
		if player==None:
			SetTimer(name, tm_sec, lambda: play('0 0 1', filename), f'将于{tm_til}定时开启音乐播放')
		else:
			SetTimer(name, tm_sec, lambda: stop(), f'将于{tm_til}定时关闭音乐播放')
		onPlaylistChanged()
	elif get_hub_url(name):
		SetTimer(name, tm_sec, lambda: send_hub_cmd(name, filename), f'将于{tm_til}定时向{name}发送指令{name}')
	elif is_tv_on(name):
		SetTimer(name, tm_sec, lambda: tv(name, 'off'), f'将于{tm_til}定时关闭电视机{name}')
		if is_tv_wsock(name):
			tv_wscmd(name, f'set_countdown({tm_sec})')
	else:
		if filename:
			SetTimer(name, tm_sec, lambda: _tvPlay(name, filename, os.url_root), f'将于{tm_til}定时开启电视机{name}并播放{filename}')
		else:
			SetTimer(name, tm_sec, lambda: tv(name, 'on'), f'将于{tm_til}定时开启电视机{name}')
			
	return 'OK'

def handle_ASR_timer(asr_out, tv_name, _, filename, url_root, **kwargs):
	if not asr_out['text']: return
	tm = txt2time(asr_postprocess(asr_out['text']))
	if tm is None:
		return play_audio('voice/set_timer_unknown.mp3', True, tv_name)
	return play_audio('voice/set_timer_okay.mp3' if set_timer(str(tm), tv_name, filename) == 'OK' else 'voice/set_timer_fail.mp3', True, tv_name)

@app.route('/set_spoken_timer', methods=['GET', 'POST'])
@app.route('/set_spoken_timer/<tv_name>', methods=['GET', 'POST'])
@app.route('/set_spoken_timer/<tv_name>/<path:filename>', methods=['GET', 'POST'])
def set_spoken_timer(tv_name=None, filename=None):
	tv_name = None if tv_name in [None, ' '] else tv_name
	is_post, url_root = save_post_file(), get_url_root(request)
	prompt = '' if is_post else 'voice/set_timer_speak.mp3'
	run_thread(recog_and_do, prompt, tv_name, filename, handle_ASR_timer, url_root)
	return 'OK'

@tool
def send_hub_cmd(hub_name, cmd):
	"""Send RC (remote control) command to the hub

	Args:
		hub_name (str): name of the controller hub
		cmd (str): the RC code
	"""
	get_http(get_hub_url(hub_name) + f'/rc_run?{cmd}')

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

@app.route('/rewind')
@app.route('/rewind/<tv_name>')
def rewind(tv_name=None):
	global player
	try:
		if tv_name:
			return tv_wscmd(tv_name, 'rewind')
		else:
			player.set_position(0)
			player.set_pause(False)
			return 'OK'
	except Exception as e:
		return str(e)

def _normalize_vol(song, remote_ip=None):
	global player, last_get_file_ip
	if song:
		fn = expand_path(song if song.startswith('~') else (SHARED_PATH+'/'+song))
		norm_song_volume(fn)
		if remote_ip in IP2websock and ip_strip(remote_ip) in ip2tvdata:
			tv_wscmd(remote_ip, f'show_banner(-1);v.src=v.src+"?{time.time()}"')
	elif player is not None:
		mrl = mplayer.get_media().get_mrl()
		cur_ii = filelist.index(mrl2path(mrl))
		if cur_ii<0: return
		fn = mrl2path(filelist[cur_ii])
		if not os.path.isfile(fn): return
		player.stop()
		play_audio('voice/processing.mp3', False)
		norm_song_volume(fn)
		player.play_item_at_index(cur_ii)
	elif last_get_file_ip:
		dev_ip = last_get_file_ip
		tvd = ip2tvdata[dev_ip]
		playlist, cur_ii = tvd['playlist'], tvd['cur_ii']
		tv_wscmd(dev_ip, 'pause')
		play_audio('voice/processing.mp3', False, dev_ip)
		norm_song_volume(playlist[cur_ii])
		tv_wscmd(dev_ip, f'show_banner(-1);v.src=v.src+"?{time.time()}"')

@app.route('/normalize_vol')
@app.route('/normalize_vol/<path:song>')
def normalize_vol(song=''):
	client_port = request.environ.get('REMOTE_PORT')
	run_thread(_normalize_vol, song, f'{request.remote_addr}:{client_port}')
	return 'OK'

@app.route('/playFrom/<name>')
@app.route('/playFrom/<tv_name>/<name>')
def playFrom(name='', tv_name=None, lang=None):
	global player
	try:
		plist = Try(lambda: get_tv_data(tv_name)['playlist'], filelist)
		ii = name if type(name)==int else findSong(name, lang=lang, flist=plist)
		assert ii!=None
		player.play_item_at_index(ii) if tv_name is None else tv_wscmd(tv_name, f'goto_idx {ii}')
	except Exception as e:
		return str(e)
	return 'OK'

@app.route('/playFromN/<int:N>')
@app.route('/playFromN/<tv_name>/<int:N>')
def playFromN(N=0, tv_name=None):
	global player
	try:
		player.play_item_at_index(N) if tv_name is None else tv_wscmd(tv_name, f'goto_idx {N}')
	except Exception as e:
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
		onPlaylistChanged()
	except Exception as e:
		ret = str(e)
	player = None
	Try(lambda: unset_audio_device(MP3_SPEAKER) if request.query_string == b'off' else 0)
	return ret

loopModes = [vlc.PlaybackMode.loop, vlc.PlaybackMode.repeat, vlc.PlaybackMode.default]
@app.route('/loop_mode/<int:mode>')
@app.route('/loop_mode/<tv_name>/<int:mode>')
def loop_mode(mode=1, tv_name=None):
	global player
	ret = 'OK'
	try:
		if tv_name:
			tv_wscmd(tv_name, f'loop_mode {mode}')
		else:
			player.set_playback_mode(loopModes[mode])
			player.loop_mode = mode
			onPlaylistChanged()
	except Exception as e:
		ret = str(e)
	return ret

def is_ble_connected(dev_mac):
	ret = RUN(f'bluetoothctl info {dev_mac}' if sys.platform=='linux' else f'blueutil --info {dev_mac}')
	for L in ret.splitlines():
		its = L.split()
		if its[0].lower().startswith('connected'):
			return its[1].lower()=='yes'
	return None

def remove_ble(dev_mac):
	os.system(f'bluetoothctl remove {dev_mac}' if sys.platform=='linux' else f'blueutil --remove {dev_mac}')

def is_ble_trusted(dev_mac):
	ret = RUN(f'bluetoothctl devices Trusted' if sys.platform=='linux' else f'blueutil --devices Trusted')
	return bool([L for L in ret.splitlines() if dev_mac.upper() in L])

def trust_ble(dev_mac):
	timeout = 5
	while not is_ble_trusted(dev_mac) and timeout<10:
		os.system(f'bluetoothctl power on' if sys.platform=='linux' else f'blueutil --power on')
		os.system(f'bluetoothctl --timeout {timeout} scan on' if sys.platform=='linux' else f'blueutil --timeout {timeout} --scan on')
		os.system(f'bluetoothctl trust {dev_mac}' if sys.platform=='linux' else f'blueutil --trust {dev_mac}')
		timeout += 1

def is_ble_paired(dev_mac):
	ret = RUN(f'bluetoothctl devices Paired' if sys.platform=='linux' else f'blueutil --devices Paired')
	return bool([L for L in ret.upper().splitlines() if dev_mac.upper() in L])

def pair_ble(dev_mac):
	if is_ble_paired(dev_mac):
		return True
	os.system(f'bluetoothctl --timeout 8 pair {dev_mac}' if sys.platform=='linux' else f'blueutil --timeout 8 --pair {dev_mac}')
	return is_ble_paired(dev_mac)

def is_ble_connected(ble_dev):
	dev_mac = ble_dev.get('mac', '') if type(ble_dev)==dict else ble_dev
	ret = RUN(f'bluetoothctl devices Connected' if sys.platform=='linux' else f'blueutil --devices Connected')
	return bool([L for L in ret.upper().splitlines() if dev_mac.upper() in L])

@app.route('/connectble/<device>')
def connectble(dev_mac):
	while not is_ble_paired(dev_mac):
		remove_ble(dev_mac)
		trust_ble(dev_mac)
		pair_ble(dev_mac)
	if is_ble_connected(dev_mac):
		return '0'
	disconnectble(dev_mac)
	ret = os.system(f'bluetoothctl connect {dev_mac}' if sys.platform=='linux' else f'blueutil --connect {dev_mac}')
	return str(ret)

@app.route('/disconnectble/<device>')
def disconnectble(dev_mac=''):
	ret = os.system(f'bluetoothctl disconnect {dev_mac}' if sys.platform=='linux' else f'blueutil --disconnect {dev_mac}')
	return str(ret)

@app.route('/volume/<cmd>')
def set_volume(cmd=None, tv_name=None):
	if tv_name != None:
		return tvVolume(name=tv_name, vol=cmd) if is_tv_on(tv_name) else 'ignored'
	try:
		ret = None
		if type(cmd) in [int, float] or cmd.isdigit():
			ret = os.system(f'amixer sset Master {int(cmd)}%' if sys.platform=='linux' else f'osascript -e "set volume output volume {int(cmd)}"')
		elif cmd=='up':
			ret = os.system('amixer sset Master 10%+' if sys.platform=='linux' else 'osascript -e "set volume output volume (output volume of (get volume settings) + 10)"')
		elif cmd=='down':
			ret = os.system('amixer sset Master 10%-' if sys.platform=='linux' else 'osascript -e "set volume output volume (output volume of (get volume settings) - 10)"')
		if ret is not None:
			onPlaylistChanged()			
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


### For LG TV
# Set T2S/S2T info
def setInfo(tv_name, text, lang, prefix, match=None, wait=False):
	langName = LC.get(lang).display_name('zh')
	ip = get_tv_ip(tv_name)
	ip2tvdata[ip_strip(ip)].update({f'{prefix}_lang': langName, f'{prefix}_text': text}|({} if match==None else {f'{prefix}_match': match}))
	if ip and is_tv_on(tv_name):
		wait_for_ws(tv_name) if wait else None
		IP2websock.send(ip, f'{prefix}lang.textContent="{langName}";{prefix}text.textContent="{text}";'+(f'{prefix}match.textContent="{match}"' if match!=None else ''))

def _report_title(tv_name, title=''):
	with VoicePrompt(tv_name, 'voice/cur_song_title.mp3') as context:
		ev = play_audio('voice/cur_song_title.mp3', False, tv_name)
		if tv_name:
			if not title:
				data = get_tv_data(tv_name)
				title = data['playlist'][data['cur_ii']]
			langId, txt = prepare_TTS(filepath2songtitle(title))
			setInfo(tv_name, txt, langId, 'T2S')
		else:
			prepare_TTS(filepath2songtitle(mrl2path(mplayer.get_media().get_mrl())))
		ev.wait()
		play_audio(DEFAULT_T2S_SND_FILE, True, tv_name)

@app.route('/report_title')
@app.route('/report_title/<tv_name>')
def report_title(tv_name=None, title=''):
	run_thread(_report_title, tv_name, title)
	return 'OK'

@app.route('/is_tv_on/<tv_name>')
def is_tv_on(tv_name):
	return ping(ip_strip(get_tv_ip(tv_name)))

@app.route('/is_tv_ready/<tv_name>')
def is_tv_ready(tv_name):
	return os.system(f'{LG_TV_BIN} --name {tv_name} audioVolume')==0

# Whether TV browser websocket is connected (so that it can play sound)
@app.route('/is_tv_wsock/<tv_name>')
def is_tv_wsock(tv_name):
	return is_tv_on(tv_name) and get_tv_ip(tv_name) in IP2websock

@tool
@app.route('/tv_on/<tv_name>')
def tv_on_if_off(tv_name, wait_ready=False):
	"""Turn on the specified TV

	Args:
		tv_name (str): TV name string
		wait_ready (bool = False): whether to wait for TV to be ping-able

	Returns:
		str: "OK"
	"""
	tvinfo = tv2lginfo(tv_name)
	if not is_tv_on(tv_name):
		send_wol({'data': tvinfo['mac']})
		time.sleep(5)
	if wait_ready:
		while not is_tv_ready(tv_name):
			time.sleep(1)
		time.sleep(1)
	return 'OK'
os.tv_on_if_off = tv_on_if_off

@app.route('/tv_setInput/<tv_name>')
def tv_setInput(tv_name, input_id):
	tv_on_if_off(tv_name, wait_ready=True)
	os.system(f'{LG_TV_BIN} --name {tv_name} setInput {input_id}')
	return 'OK'

@app.route('/tv/<name>/<cmd>')
def tv(name='', cmd=''):
	if cmd == 'on':
		return tv_on_if_off(name)
	for i in range(3):
		res = os.system(f'{LG_TV_BIN} --name {name} {cmd}')
		if res==0:
			return 'OK'
		time.sleep(1)
	return 'Failed after trying 3 times!'
os.tv = tv

@tool
@app.route('/tvVolume/<name>/<vol>')
def tvVolume(name='', vol=''):
	"""Get or adjust TV volume

	Args:
		name (str): TV name
		vol (str): e.g., "+5%", "15" (the normal level, different on different TVs), "-10%", "" (get the current volume)

	Returns:
		str: operation status
	"""
	try:
		vol = str(vol)
		is_perc = vol.endswith('%')
		neg_mul = -1 if vol.startswith('-') else 1
		value = abs(int(vol.rstrip('%')))
		if not vol[0].isdigit():
			ret = RUN(f'{LG_TV_BIN} --name {name} audioVolume')
			L = ret[ret.find('"volume":'):]
			cur_vol = int(L[L.find(' '):L.find(',')])
			value = cur_vol + (max(1, round(cur_vol*value/100)) if is_perc else value)*neg_mul
		return RUN(f'{LG_TV_BIN} --name {name} setVolume {value}')
	except:
		pass
	try:
		ret = RUN(f'{LG_TV_BIN} --name {name} audioVolume')
		L = ret[ret.find('"volume":'):]
		return str(int(L[L.find(' '):L.find(',')]))
	except Exception as e:
		return str(e)

@sock.route('/ws_init')
def ws_init(sock):
	global IP2websock
	addr = sock.sock.getpeername()
	key = f'{addr[0]}:{addr[1]}'
	LOG(f'TV Websock: {key} connected', file=sys.stderr)
	IP2websock[key] = sock
	while sock.connected:
		try:
			cmd = sock.receive()
			tv_wscmd(key, cmd)
		except:
			LOG(f'TV Websock: {key} disconnected', file=sys.stderr)
	IP2websock.pop(key)

def wait_for_ws(tv_name, max_time=10):
	global IP2websock
	tm, ip = time.time(), get_tv_ip(tv_name)
	while (ip not in IP2websock) and (time.time()-tm<max_time):
		time.sleep(0.1)

@sock.route('/yd_init')
def yd_init(sock):
	global ip2ydsock
	key = sock.sock.getpeername()[0]
	LOG(f'yt-dlp Websock: {key} connected', file=sys.stderr)
	ip2ydsock[key] = sock
	while sock.connected:
		try:
			cmd = sock.receive()
		except:
			LOG(f'yt-dlp Websock: {key} disconnected', file=sys.stderr)
	ip2ydsock.pop(key)

@sock.route('/pl_init')
def pl_init(sock):
	global ip2plsock
	key = sock.sock.getpeername()[0]
	LOG(f'Playlist Websock: {key} connected', file=sys.stderr)
	ip2plsock[key] = sock
	sock.send('updatePlayList()')
	while sock.connected:
		try:
			cmd = sock.receive()
		except:
			LOG(f'Playlist Websock: {key} disconnected', file=sys.stderr)
			# traceback.print_exc()
	ip2plsock.pop(key)

def load_playable(ip, tm_info, filename):
	if ip==None and filename=='':
		filename = MP3_DFTLIST
	fullname = filename if type(filename)==str and filename.startswith(SHARED_PATH) else (SHARED_PATH+str(filename))
	tm_sec, ii, randomize = list_get_args(tm_info.split(), 3, [0,0], lambda t: int(float(t)))
	tvd = ip2tvdata[ip_strip(ip)]
	if not filename:
		lst = tvd['playlist']
	elif is_json_lst(filename):
		lst = json.loads(filename)
	elif fullname.lower().endswith('.m3u'):
		lst = load_m3u(fullname)
	elif os.path.isdir(fullname):
		lst = ls_media_files(fullname) or getAnyMediaList(fullname, media_file_exts)
	elif os.path.isfile(fullname):
		lst = ls_media_files(os.path.dirname(fullname))
		ii = Try(lambda: lst.index(fullname), 0)
	else:
		while not os.path.isdir(fullname):
			fullname = os.path.dirname(fullname)
		while fullname.startswith(SHARED_PATH):
			lst, randomize, ii = getAnyMediaList(fullname), 0, 0
			if lst: break
			fullname = os.path.dirname(fullname)
		if not fullname.startswith(SHARED_PATH):
			return [""], 0, 0, 0
	if ii<0 or tm_sec<0:
		ii, tm_sec = tvd['markers'].get(json.dumps(lst), [0,0])
	if randomize:
		if randomize==2:
			elem = lst[ii] if 0<=ii<len(lst) else None
			random.shuffle(lst)
			ii = ii if elem is None else lst.index(elem)
		else:
			random.shuffle(lst)
	lst = [(s if s.startswith(SHARED_PATH) else SHARED_PATH+s) for s in lst]
	tvd.update({'playlist': lst, 'cur_ii': ii, 'shuffled': randomize})
	return lst, ii, tm_sec, randomize

@app.route('/webPlay')
@app.route('/webPlay/<tm_info>')
@app.route('/webPlay/<tm_info>/<path:filename>')
def webPlay(tm_info=None, filename=None):
	if tm_info==None:
		tvd = get_tv_data(request.remote_addr)
		if 'last_movie_drama' in tvd:
			lst, ii, tm_sec, is_random = load_playable(request.remote_addr, '-1', tvd['last_movie_drama'])
		else:
			lst = Try(lambda: tvd['playlist'], lambda: json.loads(list(tvd['markers'].keys())[-1]), lambda: getAnyMediaList())
			if lst:
				ii, tm_sec = tvd['markers'].get(json.dumps(lst), [tvd.get('cur_ii', 0), 0])
	else:
		lst, ii, tm_sec, is_random = load_playable(request.remote_addr, tm_info, filename)
		tvd = ip2tvdata[request.remote_addr]
	return render_template('video.html',
		listname=Try(lambda:''.join(lst[0].split('/')[-2:-1]), '') or '播放列表',
		playlist=[i.split('/')[-1] for i in lst],
		tvlist = TV_LIST,
		is_random = is_random,
		asrlookup = ASR_LOOKUP,
		file_path=f'/files/{lst[ii][len(SHARED_PATH):]}#t={tm_sec}' if lst else '',
		**{n:tvd.get(n,'') for n in ['T2S_text', 'T2S_lang', 'S2T_text', 'S2T_lang', 'S2T_match', 'cur_ii']})

@app.route('/tv_runjs')
def tv_runjs():
	name, cmd = unquote(request.query_string.decode()).split('/', 1)
	IP2websock.send(get_tv_ip(name), cmd)
	return 'OK'

@tool
def _tvPlay(name, listfilename, url_root=''):
	"""Turn on the specified TV and play the list of media files on the TV web-browser

	Args:
		name (str): TV name
		listfilename (list): list of media filenames

	Returns:
		str: result
	"""
	tv_name, tm_info = list_get_args(name.split(' ',1), 2, ['0'])
	url_root = url_root or os.url_root
	if is_json_lst(listfilename):
		get_tv_data(tv_name)['playlist'] = json.loads(listfilename)
		listfilename = ''
	if tv_name in _tv2lginfo:
		tv_on_if_off(tv_name, True)
		return tv(tv_name, f'openBrowserAt "{url_root}/webPlay/{tm_info}/{listfilename}"')
	else:
		return IP2websock.send(get_tv_ip(tv_name), f'seturl("{url_root}/webPlay/{tm_info}/{listfilename}")') or 'OK'

@app.route('/tvPlay/<name>/<path:listfilename>')
def tvPlay(name, listfilename, url_root=None):
	run_thread(_tvPlay, name, listfilename, url_root or get_url_root(request))
	return 'OK'

def updateMarker(tvd):
	tvd['markers'].update({json.dumps(tvd['playlist']): [tvd['cur_ii'], tvd['cur_tm']]})
	fn = tvd['playlist'][tvd['cur_ii']]
	if getDuration(fn) >= DRAMA_DURATION_TH:
		tvd['last_movie_drama'] = fn
	tvd['markers'].prune(max_items=PLAY_HISTORY_MAX_ITEMS, max_age=PLAY_HISTORY_RETENTION_SEC)
	save_playstate(ip2tvdata, True)

def mark(name, tms, cur_file):
	tvd = get_tv_data(name)
	mrk_cur_file = SHARED_PATH + cur_file
	tvd_cur_file = Try(lambda: tvd['playlist'][tvd['cur_ii']], None)
	if mrk_cur_file != tvd_cur_file:
		return tv_wscmd(name, 'MARK()')
	tvd['cur_tm'] = float(tms)
	updateMarker(tvd)

def MARK(name, data):
	tvd = get_tv_data(name)
	data['playlist'] = [SHARED_PATH+s for s in data['playlist']]
	tvd.update(data)
	updateMarker(tvd)

def _load_subtitles(video_file, ip, force=False):
	video_file = os.path.realpath(video_file)
	out_dir = os.path.join(TMP_DIR, '.subtitles', video_file.lstrip('/'))
	if force or (not os.path.isdir(out_dir)) or (not listdir(out_dir)):
		Try(lambda: os.makedirs(out_dir))
		stt_info = list_subtitles(video_file, force=force)
		txt_stt = [fn.split('.')[0] for lang, fn, codec in stt_info if fn.endswith('.vtt')]
		vobsub_stt = [fn.split('.')[0] for lang, fn, codec in stt_info if fn.endswith('.sup') and codec=='dvd_subtitle']
		pgs_stt = [fn.split('.')[0] for lang, fn, codec in stt_info if fn.endswith('.sup') and codec=='hdmv_pgs_subtitle']
		n_subs = len(txt_stt+vobsub_stt+pgs_stt)
		LOG(f'Loading {n_subs} subtitle tracks ({len(txt_stt)} text & {len(vobsub_stt)+len(pgs_stt)} bitmap tracks) from "{video_file}" ...')
		if txt_stt:
			RUN(['ffmpeg', '-y', '-i', video_file]+[it for k in txt_stt for it in ['-map', f'0:{k}', '-f', 'webvtt', f'{out_dir}/{k}.vtt']], shell=False, timeout=9999)
		if vobsub_stt:
			RUN(['mkvextract', 'tracks', video_file] + [f'{k}:{out_dir}/{k}' for k in vobsub_stt], shell=False, timeout=9999)
			for k in vobsub_stt:
				runsys(f'DISPLAY=:0 java -jar lib/BDSup2Sub512.jar -o "{out_dir}/{k}.sup" "{out_dir}/{k}.idx"')
		if pgs_stt:
			# hdmv_pgs_subtitle is already stored in the raw PGS format that dvdsub.js decodes, so a plain stream copy suffices
			RUN(['ffmpeg', '-y', '-i', video_file]+[it for k in pgs_stt for it in ['-map', f'0:{k}', '-c:s', 'copy', f'{out_dir}/{k}.sup']], shell=False, timeout=9999)
		LOG(f'Finished loading {n_subs} subtitle tracks from "{video_file}"')
	IP2websock.send(ip, 'load_subtitles()')

def _show_mediainfo(fn, ip):
	fsize = os.stat(SHARED_PATH+fn).st_size
	txt = RUN(['ffprobe', SHARED_PATH+fn], shell=False, stderr=subprocess.STDOUT).splitlines()
	ii = [i for i,L in enumerate(txt) if L.startswith('Input ')][0]
	res = '\n'.join(['File size: %d (%.2f MB)'%(fsize, fsize/1024/1024)]+txt[ii:])
	tv_wscmd(ip, f'INFOframe.textContent=`{res.replace("`","")}`;')

@app.route('/tv_wscmd/<name>/<path:cmd>')
def tv_wscmd(name, cmd):
	global ev_reply, ev_mutex
	LOG(name+' : '+cmd)
	try:
		ip = get_tv_ip(name)
		ws = IP2websock[ip]
		tvd = ip2tvdata[ip_strip(ip)]
		if cmd.startswith('\t'):
			ev_reply = cmd[1:]
			ev_mutex.set()
		elif cmd == 'pause':
			ev_mutex.clear()
			ws.send(' pause()')
			ev_mutex.wait()
			return ev_reply
		elif cmd == 'resume':
			ws.send('v.play()')
		elif cmd == 'next':
			ws.send('goto_idx(cur_ii+1)')
		elif cmd == 'prev':
			ws.send('goto_idx(cur_ii-1)')
		elif cmd == 'rewind':
			ws.send('v.currentTime=0')
		elif cmd == 'hideQR':
			ws.send('QRcontainer.style.display="none";')
		elif cmd == 'play_spoken':
			play_spoken(name)
		elif cmd.startswith('report_title '):
			report_title(name, cmd.split(' ', 1)[1])
		elif cmd.startswith('mark '):
			mark(name, *cmd.split(' ', 2)[1:])
			tv(ip2tvname(name), 'screenOn')
		elif cmd.startswith('MARK '):
			MARK(name, json.loads(cmd.split(' ', 1)[1]))
		elif cmd.startswith('goto_idx '):
			ws.send(f'goto_idx({int(cmd.split()[1])})')
		elif cmd.startswith('norm_vol '):
			run_thread(_normalize_vol, cmd.split(' ', 1)[1], ip)
		elif cmd.startswith('loop_mode '):
			ws.send(f"toggle_loop({cmd.split(' ',1)[1]})")
		elif cmd.startswith('lsdir '):
			full_dir = SHARED_PATH+cmd.split(' ',1)[1]+'/'
			lst = showdir(full_dir)
			ws.send('\tshowDir\t'+'\n'.join([i+'\r'+transl_lower(i) for i in lst]))
		elif cmd.startswith('list_subtitles '):
			file_path = SHARED_PATH+cmd.split(' ',1)[1]
			subs = list_subtitles(file_path)
			LOG(f'"{file_path}" contains {len(subs)} subtitle tracks')
			ws.send(f'\tlist_subtitles\t{json.dumps(subs)}')
		elif cmd.startswith('load_subtitles '):
			args = cmd.split(' ', 2)
			force = int(args[1])
			file_path = SHARED_PATH+args[2]
			run_thread(_load_subtitles, file_path, ip, force)
		elif cmd.startswith('show_mediainfo '):
			args = cmd.split(' ', 1)
			run_thread(_show_mediainfo, args[1], ip)
		elif cmd.startswith('goto_file '):
			fn = SHARED_PATH + cmd.split(' ',1)[1].strip('/')
			flist = load_m3u(fn) if fn.lower().endswith('.m3u') else ls_media_files(os.path.dirname(fn))
			cur_ii = Try(lambda: [ii for ii,fulln in enumerate(flist) if fulln.endswith('/'+os.path.basename(fn))][0], 0)
			ws.send('\tupdateList\t'+'\n'.join([s.split('/')[-1] for s in flist]))
			ws.send(f'setvsrc("/files/{flist[cur_ii][len(SHARED_PATH):]}",{cur_ii})')
		else:
			ws.send(cmd)
		return 'OK'
	except Exception as e:
		return str(e)


# For audio
list_sinks = lambda: RUN('pactl list sinks short')
list_sources = lambda: RUN('pactl list sources short')

@app.route('/speaker/<cmd>/<name>')
def speaker(cmd, name, return_obj=False):
	if name.endswith('_SPEAKER'):
		name = Eval(name, name)
	t = run_thread(set_audio_device if cmd=='on' else unset_audio_device, name)
	return t if return_obj else str(t.ident)
os.speaker = speaker

def _off_speaker_delayed():
	global g_last_speak_time, g_last_speak_popen, player
	if g_last_speak_time: return
	g_last_speak_time = time.time()
	while True:
		time.sleep(10)
		if player != None: continue
		if (time.time()-g_last_speak_time < MP3_OFF_DELAY): continue
		if g_last_speak_popen != None and g_last_speak_popen.poll()==None:
			g_last_speak_popen.wait()
			g_last_speak_time = time.time()
		
	speaker('off', 'MP3_SPEAKER')
	g_last_speak_time = 0
os._off_speaker_delayed = _off_speaker_delayed

def set_audio_device(dev, wait=3):
	for i in range(wait+1):
		if type(dev) == dict:
			if dev.get('on', ''):
				return Invoke(dev['on'], lambda: set_audio_device(dev['mac'], wait=wait))
			dev = dev.get('mac', '')
		patn = dev
		if dev.count(':')==5:
			connectble(dev)
			patn = dev.replace(':', '_')
			time.sleep(1)
		out = [L.split() for L in list_sinks().splitlines()]
		res = [its[0] for its in out if patn in its[1]]
		if res:
			return os.system(f'pactl set-default-sink {res[0]}')==0
	return (os.system(f'pactl set-default-sink {out[0][0]}')==0) if out else False

def unset_audio_device(devs):
	for dev in (devs if type(devs)==list else [devs]):
		if type(dev) == dict:
			if dev.get('off', ''):
				Invoke(dev['off'])
				continue
			else:
				dev = dev.get('mac', '')
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

def play_ASRchip_voice(name, block=False):
	hex_cmd = ASRchip_voice_hex.get(name, '')
	if not hex_cmd:
		return False
	delay = 0
	if type(hex_cmd)==tuple:
		hex_cmd, delay = hex_cmd[:2]
	requests.get(f'{ASRchip_voice_IP}/asr_write?{hex_cmd}')
	if block:
		time.sleep(delay)
	return True

def play_audio_chip(fn, block=False):
	if not play_ASRchip_voice(os.path.basename(fn).split('.')[0], block):
		ev_mutex.set()
		return None
	ev_mutex.set()
	return ev_mutex

def _set_mutex_after_speak():
	global g_last_speak_time, g_last_speak_popen, ev_mutex
	g_last_speak_popen.wait()
	ev_mutex.set()
	g_last_speak_time = time.time() if g_last_speak_time else 0

def play_audio(fn, block=None, tv_name=None):
	# block: None (auto, i.e., True if from TV, False otherwise)
	global g_last_speak_time, g_last_speak_popen
	LOG(f'play_audio({fn}, {block}, {tv_name})')
	ev_mutex.clear()
	if tv_name:
		if not is_tv_wsock(tv_name):
			return play_audio_chip(fn, False if block==None else block)
		res = tv_wscmd(tv_name, f'play_audio("/{f"voice?{random.randint(0,999999)}" if fn==DEFAULT_T2S_SND_FILE else fn}",true)')
		assert res == 'OK'
	else:
		if not is_ble_connected(MP3_SPEAKER):
			return play_audio_chip(fn, False if block==None else block)
		g_last_speak_time = time.time() if g_last_speak_time else 0
		g_last_speak_popen = POPENCMD(f'mplayer -really-quiet -noconsolecontrols {fn}', shell=True)[0]
		run_thread(_set_mutex_after_speak)
		# RUNSYS(f'mplayer -really-quiet -noconsolecontrols {fn}', _set_last_speaker_time, event=ev_mutex)
	if block or block is None: ev_mutex.wait()
	return ev_mutex
os.play_audio = play_audio

def record_audio_for_duration(tm_sec=5, file_path=DEFAULT_S2T_SND_FILE):
	os.system(f'ffmpeg -y -f pulse -i {get_recorder(MIC_RECORDER)} -ac 1 -t {tm_sec} {file_path}')


# For ASR server
def get_ASR_offline(audio_fn=asr_input):
	try:
		obj = M_ASR[0].transcribe(audio_fn)
		return obj
	except Exception as e:
		traceback.print_exc()
		return str(e)

def get_ASR_online(audio_fn=asr_input):
	try:
		with Open(audio_fn, 'rb') as f:
			r = requests.post(f'{ASR_CLOUD_ENDP}/run_asr', files={'file': f}, timeout=ASR_CLOUD_TIMEOUT)
		return json.loads(r.text) if r.status_code==200 else {}
	except Exception as e:
		traceback.print_exc()
		return str(e)

class VoicePrompt:
	def __init__(self, tv_name=None, prompt=''):
		self.cur_sta = self.cur_vol = None
		self.tv_name = tv_name
		self.prompt = prompt

	def __enter__(self):	# preserve environment
		global player
		if self.prompt:
			if self.tv_name and is_tv_wsock(self.tv_name):
				self.cur_sta = tv_wscmd(self.tv_name, 'pause')
				self.cur_vol = tvVolume(self.tv_name)
			elif player!=None:
				self.cur_sta = player.is_playing()
				if self.cur_sta:
					player.set_pause(True)
				self.cur_vol = get_volume()
		return self

	def restore(self):
		if self.prompt:
			if self.tv_name:
				if self.cur_vol:
					tvVolume(self.tv_name, self.cur_vol)
				if self.cur_sta != 'true':
					tv_wscmd(self.tv_name, 'resume')
			else:
				if self.cur_vol != None:
					set_volume(self.cur_vol)
				if self.cur_sta:
					player.set_pause(False)
			self.cur_vol = self.cur_sta = None
		return True

	def __exit__(self, exc_type, exc_value, exc_tb):	# restore environment
		if exc_tb != None:
			traceback.print_tb(exc_tb)
		return self.restore()


# This function might take very long time, must be run in a separate thread
def recog_and_do(prompt, tv_name, path_name, handler, url_root='', audio_file=DEFAULT_S2T_SND_FILE, **kwargs):
	global player, M_ASR, ASR_cloud_running, ASR_server_running

	with VoicePrompt(tv_name, prompt) as context:
		# record speech
		if prompt:
			set_volume(VOICE_VOL[tv_name])
			play_audio(prompt if os.path.isfile(prompt) else f'voice/speak_{prompt}.mp3', True, tv_name)
			record_audio_for_duration(file_path=audio_file)

		# try cloud ASR
		asr_output = None
		if ASR_CLOUD_ENDP and not ASR_cloud_running:
			ASR_cloud_running = True
			asr_output = get_ASR_online(audio_file)
			ASR_cloud_running = False

		# try offline ASR if cloud ASR fails
		if type(asr_output)==str or not asr_output:
			if not M_ASR:
				return play_audio('voice/offline_asr_not_available.mp3', True, tv_name) if prompt else tv_wscmd(tv_name, "show_flashmsg('Offline ASR not available!')")
			if ASR_server_running:
				return play_audio('voice/unfinished_offline_asr.mp3', True, tv_name) if prompt else tv_wscmd(tv_name, "show_flashmsg('Another offline ASR is running!')")
			run_thread(lambda: [play_audio('voice/wait_for_asr.mp3', True, tv_name), context.restore()])
			asr_output = get_ASR_offline(audio_file)

		print(f'ASR result: {asr_output}', file=sys.stderr)
		if asr_output=={} or type(asr_output)==str:
			return play_audio('voice/asr_error.mp3', True, tv_name) if prompt else tv_wscmd(tv_name, f"show_flashmsg('ASR error: {asr_output}')")
		else:
			return handler(asr_output, tv_name, prompt, path_name, url_root.rstrip('/'), **kwargs)
os.recog_and_do = recog_and_do

def _play_last(name=None, url_root=None):
	tvd, tms, ii = get_tv_data(name), 0, 0
	if 'last_movie_drama' in tvd:
		pl, ii, tms, _ = load_playable(get_tv_ip(name), '-1', tvd['last_movie_drama'])
	else:
		pl = Try(lambda: tvd['playlist'], lambda: json.loads(list(tvd['markers'].keys())[-1]), lambda: getAnyMediaList())
		if pl:
			ii, tms = tvd['markers'].get(json.dumps(pl), [tvd.get('cur_ii', 0), 0])
	_tvPlay(f'{name} {tms} {ii}', json.dumps(pl), url_root)

@app.route('/play_last')
@app.route('/play_last/<tv_name>')
def play_last(tv_name=None):
	run_thread(_play_last, tv_name, get_url_root(request))
	return 'OK'

def handle_ASR_play(asr_out, tv_name, prompt, rel_path, url_root, **kwargs):
	if not asr_out['text']: return
	full_path = SHARED_PATH + rel_path
	if os.path.isdir(full_path):
		res = findMedia(asr_postprocess(asr_out['text']), asr_out['language'], base_path=full_path)
	elif os.path.isfile(full_path):
		lst = load_m3u(full_path) if rel_path else ip2tvdata[Try(lambda: ip_strip(tv2lginfo(tv_name)['ip']), None)]['playlist']
		res = findSong(asr_postprocess(asr_out['text']), asr_out['language'], lst)
	else:
		return 'Error: Invalid search path'

	if res == None:
		setInfo(tv_name, asr_out["text"], asr_out['language'], 'S2T', '')
		if prompt:
			play_audio(f'voice/asr_not_found_{prompt}.mp3', True, tv_name)
		elif tv_name:
			tv_wscmd(tv_name, "show_flashmsg('ASR okay, but media file not found!')")
		return 'ASR okay, but media file not found!'

	shuffle = kwargs.get('shuffle', 0)
	if type(res)==int:
		play_audio(f'voice/asr_found_{getMediaType(lst[res])}.mp3', None, tv_name)
		if rel_path:
			if shuffle:
				elem = lst[res]
				random.shuffle(lst)
				res = lst.index(elem)
			_tvPlay(f'{tv_name} 0 {res}', full_path if rel_path else json.dumps(lst), url_root) if tv_name else _play(f'0 {res}', json.dumps(lst))
		else:
			playFrom(res) if tv_name==None else tv_wscmd(tv_name, f'goto_idx {res}')
		media_fn = lst[res][len(SHARED_PATH):]
	elif type(res)==tuple:
		dn, epi = res if type(res)==tuple else (res, None)
		short_path = dn[len(SHARED_PATH):]
		play_audio(f'voice/asr_found_{getMediaType(dn)}.mp3', None, tv_name)
		if tv_name==None:
			_play(f'0 {epi}', short_path)
		else:
			_tvPlay(f'{tv_name} 0 {epi}', short_path, url_root)
		media_fn = ls_media_files(dn)[epi][len(SHARED_PATH):]
	else:
		short_path = res[len(SHARED_PATH):]
		if prompt:
			play_audio(f'voice/asr_found_{getMediaType(res)}.mp3', None, tv_name)
		else:
			tv_wscmd(tv_name, "show_flashmsg('Media found successfully, starting to play ...')")
		if tv_name == None:
			_play('-1' if os.path.isdir(res) else f'0 0 {shuffle}', short_path)
		else:
			_tvPlay(tv_name+(' -1' if os.path.isdir(res) else f' 0 0 {shuffle}'), short_path, url_root)
		media_fn = res[len(SHARED_PATH):]
	setInfo(tv_name, asr_out["text"], asr_out['language'], 'S2T', '' if res==None else media_fn, wait=True)
	return str(asr_out)

def save_post_file(fn=DEFAULT_S2T_SND_FILE):
	if request.method!='POST' or not request.data: return ''
	with Open(fn, 'wb') as fp:
		fp.write(request.data)
	return fn

# Play spoken item on TV
@app.route('/play_spoken', methods=['GET', 'POST'])
@app.route('/play_spoken/<tvName_prompt>', methods=['GET', 'POST'])
@app.route('/play_spoken/<tvName_prompt>/<path:rel_path>', methods=['GET', 'POST'])
def play_spoken(tvName_prompt='None', rel_path=''):
	tv_name, prompt, shuffle = list_get_args(tvName_prompt.split(), 3, ['song', '0'])
	is_post, url_root = save_post_file(), get_url_root(request)
	run_thread(recog_and_do, '' if is_post else prompt, None if tv_name=='None' else tv_name,
		rel_path, handle_ASR_play, url_root, **{'shuffle': int(shuffle)})
	return 'OK'

# Play spoken file recorded locally on the local device
@app.route('/play_recorded', methods=['POST'])
@app.route('/play_recorded/<path:rel_path>', methods=['POST'])
def play_recorded(rel_path=''):
	recfn, req = save_post_file(), request._get_current_object()
	client_port = request.environ.get('REMOTE_PORT')
	run_thread(recog_and_do, '', f'{req.remote_addr}:{client_port}', rel_path, handle_ASR_play, get_url_root(req), recfn)
	return 'OK'

# Compare ASR system
@app.route('/cmpASR', methods=['GET', 'POST'])
@app.route('/cmpASR/<path:rel_path>', methods=['POST'])
def cmpASR(rel_path=''):
	recfn = save_post_file()
	client_port = request.environ.get('REMOTE_PORT')
	if request.method == 'GET':
		r = requests.get(ASR_CLOUD_ENDP+'/cmp_asr', timeout=ASR_CLOUD_TIMEOUT)
		return Response(
			r.content,           # The raw binary body
			status=r.status_code, # The exact HTTP status code
		)
	try:
		ws = IP2websock[f'{request.remote_addr}:{client_port}']
		if not recfn:
			recfn = record_voice_until_sil(
				cb_on_speech=lambda: ws.send('recButtons2.style.background="#0f0"'),
				cb_on_return=lambda: ws.send('recButtons2.style.background="#00f"'))
		if not recfn:
			return ''
		with open(recfn, 'rb') as f:
			r = requests.post(f'{ASR_CLOUD_ENDP}/cmp_asr', files={'file': f})
		obj = json.loads(r.text) if r.status_code==200 else {}
		to_play = ''
		for k1, o1 in obj.items():
			asr_out = o1['out']
			res = findMedia(asr_postprocess(asr_out['text']), asr_out['language'], base_path=SHARED_PATH+rel_path)
			o1['found'] = res!=None
			to_play = res or to_play
		if to_play:
			tv_wscmd(f'{request.remote_addr}:{client_port}', 'goto_file '+to_play[len(SHARED_PATH):])
		return json.dumps(obj)
	except:
		ws.send(f'alert("{traceback.format_exc()}")')

@app.route('/audio_cache/<path:rel_path>')
def serve_audio(rel_path):
	target_path = os.path.join(AUDIO_CACHE_DIR, rel_path.lstrip('/'))
	if not os.path.isfile(target_path):
		prepare_TTS(os.path.basename(target_path).split('.')[0], fn=target_path)
	return send_file(target_path)

@app.route('/speak_file/')
@app.route('/speak_file/<path:subpath>')
def speak_file(subpath=""):
	# Security: Ensure we stay inside BASE_DIR
	target_path = os.path.normpath(os.path.join(SHARED_PATH, subpath.lstrip('/')))
	if not target_path.startswith(SHARED_PATH.rstrip('/')):
		return "Access Denied", 403

	if not os.path.isdir(target_path):
		return "Folder not found", 404

	folder_contents = []
	for item in os.listdir(target_path):
		item_path = os.path.join(target_path, item)
		is_dir = os.path.isdir(item_path)
		
		# Prepare item data
		item_data = {
			"name": item,
			"is_dir": is_dir,
			"rel_path": os.path.join(subpath, item).replace("\\", "/")
		}

		if not is_dir:
			base_name = os.path.splitext(item)[0]
			audio_filename = base_name + ".mp3"
			item_data["audio_url"] = '/audio_cache/'+audio_filename

		folder_contents.append(item_data)

	# Simple HTML template to handle logic
	template = """
	<h1>Browsing: /{{ subpath }}</h1>
	<ul>
		{% if subpath %}
			<li><a href="{{ '/speak_file/'+'/'.join(subpath.split('/')[:-1]) }}">.. (parent folder)</a></li>
		{% endif %}
		
		{% for item in contents %}
			<li>
				{% if item.is_dir %}
					📁 <a href="{{ '/speak_file/'+item.rel_path }}">{{ item.name }}/</a>
				{% else %}
					📄 <a href="#" onclick="new Audio('{{ item.audio_url }}').play(); return false;">{{ item.name }}</a>
				{% endif %}
			</li>
		{% endfor %}
	</ul>
	"""
	return render_template_string(template, contents=folder_contents, subpath=subpath)


# For Ecovacs
@app.route('/ecovacs', defaults={'name': '', 'cmd':''})
@app.route('/ecovacs/<name>/<cmd>')
def ecovacs(name='', cmd=''):
	return RUN(f'./ecovacs-cmd.sh {name} {cmd} &')

# For ceiling fan control
# autoFanOn levels exclude off state; autoFan levels include keeping the fan off
# `level` ranges from 1 to # of speed levels, 0 means off, None means auto
last_fan_tms = defaultdict(lambda:0)	# the last time when fan level is auto determined to be on
def autoFanLevel(name, level, forceOn):
	global last_fan_tms
	tms = time.time()
	fan_cmds = FAN_DATA[name]
	if name not in FAN_MODELS:
		FAN_MODELS[name] = FanLevelDNN(f'{NN_MODEL_PATH}/{name}.pt', len(fan_cmds['LEVELS']))
	fan_model = FAN_MODELS[name]
	wt = get_weather()
	if level==None:
		level = fan_model.predict(wt['temperature'], wt['humidity'])
		level = max(level, 1) if forceOn else level
		if level>0:
			if 'ON' in fan_cmds:
				execRC(fan_cmds['ON'])
			execRC(fan_cmds['LEVELS'][level-1])
			if 'S_LEVELS' in fan_cmds:
				play_ASRchip_voice(fan_cmds['S_LEVELS'][level-1])
			last_fan_tms[name] = tms
		else:
			if 'S_OFF' in fan_cmds:
				play_ASRchip_voice(fan_cmds['S_OFF'])
			# shall not actively turn off the fan if predicted_fan_level==0
			# execRC(fan_cmds['OFF'])
	else:
		if level or (level==0 and tms-last_fan_tms[name]<100):
			fan_model.add_data(wt['temperature'], wt['humidity'], level)
			fan_model.train()
			fan_model.save()

@app.route('/autoFan/<name>')
@app.route('/autoFan/<name>/<int:level>')
def autoFan(name='', level=None):
	run_thread(autoFanLevel, name, level, False)
	return 'OK'

@app.route('/autoFanOn/<name>')
@app.route('/autoFanOn/<name>/<int:level>')
def autoFanOn(name='', level=None):
	run_thread(autoFanLevel, name, level, True)
	return 'OK'

def killMode():
	global P_ext, P_hidecursor
	os.killpg(os.getpgid(P_ext.pid), signal.SIGKILL)
	P_ext = None
	if sys.platform=='linux' and P_hidecursor is not None:
		os.killpg(os.getpgid(P_hidecursor.pid), signal.SIGKILL)
		P_hidecursor = None

@app.route('/tuyaOutlet/<func>/<path:name_or_obj>')
def tuyaOutlet(func, name_or_obj):
	try:
		rc_obj = eval(name_or_obj)
		rc_obj['func'] = eval(f'lambda t:t.{func}')
		return execRC(rc_obj)
	except:
		return traceback.format_exc()

@tool
@app.route('/execRC/<path:name_or_obj>')
def ExecRC(name_or_obj):
	"""Run RC (remote-control) codes

	Args:
		name_or_obj (str): the RC code

	Returns:
		str: response string or stack trace (upon error)
	"""
	try:
		return execRC(eval(name_or_obj))
	except:
		return traceback.format_exc()


# For OpenHomeKaraoke
def KTV(turn_on):
	global P_ext, P_hidecursor
	if turn_on:
		cpufreq_set(1)
		tv_name, input_id = list_get_args(KTV_SCREEN.split(':'), 2, [''])
		stop()
		if KTV_SPEAKER_ON:
			execRC(KTV_SPEAKER_ON)
		tv_on_if_off(tv_name, True)
		if input_id:
			tv_setInput(tv_name, input_id)
		set_audio_device(KTV_SPEAKER, 5)
		P_ext = subprocess.Popen(KTV_EXEC, shell=True, preexec_fn=os.setsid)
		P_ext.mode = 'KTV'
		if sys.platform=='linux' and P_hidecursor is None:
			P_hidecursor = subprocess.Popen('DISPLAY=:0 unclutter -idle 2', shell=True, preexec_fn=os.setsid)
	else:
		killMode()
		unset_audio_device(KTV_SPEAKER)
		cpufreq_set(0)
		if KTV_SPEAKER_OFF:
			execRC(KTV_SPEAKER_OFF)

# For Retro-gaming
def RetroGame(img=''):
	global P_ext
	if img:
		cpufreq_set(1)
		try:
			tv_name, input_id = list_get_args(GAME_SCREEN.split(':'), 2, [''])
			tv_on_if_off(tv_name, True)
			if input_id:
				tv_setInput(tv_name, input_id)
		except:
			pass
		P_ext = subprocess.Popen(['./bato-launch.sh', expand_path(img)], preexec_fn=os.setsid)
		P_ext.mode = 'RetroGame'
	else:
		killMode()
		P_ext = subprocess.Popen(['./bato-launch.sh', 'stop'], preexec_fn=os.setsid)
		cpufreq_set(0)

# Enter mode
@app.route('/Mode')
@app.route('/Mode/<mode>')
@app.route('/Mode/<mode>/<path:args>')
def Mode(mode='', args=''):
	global P_ext

	if P_ext != None:
		cur_mode = Try(lambda: P_ext.mode, '')
		if cur_mode == 'KTV':
			KTV(False)
		elif cur_mode == 'RetroGame':
			RetroGame(False)
		else:
			killMode()

	if mode == 'KTV':
		KTV(True)
	elif mode == 'RetroGame':
		RetroGame(args)
		
	return 'OK'

# For smartphone console
ip2qr = {}
@app.route('/QR')
def prepare_QR():
	global ip2qr
	if request.remote_addr not in ip2qr:
		qr = qrcode.QRCode(image_factory=qrcode.image.svg.SvgPathImage)
		qr.add_data(get_url_root(request)+'/mobile/'+request.remote_addr)
		qr.make()
		img = qr.make_image()
		ip2qr[request.remote_addr] = img.to_string(encoding='unicode')
	return ip2qr[request.remote_addr]

@app.route('/mobile/<ip_addr>')
def mobile(ip_addr):
	return render_template('yt-dlp.html', target=ip_addr)

def _download_and_play(mobile_ip, target_ip, action, song_url):
	target_ip = target_ip.split('?')[-1]
	enqueue, include_subtitles, high_quality, redownload = [bool(int(action)>>i&1) for i in range(4)]
	fn = download_video(song_url, include_subtitles, high_quality, redownload, mobile_ip)
	if enqueue and fn:
		tv_wscmd(target_ip, f'goto_file {fn[len(SHARED_PATH):]}')


@app.route('/download')
def download():
	threading.Thread(target=_download_and_play, args=[request.remote_addr]+unquote(request.full_path).split(' ', 2)).start()
	return 'Download started ...'


def get_default_browser_cookie():
	def_cookie_loc = defaultdict(lambda:'')
	def_cookie_loc['firefox'] = '$HOME/.mozilla/firefox/'
	def_cookie_loc['chrome'] = '$HOME/.config/google-chrome/'
	def_cookie_loc['chromium'] = '$HOME/.config/chromium/'
	try:
		default_browser = webbrowser.get().name.lower().split('-')[0]
	except:
		return ''
	ret = os.path.expandvars(def_cookie_loc[default_browser])
	return f'{default_browser}:{ret}' if ret else ''

@app.route('/fast_fwd/<tm>')
@app.route('/fast_fwd/<tv_name>/<tm>')
def fast_fwd(tm, tv_name='auto', op='+='):
	tm1 = zh2num(tm)
	tv_name = os.lastTVname if tv_name=='auto' else tv_name
	if tm1.endswith('%'):
		tv_wscmd(tv_name, f'v.currentTime{op}{float(tm1[:-1])*.01}*v.duration;')
	else:
		tv_wscmd(tv_name, f'v.currentTime{op}{hhmmss2sec(zh2time_hhmmss(tm1))}')
	return f'fast_forward({op}{tm}, {tv_name})'

@app.route('/fast_fwd2/<tm>')
@app.route('/fast_fwd2/<tv_name>/<tm>')
def fast_fwd2(tm, tv_name='auto'):
	return fast_fwd(tm, tv_name, '=')

# Large-vocabulary multilingual speech recognition
def lvmsr_voice_cmd(asr_str):
	for k, v in VOICE_CMD_FFWD_DCT.items():
		if asr_str.startswith(k):
			return fast_fwd(asr_str[len(k):], v, '=' if k.endswith('到') else ('+=' if '进' in k else '-='))
	return f'Not found {asr_str}'

@app.route('/voice_cmd/<path:hub_pfx>', methods=['POST'])
def voice_cmd(hub_pfx):
	global ASR_cloud_running, ASR_server_running
	hub_pfx = hub_pfx.rstrip('/')
	try:
		# save recorded audio file
		audio_file = save_post_file()
		assert audio_file

		# try cloud ASR
		if ASR_CLOUD_ENDP and not ASR_cloud_running:
			ASR_cloud_running = True
			asr_output = get_ASR_online(audio_file)
			ASR_cloud_running = False

		# try offline ASR if cloud ASR fails
		if type(asr_output)==str or not asr_output:
			if not M_ASR:
				return 'Offline ASR not enabled'
			if ASR_server_running:
				return 'Unfinished offline ASR'
			asr_output = get_ASR_offline(audio_file)

		LOG(f'ASR output: {asr_output}')
		asr_str = asr_output['text'].strip()

		# get cmd list and search and execute the match
		cmd_tbl = parseRC(get_http(hub_pfx+'/rc_load')[0])
		ii = findSong(asr_str, 'zh', [p[1] for p in cmd_tbl])
		if ii is None:
			return lvmsr_voice_cmd(asr_str)
		cmdID, cmdDesc, cmdExec = cmd_tbl[ii][:3]
		if '/play_spoken' in cmdExec and cmdExec[0]=="'" and cmdExec[-1]=="'":
			return f"EXEC ASR({cmdExec})"
		else:
			get_http(hub_pfx + '/rl_run?' + cmdID)
		return f'OK: {cmdDesc}'
	except:
		return traceback.format_exc()

def _chatGPT(args):
	global gpt_agent
	if args.pop('prompt', None):
		play_audio('voice/ok_what.mp3', block=True)
	while True:
		if not record_voice_until_sil():
			break
		q = recog_and_do('', '', '', (lambda t, *args, **kwargs: t), **args)
		if type(q) != dict or 'text' not in q:
			return
		play_audio('voice/ok_let_me_think.mp3', block=False)
		gpt_agent(q['text'])

@app.route('/GPTagent/<path:q>')
def GPTagent(q):
	run_thread(gpt_agent, q)
	return 'OK'

@app.route('/chatGPT')
def chatGPT():
	args = dict(request.args)
	args['url_root'] = get_url_root(request)
	run_thread(_chatGPT, args)
	return 'OK'

@app.route('/stopGPT')
def stopGPT():
	global gpt_agent
	gpt_agent.tool.stop()
	if g_last_speak_popen != None and g_last_speak_popen.poll()==None:
		os.killpg(g_last_speak_popen.pid, signal.SIGTERM)
		g_last_speak_popen = None

if __name__ == '__main__':
	parser = argparse.ArgumentParser(usage='$0 [options]', description='launch the smart home server',
			formatter_class=argparse.ArgumentDefaultsHelpFormatter)
	parser.add_argument('--port', '-p', type=int, default=8883, help='server port number')
	parser.add_argument('--ssl', '-ssl', help='server port number', action='store_true')
	parser.add_argument('--asr-models', '-am', default=[], help='ASR models to load, each in the form "backend:model_name:dtype", e.g., whisper:medium, faster_whisper:large-v3:int8, qwen:Qwen/Qwen3-ASR-1.7B, etc.', action='append')
	parser.add_argument('--no-console', '-nc', help='do not open console', action='store_true')
	parser.add_argument('--no-xauth', '-nx', help='do not xauth add magic key', action='store_true')
	parser.add_argument('--hide-subtitle', '-nosub', help='whether to hide subtitles', action='store_true')
	parser.add_argument('--browser-cookies', '-c', default = "auto",
		help = "YouTube downloader can use browser cookies from the specified path (see the --cookies-from-browser option of yt-dlp), it can also be auto (default): automatically determine based on OS; none: do not use any browser cookies",
	)

	opt = parser.parse_args()
	globals().update(vars(opt))

	subtitle = not hide_subtitle

	# Set browser cookies location for YouTube downloader
	if browser_cookies.lower() == 'none':
		cookies_opt = []
	elif browser_cookies.lower() == 'auto':
		path = get_default_browser_cookie()
		cookies_opt = ['--cookies-from-browser', path] if path else []
	else:
		cookies_opt = ['--cookies-from-browser', browser_cookies]

	M_ASR = [ASR(asr_model) for asr_model in asr_models]

	os.url_root = f'http://{get_local_IP()}:{port}'

	# Allow tmux/ssh session to display over HDMI output screen
	xauth_add()

	# Create ChatGPT agent
	from strands_tools import stop as agent_stop
	gpt_agent = Agent(
		model=load_GPT_model(),
		tools=[listen, speak, show_HTML, RUN, RUNCMD, runsys, tv_list, py_exec, py_eval, \
			run_python_script, get_http, send_hub_cmd, tv_on_if_off, tvVolume, _tvPlay, ExecRC, agent_stop],
		system_prompt=get_sys_prompt(),
	)

	if not ssl:
		threading.Thread(target=lambda:app.run(host='0.0.0.0', port=port+1, threaded = True, ssl_context=('cert.pem', 'key.pem'))).start()
	threading.Thread(target=lambda:app.run(host='0.0.0.0', port=port, threaded = True, ssl_context=('cert.pem', 'key.pem') if ssl else None)).start()

	if no_console:
		while True: time.sleep(999999999)

	try:
		import IPython
		IPython.embed()
	except:
		print('IPython not installed, starting basic console (lines starting with / are for eval, otherwise are for exec, exit/quit to exit):')
		while True:
			L = input()
			if L in ['exit', 'quit']:
				break
			try:
				print(eval(L[1:], globals(), globals())) if L.startswith('/') else exec(L, globals(), globals())
			except:
				traceback.print_exc()

	save_playstate(ip2tvdata)
	import os
	os._exit(0)
