#!/usr/bin/env python3
# -*- coding: utf-8 -*-

DEBUG_LOG = True

import traceback, argparse, math, requests, json, re, webbrowser
import os, sys, subprocess, random, time, threading, socket
import vlc, signal, qrcode, qrcode.image.svg
from collections import *
from io import StringIO
from flask import Flask, request, send_from_directory, render_template, send_file
from flask_sock import Sock
from unidecode import unidecode
from pydub import AudioSegment as AudSeg
from gtts import gTTS
from lingua import LanguageDetectorBuilder
from langcodes import Language as LC

from lib.DefaultRevisionDict import *
from lib.gTranslateTTS import gTransTTS
from lib.settings import *
from lib.NLP import *
from device_config import *
SHARED_PATH = os.path.expanduser(SHARED_PATH).rstrip('/')+'/'

_regex_ip = re.compile("^(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\\.(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\\.(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\\.(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$")
isIP = _regex_ip.match

app = Flask(__name__, template_folder='template')
app.url_map.strict_slashes = False
app.config['TEMPLATES_AUTO_RELOAD'] = True	##DEBUG
sock = Sock(app)
get_volume = lambda: RUN("amixer get Master | awk -F'[][]' '/Left:/ { print $2 }'").rstrip('%\n')
ping = lambda ip: os.system(f'ping -W 1 -c 1 {ip}')==0
mrl2path = lambda t: unquote(t).replace('file://', '').strip() if t.startswith('file://') else (t.strip() if t.startswith('/') else '')
is_json_lst = lambda s: s.startswith('["') and s.endswith('"]')
load_m3u = lambda fn: [i for L in open(fn).readlines() for i in [mrl2path(L)] if i]
get_url_root = lambda r: r.url_root.rstrip('/') if r.url_root.count(':')>=2 else r.url_root.rstrip('/')+f':{r.server[1]}'

inst = vlc.Instance()
event = vlc.EventType()
ev_voice = threading.Event()
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
LOG = lambda s: print(f'LOG: {s}') if DEBUG_LOG else None


def Eval(cmd, default=None):
	try:
		return eval(cmd, globals(), globals())
	except:
		return default

def RUN(cmd, shell=True, timeout=3, **kwargs):
	ret = subprocess.check_output(cmd, shell=shell, timeout=timeout, **kwargs)
	return ret if type(ret)==str else ret.decode()

def _runsys(cmd, event):
	os.system(cmd)
	if event!=None:
		event.set()

def RUNSYS(cmd, event=None):
	threading.Thread(target=_runsys, args=(cmd, event)).start()

def prune_dict(dct, limit=10):
	while len(dct)>limit:
		dct.pop(list(dct.keys())[0])
	return dct

def get_local_IP():
	s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
	s.connect(('8.8.8.8', 1))
	return s.getsockname()[0]

local_IP = get_local_IP()
load_config = lambda: Try(lambda: InfiniteDefaultRevisionDict().from_json(open(DEFAULT_CONFIG_FILE)), InfiniteDefaultRevisionDict())
save_config = lambda obj: exec(f"with open('{DEFAULT_CONFIG_FILE}','w') as fp: obj.to_json(fp, indent=1)")
get_base_url = lambda: f'{"https" if ssl else "http"}://{local_IP}:{port}'

# Detect language, invoke Google-translate TTS and play the speech audio
def prepare_TTS(txt, fn=DEFAULT_SPEECH_FILE):
	lang_id = Try(lambda: lang2id[lang_detector.detect_language_of(txt)], 'km')
	LOG(f'TTS txt="{txt}" lang_id={lang_id}')
	try:
		tts = gTTS(txt, lang=lang_id)
		tts.save(fn+'.mp3')
	except:
		gTransTTS(txt, lang_id, fn+'.mp3')
	os.system(f'ffmpeg -y -i "{fn}.mp3" -af "adelay=300ms:all=true,volume=2" "{fn}"')
	return lang_id, txt

def play_TTS(txt, tv_name=None):
	txts = txt if type(txt)==list else [txt]
	for seg in txts:
		prepare_TTS(seg)
		play_audio(DEFAULT_SPEECH_FILE, True, tv_name)

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

@app.route('/files/<path:filename>')
def get_file(filename):
	return send_from_directory(SHARED_PATH, filename.strip('/'), conditional=True)

@app.route('/favicon.ico')
def get_favicon():
	return send_file('template/favicon.ico')

@app.route('/voice')
@app.route('/voice/<path:fn>')
def get_voice(fn=''):
	return send_from_directory('./voice', fn, conditional=True) if fn else send_file(DEFAULT_SPEECH_FILE, conditional=True)

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

def _play(tm_info, filename=''):
	global inst, player, playlist, filelist, mplayer, isVideo
	filelist, ii, tm_sec, randomize = load_playable(None, tm_info, filename)

	stop()
	playlist = inst.media_list_new(filelist)
	if player == None:
		player = inst.media_list_player_new()
	player.set_media_list(playlist)
	isVideo = bool([fn for fn in filelist if isVideoFile(fn)])

	mplayer = player.get_media_player()
	mplayer.event_manager().event_attach(event.MediaPlayerOpening, on_media_opening)
	set_audio_device(MP4_SPEAKER if isVideo else MP3_SPEAKER)
	player.set_playback_mode(vlc.PlaybackMode.loop)
	player.play_item_at_index(ii)
	threading.Timer(1, lambda:mplayer.audio_set_volume(100)).start()
	if tm_sec>0:
		threading.Timer(1000, lambda:player.set_position(tm_sec)).start()

@app.route('/play/<tm_info>/<path:filename>')
def play(tm_info, filename=''):
	threading.Thread(target=_play, args=(tm_info, filename)).start()
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

@app.route('/rewind')
def rewind():
	global player
	try:
		player.set_position(0)
		player.set_pause(False)
	except Exception as e:
		return str(e)
	return 'OK'

def get_bak_fn(fn):
	dirname = os.path.dirname(fn)
	Try(lambda: os.makedirs(dirname+'/.orig'))
	return f'{dirname}/.orig/{os.path.basename(fn)}'

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
		sid = filelist.index(mrl2path(mrl))
		player.stop()
	fn = fn if sid<0 else mrl2path(filelist[sid])
	assert os.path.isfile(fn)
	play_audio('voice/processing.mp3')
	audio = AudSeg.from_file(fn)
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
	threading.Timer(0, lambda: _normalize_vol(song)).start()
	return 'OK'

@app.route('/playFrom/<name>')
def playFrom(name='', lang=None):
	global player
	try:
		ii = name if type(name)==int else findSong(name, lang=lang)
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


# For LG TV
ip2websock = {}
# ip2tvdata: {'IP':{'playlist':[full filenames], 'cur_ii': current_index, 'shuffled': bool (save play position if false), 
# 	'markers':[(key1,val1),...], 'T2Slang':'', 'T2Stext':'', 'S2Tlang':'', 'S2Ttext':''}}
ip2tvdata = load_config()
tv2lginfo = Try(lambda: json.load(open(os.path.expanduser(LG_TV_CONFIG_FILE))), {})

# Set T2S/S2T info
def setInfo(tv_name, text, lang, prefix, match=None):
	langName = LC.get(lang).display_name('zh')
	ip = tv2lginfo[tv_name]['ip'] if tv_name in tv2lginfo else tv_name
	ip2tvdata[ip].update({f'{prefix}_lang': langName, f'{prefix}_text': text}|({} if match==None else {f'{prefix}_match': match}))
	if ip:
		ip2websock[ip].send(f'{prefix}lang.textContent="{langName}";{prefix}text.textContent="{text}";'+(f'{prefix}match.textContent="{match}"' if match!=None else ''))

def _report_title(tv_name):
	with VoicePrompt(tv_name) as context:
		ev = play_audio('voice/cur_song_title.mp3', False, tv_name)
		if tv_name:
			data = ip2tvdata[tv2lginfo[tv_name]['ip'] if tv_name in tv2lginfo else tv_name]
			langId, txt = prepare_TTS(filepath2songtitle(data['playlist'][data['cur_ii']]))
			setInfo(tv_name, txt, langId, 'T2S')
		else:
			prepare_TTS(filepath2songtitle(mrl2path(mplayer.get_media().get_mrl())))
		ev.wait()
		play_audio(DEFAULT_SPEECH_FILE, True, tv_name)

@app.route('/report_title')
@app.route('/report_title/<tv_name>')
def report_title(tv_name=None):
	threading.Thread(target=_report_title, args=(tv_name,)).start()
	return 'OK'

def send_wol(mac, ip='255.255.255.255'):
	try:
		if len(mac) == 17:
			mac = mac.replace(mac[2], "")
		elif len(mac) != 12:
			return "Incorrect MAC address format"
		s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
		s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
		nsent = s.sendto(bytes.fromhex("F"*12 + mac*16), (ip, 9))
		s.close()
		return True
	except Exception:
		traceback.print_exc()
		return False

@app.route('/tv_on/<tv_name>')
def tv_on_if_off(tv_name, wait_ready=False):
	tvinfo = tv2lginfo[tv_name]
	if not ping(tvinfo['ip']):
		send_wol(tvinfo['mac'])
		if wait_ready:
			while os.system(f'{LG_TV_BIN} --name {tv_name} audioVolume')!=0:
				time.sleep(1)
	return 'OK'

@app.route('/tv/<name>/<cmd>')
def tv(name='', cmd=''):
	for i in range(3):
		try:
			return RUN(f'{LG_TV_BIN} --name {name} {cmd}')
		except:
			pass
	return 'Failed after trying 3 times!'

@app.route('/tvVolume/<name>/<vol>')
def tvVolume(name='', vol=''):
	try:
		value = int(vol)
		if not vol[0].isdigit():
			ret = RUN(f'{LG_TV_BIN} --name {name} audioVolume')
			L = ret[ret.find('"volume":'):]
			value += int(L[L.find(' '):L.find(',')])
		return RUN(f'{LG_TV_BIN} --name {name} setVolume {value}')
	except Exception as e:
		return str(e)

@sock.route('/ws_init')
def ws_init(sock):
	global ip2websock
	key = sock.sock.getpeername()[0]
	ip2websock[key] = sock
	while sock.connected:
		try:
			cmd = sock.receive()
			tv_wscmd(key, cmd)
		except:
			traceback.print_exc()
	ip2websock.pop(key)

def load_playable(ip, tm_info, filename):
	fullname, n = SHARED_PATH+str(filename), 1
	tm_sec, ii, randomize = ([int(float(i)) for i in tm_info.split()]+[0,0])[:3]
	tvd = ip2tvdata[ip]
	if filename == None:
		lst = tvd['playlist']
	elif is_json_lst(filename):
		lst = json.loads(filename)
	elif fullname.lower().endswith('.m3u'):
		lst = load_m3u(fullname)
	elif os.path.isdir(fullname):
		lst = ls_media_files(fullname)
	else:
		lst, randomize = ls_media_files(os.path.dirname(fullname)), 0
		ii = lst.index(fullname)
	if ii<0 or tm_sec<0:
		ii, tm_sec = tvd['markers'].get(json.dumps(lst), [0,0])
	if randomize: random.shuffle(lst)
	lst = [(s if s.startswith(SHARED_PATH) else SHARED_PATH+s) for s in lst]
	tvd.update({'playlist': lst, 'cur_ii': ii, 'shuffled': randomize})
	return lst, ii, tm_sec, randomize

@app.route('/webPlay/<tm_info>')
@app.route('/webPlay/<tm_info>/<path:filename>')
def webPlay(tm_info, filename=None):
	lst, ii, tm_sec, randomize = load_playable(request.remote_addr, tm_info, filename)
	tvd = ip2tvdata[request.remote_addr]
	return render_template('video.html',
		listname=''.join(lst[0].split('/')[-2:-1]) or '播放列表',
		playlist=[i.split('/')[-1] for i in lst],
		file_path=f'/files/{lst[ii][len(SHARED_PATH):]}#t={tm_sec}',
		**{n:tvd.get(n,'') for n in ['T2S_text', 'T2S_lang', 'S2T_text', 'S2T_lang', 'S2T_match', 'cur_ii']})

@app.route('/tv_runjs')
def tv_runjs():
	name, cmd = unquote(request.query_string.decode()).split('/', 1)
	ip2websock[tv2lginfo[name]['ip'] if name in tv2lginfo else name].send(cmd)
	return 'OK'

def _tvPlay(name, listfilename, url_root):
	tv_name, tm_info = (name.split(' ',1)+[0])[:2]
	if is_json_lst(listfilename):
		tvd = ip2tvdata[tv2lginfo[tv_name]['ip'] if tv_name in tv2lginfo else tv_name]
		tvd['playlist'] = json.loads(listfilename)
		listfilename = ''
	if tv_name in tv2lginfo:
		tv_on_if_off(tv_name, True)
		return tv(tv_name, f'openBrowserAt "{url_root}/webPlay/{tm_info}/{listfilename}"')
	else:
		ws = ip2websock[tv2lginfo[tv_name]['ip'] if tv_name in tv2lginfo else tv_name]
		return ws.send(f'seturl("{url_root}/webPlay/{tm_info}/{listfilename}")') or 'OK'

@app.route('/tvPlay/<name>/<path:listfilename>')
def tvPlay(name, listfilename):
	threading.Thread(target=_tvPlay, args=(name, listfilename, get_url_root(request))).start()
	return 'OK'

def mark(name, tms):
	tvd = ip2tvdata[tv2lginfo[name]['ip'] if name in tv2lginfo else name]
	if tvd['shuffled']:
		return 'Ignored'
	tvd['markers'].update({json.dumps(tvd['playlist']): [tvd['cur_ii'], tms]})
	prune_dict(tvd['markers'])
	save_config(prune_dict(ip2tvdata))

@app.route('/tv_wscmd/<name>/<path:cmd>')
def tv_wscmd(name, cmd):
	LOG(name+' : '+cmd)
	try:
		ip = tv2lginfo[name]['ip'] if name in tv2lginfo else name
		ws = ip2websock[ip]
		tvd = ip2tvdata[ip]
		if cmd == 'pause':
			ws.send('v.pause()')
		elif cmd == 'resume':
			ws.send('v.play()')
		elif cmd == 'rewind':
			ws.send('v.currentTime=0')
		elif cmd == 'audio_ended':
			ev_voice.set()
		elif cmd == 'hideQR':
			ws.send('QRcontainer.style.opacity=0;')
		elif cmd == 'play_spoken_inlst':
			play_spoken_song(name)
		elif cmd == 'play_spoken_indir':
			play_spoken_drama(name)
		elif cmd == 'report_title':
			report_title(name)
		elif cmd.startswith('mark '):
			mark(name, float(cmd.split()[1]))
			tv(name, 'screenOn')
		elif cmd.startswith('lsdir '):
			full_dir = SHARED_PATH+cmd.split(' ',1)[1]+'/'
			lst = [(p+'/' if os.path.isdir(full_dir+p) else p) for p in sorted(os.listdir(full_dir)) if not p.startswith('.')]
			ws.send(json.dumps(lst))
		else:
			if cmd in ['next', 'prev']:
				tvd['cur_ii'] = (tvd['cur_ii']+(1 if cmd=='next' else -1))%len(tvd['playlist'])
			elif cmd.startswith('goto_idx '):
				tvd['cur_ii'] = int(cmd.split()[1])
			elif cmd.startswith('goto_file '):
				fn = cmd.split(' ',1)[1].strip('/')
				flist = ls_media_files(SHARED_PATH+os.path.dirname(fn))
				tvd['playlist'] = flist
				tvd['cur_ii'] = [ii for ii,fulln in enumerate(flist) if fulln.endswith('/'+fn)][0]
				ws.send(json.dumps([s.split('/')[-1] for s in flist]))
			else:
				ws.send(cmd)
				return 'OK'
			fn = tvd['playlist'][tvd['cur_ii']]
			ws.send(f'setvsrc("/files/{fn[len(SHARED_PATH):]}",{tvd["cur_ii"]})')
		return 'OK'
	except Exception as e:
		return str(e)


# For audio
list_sinks = lambda: RUN('pactl list sinks short')
list_sources = lambda: RUN('pactl list sources short')

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
				time.sleep(1)
			out = [L.split() for L in list_sinks().splitlines()]
			res = [its[0] for its in out if patn in its[1]]
			if res:
				return os.system(f'pactl set-default-sink {res[0]}')==0
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

def play_audio(fn, block=False, tv_name=None):
	ev_voice.clear()
	if tv_name:
		tv_wscmd(tv_name, f'play_audio("/{f"voice?{random.randint(0,999999)}" if fn==DEFAULT_SPEECH_FILE else fn}",true)')
	else:
		RUNSYS(f'mplayer -really-quiet -noconsolecontrols {fn}', ev_voice)
	if block: ev_voice.wait()
	return ev_voice

def record_audio(tm_sec=5, file_path=DEFAULT_RECORDING_FILE):
	os.system(f'ffmpeg -y -f pulse -i {get_recorder(MIC_RECORDER)} -ac 1 -t {tm_sec} {file_path}')


# For ASR server
def get_ASR_offline():
	try:
		CANCEL_FLAG = False
		obj = asr_model.transcribe(os.path.expanduser(asr_input), cancel_func=cancel_requested)
		return obj
	except Exception as e:
		traceback.print_exc()
		return str(e)

def get_ASR_online():
	try:
		with open(os.path.expanduser(asr_input), 'rb') as f:
			r = requests.post(ASR_CLOUD, files={'file': f}, timeout=5)
		return json.loads(r.text) if r.status_code==200 else {}
	except Exception as e:
		traceback.print_exc()
		return str(e)

class VoicePrompt:
	def __init__(self, tv_name=None):
		self.cur_sta = self.cur_vol = None
		self.tv_name = tv_name

	def __enter__(self):	# preserve environment
		global player
		if self.tv_name:
			tv_wscmd(self.tv_name, 'pause')
		elif player!=None:
			self.cur_sta = player.is_playing()
			if self.cur_sta:
				player.set_pause(True)
			self.cur_vol = get_volume()
		return self

	def restore(self):
		if self.tv_name:
			tv_wscmd(self.tv_name, 'resume')
		else:
			if self.cur_vol != None:
				set_volume(self.cur_vol)
			if self.cur_sta:
				player.set_pause(False)
		self.cur_vol = self.cur_sta = None
		return True

	def __exit__(self, exc_type, exc_value, traceback):	# restore environment
		return self.restore()


# This function might take very long time, must be run in a separate thread
def recog_and_play(voice, tv_name, path_name, handler, url_root):
	global player, asr_model, ASR_cloud_running, ASR_server_running

	with VoicePrompt(tv_name) as context:
		# record speech
		if voice:
			set_volume(VOICE_VOL)
			play_audio(voice, True, tv_name)
			record_audio()

		# try cloud ASR
		if ASR_CLOUD and not ASR_cloud_running:
			ASR_cloud_running = True
			asr_output = get_ASR_online()
			ASR_cloud_running = False

		# try offline ASR if cloud ASR fails
		if type(asr_output)==str or not asr_output:
			if asr_model == None:
				play_audio('voice/offline_asr_not_available.mp3', True, tv_name)
				return
			if ASR_server_running:
				play_audio('voice/unfinished_offline_asr.mp3', True, tv_name)
				return
			play_audio('voice/wait_for_asr.mp3', False, tv_name)

			context.restore()
			asr_output = get_ASR_offline()

		print(f'ASR result: {asr_output}', file=sys.stderr)
		if asr_output=={} or type(asr_output)==str:
			play_audio('voice/asr_error.mp3', True, tv_name)
		elif not asr_output['text']:
			play_audio('voice/asr_fail.mp3', True, tv_name)
		else:
			handler(asr_output, tv_name, path_name, url_root.rstrip('/'))


def _play_last(name=None):
	tvd = ip2tvdata[tv2lginfo[name]['ip'] if name in tv2lginfo else name]
	pl = tvd.get('playlist', json.loads(list(tvd['markers'].items())[-1][0]))
	ii, tms = tvd['markers'].get(json.dumps(pl), [tvd.get('cur_ii', 0), 0])
	if name in tv2lginfo:
		tv_on_if_off(name, True)
	tvPlay(f'{name} -1', json.dumps(pl))

@app.route('/play_last')
@app.route('/play_last/<tv_name>')
def play_last(tv_name=None):
	threading.Thread(target=_play_last, args=(tv_name,)).start()
	return 'OK'

def handle_ASR_indir(asr_out, tv_name, rel_path, url_root):
	res = findMedia(asr_out['text'], asr_out['language'], base_path=SHARED_PATH+rel_path)
	setInfo(tv_name, asr_out["text"], asr_out['language'], 'S2T', '' if res==None else \
		(ls_media_files(res[0])[res[1]][len(SHARED_PATH):] if type(res)==tuple else res[len(SHARED_PATH):]))
	if res == None:
		play_audio('voice/asr_not_found_drama.mp3' if rel_path else 'voice/asr_not_found_file.mp3', True, tv_name)
	else:
		if type(res)==tuple:
			res, epi = res if type(res)==tuple else (res, None)
			short_path = res[len(SHARED_PATH):]
			play_audio('voice/asr_found_drama.mp3' if rel_path else 'voice/asr_found_file.mp3', True, tv_name)
			if tv_name==None:
				_play(f'0 {epi}', short_path)
			else:
				_tvPlay(f'{tv_name} 0 {epi}', short_path, url_root)
		else:
			short_path = res[len(SHARED_PATH):]
			play_audio(('voice/asr_found_drama.mp3' if os.path.isdir(res) else 'voice/asr_found_movie.mp3')
				if rel_path else 'voice/asr_found_file.mp3', True, tv_name)
			if tv_name == None:
				_play('-1' if os.path.isdir(res) else '0', short_path)
			else:
				_tvPlay(tv_name+(' -1' if os.path.isdir(res) else ' 0'), short_path, url_root)

def handle_ASR_inlst(asr_out, tv_name, lst_filename, url_root):
	lst = load_m3u(SHARED_PATH+lst_filename) if lst_filename else ip2tvdata[tv2lginfo[tv_name]['ip'] if tv_name else None]['playlist']
	ii = findSong(asr_out['text'], asr_out['language'], lst)
	setInfo(tv_name, asr_out["text"], asr_out['language'], 'S2T', '' if ii==None else lst[ii][len(SHARED_PATH):])
	if ii == None:
		play_audio('voice/asr_not_found.mp3', True, tv_name)
	else:
		play_audio('voice/asr_found.mp3', True, tv_name)
		if lst_filename:
			_tvPlay(f'{tv_name} 0 {ii}', json.dumps(lst)) if tv_name else play(f'0 {ii}', json.dumps(lst), url_root)
		else:
			playFrom(ii) if tv_name==None else tv_wscmd(tv_name, f'goto_idx {ii}')

@app.route('/play_spoken_indir')
@app.route('/play_spoken_indir/<tv_name>')
@app.route('/play_spoken_indir/<tv_name>/<path:rel_path>')
def play_spoken_drama(tv_name=None, rel_path=''):
	threading.Thread(target=recog_and_play, args=('voice/speak_drama.mp3', None if tv_name=='None' else tv_name,
		rel_path, handle_ASR_indir, get_url_root(request))).start()
	return 'OK'

@app.route('/play_spoken_inlst')
@app.route('/play_spoken_inlst/<tv_name>')
@app.route('/play_spoken_inlst/<tv_name>/<path:lst_filename>')
def play_spoken_song(tv_name=None, lst_filename=''):
	threading.Thread(target=recog_and_play, args=('voice/speak_song.mp3', None if tv_name=='None' else tv_name, 
		lst_filename, handle_ASR_inlst, get_url_root(request))).start()
	return 'OK'

@app.route('/play_recorded', methods=['POST'])
def play_recorded():
	with open(f'{TMP_DIR}/rec.webm', 'wb') as fp:
		fp.write(request.data)
	AudSeg.from_file(f'{TMP_DIR}/rec.webm', format='webm').export(DEFAULT_RECORDING_FILE, 'ipod')
	threading.Thread(target=recog_and_play, args=('', request.remote_addr, '', handle_ASR_indir, get_url_root(request))).start()
	return 'OK'

# For Ecovacs
@app.route('/ecovacs', defaults={'name': '', 'cmd':''})
@app.route('/ecovacs/<name>/<cmd>')
def ecovacs(name='', cmd=''):
	return RUN(f'./ecovacs-cmd.sh {name} {cmd} &')


# For pikaraoke
@app.route('/KTV/<cmd>')
def KTV(cmd):
	global P_ktv
	if cmd=='on':
		stop()
		tv_on_if_off(KTV_SCREEN, True)
		set_audio_device(KTV_SPEAKER, 5)
		P_ktv = subprocess.Popen(['~/projects/pikaraoke/run-cloud.sh'], shell=True, preexec_fn=os.setsid)
	elif cmd=='off':
		os.killpg(os.getpgid(P_ktv.pid), signal.SIGKILL)
		unset_audio_device(KTV_SPEAKER)
	return 'OK'


# For smartphone console
qr_str = ''
@app.route('/QR')
def prepare_QR():
	global qr_str
	if not qr_str:
		qr = qrcode.QRCode(image_factory=qrcode.image.svg.SvgPathImage)
		qr.add_data(get_url_root(request)+'/mobile/'+request.remote_addr)
		qr.make()
		img = qr.make_image()
		qr_str = img.to_string(encoding='unicode')
	return qr_str

@app.route('/mobile/<ip_addr>')
def mobile(ip_addr):
	return render_template('yt-dlp.html', target=ip_addr)

def _download_and_play(target_ip, action, song_url):
	target_ip = target_ip.split('?')[-1]
	enqueue, include_subtitles, high_quality, redownload = [bool(int(action)>>i&1) for i in range(4)]
	fn = download_video(song_url, include_subtitles, high_quality, redownload)
	if enqueue and fn:
		tv_wscmd(target_ip, f'goto_file {fn[len(SHARED_PATH):]}')

@app.route('/download')
def download():
	threading.Thread(target=_download_and_play, args=unquote(request.full_path).split(' ', 2)).start()
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


if __name__ == '__main__':
	parser = argparse.ArgumentParser(usage='$0 [options]', description='launch the smart home server',
			formatter_class=argparse.ArgumentDefaultsHelpFormatter)
	parser.add_argument('--port', '-p', type=int, default=8883, help='server port number')
	parser.add_argument('--ssl', '-ssl', help='server port number', action='store_true')
	parser.add_argument('--asr', '-a', help='host ASR server', action='store_true')
	parser.add_argument('--asr-model', '-am', default='base', help='ASR model to load')
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

	if asr:
		import whisper
		asr_model = whisper.load_model(asr_model)
		print('Offline ASR model loaded successfully ...', file=sys.stderr)
	else:
		asr_model = None

	if not ssl:
		threading.Thread(target=lambda:app.run(host='0.0.0.0', port=port+1, threaded = True, ssl_context=('cert.pem', 'key.pem'))).start()
	app.run(host='0.0.0.0', port=port, threaded = True, ssl_context=('cert.pem', 'key.pem') if ssl else None)

