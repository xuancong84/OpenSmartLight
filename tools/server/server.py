#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, sys, traceback, argparse, math, requests, json, re, webbrowser
import subprocess, random, time, threading, socket
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

inst = vlc.Instance()
event = vlc.EventType()
ev_voice = threading.Event()
asr_model = None
asr_input = DEFAULT_S2T_SND_FILE
player = None
playlist = None
mplayer = None
filelist = []
P_ktv = None
isFirst = True
isVideo = None
subtitle = True
last_get_file_ip = ''
CANCEL_FLAG = False
isJustAfterBoot = True if sys.platform=='darwin' else float(open('/proc/uptime').read().split()[0])<120
random.seed(time.time())
ASR_server_running = ASR_cloud_running = False
lang_detector = LanguageDetectorBuilder.from_languages(*lang2id.keys()).build()

def get_local_IP():
	s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
	s.connect(('8.8.8.8', 1))
	return s.getsockname()[0]

local_IP = get_local_IP()
load_playstate = lambda: Try(lambda: InfiniteDefaultRevisionDict().from_json(Open(PLAYSTATE_FILE)), InfiniteDefaultRevisionDict())
def save_playstate(obj):
	with Open(PLAYSTATE_FILE, 'wt') as fp:
		obj.to_json(fp, indent=1)
get_base_url = lambda: f'{"https" if ssl else "http"}://{local_IP}:{port}'

ip2websock, ip2ydsock = {}, {}
os.ip2ydsock = ip2ydsock
# ip2tvdata: {'IP':{'playlist':[full filenames], 'cur_ii': current_index, 'shuffled': bool (save play position if false), 
# 	'markers':[(key1,val1),...], 'T2Slang':'', 'T2Stext':'', 'S2Tlang':'', 'S2Ttext':''}}
ip2tvdata = load_playstate()
tv2lginfo = Try(lambda: json.load(Open(LG_TV_CONFIG_FILE)), {})
get_tv_ip = lambda t: tv2lginfo[t]['ip'] if t in tv2lginfo else t
get_tv_data = lambda t: ip2tvdata[tv2lginfo[t]['ip'] if t in tv2lginfo else t]

# Detect language, invoke Google-translate TTS and play the speech audio
def prepare_TTS(txt, fn=DEFAULT_T2S_SND_FILE):
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
		play_audio(DEFAULT_T2S_SND_FILE, True, tv_name)

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

@app.route('/py_exec/<path:cmd>')
def py_exec(cmd):
	try:
		exec(cmd, globals(), globals())
		return "OK"
	except Exception as e:
		traceback.print_exc()
		return str(e)

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

@app.route('/get_http/<path:url>')
def get_http(url):
	res = requests.get(url if url.startswith('http://') else f'http://{url}')
	return res.text, res.status_code

@app.route('/voice')
@app.route('/voice/<path:fn>')
def get_voice(fn=''):
	return send_from_directory('./voice', fn, conditional=True) if fn else send_file(DEFAULT_T2S_SND_FILE, conditional=True)

@app.route('/subtt/<path:fn>')
def subtt(fn='0.vtt'):
	return send_from_directory(f'{TMP_DIR}/.subtitles/{request.remote_addr}/', fn, conditional=True)

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

def get_bak_fn(fn):
	dirname = os.path.dirname(fn)
	Try(lambda: os.makedirs(dirname+'/.orig'))
	return f'{dirname}/.orig/{os.path.basename(fn)}'

def norm_song_volume(fn):
	audio = AudSeg.from_file(fn)
	if isVideoFile(fn):
		if not os.path.exists(get_bak_fn(fn+'.m4a')):
			audio.export(get_bak_fn(fn+'.m4a'), format='ipod')
		audio += (STD_VOL_DBFS - audio.dBFS)
		audio.export(fn+'.m4a', format='ipod')
		os.system(f'ffmpeg -y -i {fn} -i {fn}.m4a -c copy -map 0 -map -0:a -map 1:a {fn}.tmp.mp4')
		os.system('sync')
		os.rename(f'{fn}.tmp.mp4', fn)
		os.system('sync')
		os.remove(fn+'.m4a')
	else:
		if not os.path.exists(get_bak_fn(fn+'.m4a')):
			os.rename(fn, get_bak_fn(fn+'.m4a'))
		audio += (STD_VOL_DBFS - audio.dBFS)
		audio.export(fn, format=('mp3' if fn.lower().endswith('.mp3') else 'ipod'))

def _normalize_vol(song):
	global player, last_get_file_ip
	if song:
		fn = os.path.expanduser(song if song.startswith('~') else (SHARED_PATH+'/'+song))
		norm_song_volume(fn)
	elif player is not None:
		mrl = mplayer.get_media().get_mrl()
		cur_ii = filelist.index(mrl2path(mrl))
		if cur_ii<0: return
		fn = mrl2path(filelist[cur_ii])
		if not os.path.isfile(fn): return
		player.stop()
		play_audio('voice/processing.mp3')
		norm_song_volume(fn)
		player.play_item_at_index(cur_ii)
	elif last_get_file_ip:
		dev_ip = last_get_file_ip
		tvd = ip2tvdata[dev_ip]
		playlist, cur_ii = tvd['playlist'], tvd['cur_ii']
		tv_wscmd(dev_ip, 'pause')
		play_audio('voice/processing.mp3', False, dev_ip)
		norm_song_volume(playlist[cur_ii])
		tv_wscmd(dev_ip, f'goto_idx {cur_ii}')

@app.route('/normalize_vol')
@app.route('/normalize_vol/<path:song>')
def normalize_vol(song=''):
	threading.Timer(0, lambda: _normalize_vol(song)).start()
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

loopModes = [vlc.PlaybackMode.repeat, vlc.PlaybackMode.loop, vlc.PlaybackMode.default]
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
	except Exception as e:
		ret = str(e)
	player = None
	return ret

@app.route('/connectble/<device>')
def connectble(dev_mac):
	ret = os.system(f'bluetoothctl trust {dev_mac}' if sys.platform=='linux' else f'blueutil --trust {dev_mac}')
	ret |= os.system(f'bluetoothctl pair {dev_mac}' if sys.platform=='linux' else f'blueutil --pair {dev_mac}')
	ret |= os.system(f'bluetoothctl connect {dev_mac}' if sys.platform=='linux' else f'blueutil --connect {dev_mac}')
	return str(ret)

@app.route('/disconnectble/<device>')
def disconnectble(dev_mac):
	ret = os.system(f'bluetoothctl disconnect {dev_mac}' if sys.platform=='linux' else f'blueutil --disconnect {dev_mac}')
	# ret |= os.system(f'bluetoothctl remove {dev_mac}' if sys.platform=='linux' else f'blueutil --remove {dev_mac}')
	return str(ret)

@app.route('/volume/<cmd>')
def set_volume(cmd=None, tv_name=None):
	if tv_name != None:
		return tvVolume(name=tv_name, vol=cmd)
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


### For LG TV
# Set T2S/S2T info
def setInfo(tv_name, text, lang, prefix, match=None):
	langName = LC.get(lang).display_name('zh')
	ip = get_tv_ip(tv_name)
	ip2tvdata[ip].update({f'{prefix}_lang': langName, f'{prefix}_text': text}|({} if match==None else {f'{prefix}_match': match}))
	if ip:
		ip2websock[ip].send(f'{prefix}lang.textContent="{langName}";{prefix}text.textContent="{text}";'+(f'{prefix}match.textContent="{match}"' if match!=None else ''))

def _report_title(tv_name):
	with VoicePrompt(tv_name) as context:
		ev = play_audio('voice/cur_song_title.mp3', False, tv_name)
		if tv_name:
			data = get_tv_data(tv_name)
			langId, txt = prepare_TTS(filepath2songtitle(data['playlist'][data['cur_ii']]))
			setInfo(tv_name, txt, langId, 'T2S')
		else:
			prepare_TTS(filepath2songtitle(mrl2path(mplayer.get_media().get_mrl())))
		ev.wait()
		play_audio(DEFAULT_T2S_SND_FILE, True, tv_name)

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

@app.route('/tv_setInput/<tv_name>')
def tv_setInput(tv_name, input_id):
	tv_on_if_off(tv_name, wait_ready=True)
	os.system(f'{LG_TV_BIN} --name {tv_name} setInput {input_id}')
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
		vol = str(vol)
		value = int(vol)
		if not vol[0].isdigit():
			ret = RUN(f'{LG_TV_BIN} --name {name} audioVolume')
			L = ret[ret.find('"volume":'):]
			value += int(L[L.find(' '):L.find(',')])
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
	global ip2websock
	key = sock.sock.getpeername()[0]
	ip2websock[key] = sock
	while sock.connected:
		try:
			cmd = sock.receive()
			tv_wscmd(key, cmd)
		except:
			print(f'Websock: {key} disconnected', file=sys.stderr)
			# traceback.print_exc()
	ip2websock.pop(key)

@sock.route('/yd_init')
def yd_init(sock):
	global ip2ydsock
	key = sock.sock.getpeername()[0]
	ip2ydsock[key] = sock
	while sock.connected:
		try:
			cmd = sock.receive()
		except:
			print(f'Websock: {key} disconnected', file=sys.stderr)
			# traceback.print_exc()
	ip2ydsock.pop(key)

def load_playable(ip, tm_info, filename):
	fullname = filename if type(filename)==str and filename.startswith(SHARED_PATH) else (SHARED_PATH+str(filename))
	tm_sec, ii, randomize = ([int(float(i)) for i in tm_info.split()]+[0,0])[:3]
	tvd = ip2tvdata[ip]
	if not filename:
		lst = tvd['playlist']
	elif is_json_lst(filename):
		lst = json.loads(filename)
	elif fullname.lower().endswith('.m3u'):
		lst = load_m3u(fullname)
	elif os.path.isdir(fullname):
		lst = ls_media_files(fullname)
	elif os.path.isfile(fullname):
		lst, randomize = ls_media_files(os.path.dirname(fullname)), 0
		ii = lst.index(fullname)
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
		listname=Try(lambda:''.join(lst[0].split('/')[-2:-1]), '') or '播放列表',
		playlist=[i.split('/')[-1] for i in lst],
		file_path=f'/files/{lst[ii][len(SHARED_PATH):]}#t={tm_sec}' if lst else '',
		**{n:tvd.get(n,'') for n in ['T2S_text', 'T2S_lang', 'S2T_text', 'S2T_lang', 'S2T_match', 'cur_ii']})

@app.route('/tv_runjs')
def tv_runjs():
	name, cmd = unquote(request.query_string.decode()).split('/', 1)
	ip2websock[get_tv_ip(name)].send(cmd)
	return 'OK'

def _tvPlay(name, listfilename, url_root):
	tv_name, tm_info = (name.split(' ',1)+[0])[:2]
	if is_json_lst(listfilename):
		get_tv_data(tv_name)['playlist'] = json.loads(listfilename)
		listfilename = ''
	if tv_name in tv2lginfo:
		tv_on_if_off(tv_name, True)
		return tv(tv_name, f'openBrowserAt "{url_root}/webPlay/{tm_info}/{listfilename}"')
	else:
		ws = ip2websock[get_tv_ip(tv_name)]
		return ws.send(f'seturl("{url_root}/webPlay/{tm_info}/{listfilename}")') or 'OK'

@app.route('/tvPlay/<name>/<path:listfilename>')
def tvPlay(name, listfilename, url_root=None):
	threading.Thread(target=_tvPlay, args=(name, listfilename, url_root or get_url_root(request))).start()
	return 'OK'

last_save_time = time.time()
def mark(name, tms):
	tvd = get_tv_data(name)
	if tvd['shuffled']:
		return 'Ignored'
	tvd['markers'].update({json.dumps(tvd['playlist']): [tvd['cur_ii'], tms]})
	fn = tvd['playlist'][tvd['cur_ii']]
	if getDuration(fn) >= DRAMA_DURATION_TH:
		tvd['last_movie_drama'] = fn
	prune_dict(tvd['markers'])
	if time.time()-last_save_time>3600:
		save_playstate(prune_dict(ip2tvdata))
		last_save_time = time.time()

ip2subtt = {}
def _load_subtitles(video_file, n_subs, ip):
	if ip2subtt.get(ip, '') != video_file:
		out_dir = f'{TMP_DIR}/.subtitles/{ip}'
		if not os.path.isdir(out_dir):
			runsys(f'mkdir -p {out_dir}')
		if video_file in ip2subtt.values():
			ip2 = [k for k,v in ip2subtt.items() if v==video_file][0]
			runsys(f'cp -rf {TMP_DIR}/.subtitles/{ip2}/* {out_dir}/')
			LOG(f'Copyed {n_subs} subtitle files from {ip2} to {ip} ...')
		else:
			LOG(f'Loading {n_subs} subtitle tracks from "{video_file}" ...')
			out = RUN(['ffmpeg', '-y', '-i', video_file]+[it for k in range(n_subs) for it in ['-map', f'0:s:{k}', '-f', 'webvtt', f'{out_dir}/{k}.vtt']], shell=False, timeout=9999)
			LOG(f'Finished Loading {n_subs} subtitle tracks from "{video_file}": {out}')
		ip2subtt[ip] = video_file
	ip2websock[ip].send('load_subtitles()')

@app.route('/tv_wscmd/<name>/<path:cmd>')
def tv_wscmd(name, cmd):
	LOG(name+' : '+cmd)
	try:
		ip = get_tv_ip(name)
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
		elif cmd.startswith('loop_mode '):
			ws.send(f"toggle_loop({cmd.split(' ',1)[1]})")
		elif cmd.startswith('lsdir '):
			full_dir = SHARED_PATH+cmd.split(' ',1)[1]+'/'
			lst = showdir(full_dir)
			ws.send('\tshowDir\t'+'\n'.join(lst))
		elif cmd.startswith('list_subtitles '):
			file_path = SHARED_PATH+cmd.split(' ',1)[1]
			subs = list_subtitles(file_path)
			LOG(f'"{file_path}" contains {len(subs)} subtitle tracks')
			ws.send(f'\tlist_subtitles\t{json.dumps(subs)}')
		elif cmd.startswith('load_subtitles '):
			args = cmd.split(' ', 2)
			n_subs = int(args[1])
			file_path = SHARED_PATH+args[2]
			threading.Thread(target=_load_subtitles, args=(file_path, n_subs, ip)).start()
		else:
			if cmd in ['next', 'prev']:
				tvd['cur_ii'] = (tvd['cur_ii']+(1 if cmd=='next' else -1))%len(tvd['playlist'])
			elif cmd.startswith('goto_idx '):
				tvd['cur_ii'] = int(cmd.split()[1])
			elif cmd.startswith('goto_file '):
				fn = cmd.split(' ',1)[1].strip('/')
				if fn.lower().endswith('.m3u'):
					load_m3u(fn)
				flist = ls_media_files(SHARED_PATH+os.path.dirname(fn))
				tvd['playlist'] = flist
				tvd['cur_ii'] = [ii for ii,fulln in enumerate(flist) if fulln.endswith('/'+fn)][0]
				ws.send('\tupdateList\t'+'\n'.join([s.split('/')[-1] for s in flist]))
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
		res = tv_wscmd(tv_name, f'play_audio("/{f"voice?{random.randint(0,999999)}" if fn==DEFAULT_T2S_SND_FILE else fn}",true)')
		assert res == 'OK'
	else:
		RUNSYS(f'mplayer -really-quiet -noconsolecontrols {fn}', ev_voice)
	if block: ev_voice.wait()
	return ev_voice

def record_audio(tm_sec=5, file_path=DEFAULT_S2T_SND_FILE):
	os.system(f'ffmpeg -y -f pulse -i {get_recorder(MIC_RECORDER)} -ac 1 -t {tm_sec} {file_path}')


# For ASR server
def get_ASR_offline(audio_fn=asr_input):
	try:
		CANCEL_FLAG = False
		obj = asr_model.transcribe(os.path.expanduser(audio_fn), cancel_func=cancel_requested)
		return obj
	except Exception as e:
		traceback.print_exc()
		return str(e)

def get_ASR_online(audio_fn=asr_input):
	try:
		with Open(audio_fn, 'rb') as f:
			r = requests.post(ASR_CLOUD_URL, files={'file': f}, timeout=ASR_CLOUD_TIMEOUT)
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
			self.cur_vol = tvVolume(self.tv_name)
		elif player!=None:
			self.cur_sta = player.is_playing()
			if self.cur_sta:
				player.set_pause(True)
			self.cur_vol = get_volume()
		return self

	def restore(self):
		if self.tv_name:
			if self.cur_vol:
				tvVolume(self.tv_name, self.cur_vol)
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
def recog_and_play(voice_prompt, tv_name, path_name, handler, url_root, audio_file=DEFAULT_S2T_SND_FILE):
	global player, asr_model, ASR_cloud_running, ASR_server_running

	with VoicePrompt(tv_name) as context:
		# record speech
		if voice_prompt:
			set_volume(VOICE_VOL[tv_name])
			play_audio(voice_prompt, True, tv_name)
			record_audio()

		# try cloud ASR
		if ASR_CLOUD_URL and not ASR_cloud_running:
			ASR_cloud_running = True
			asr_output = get_ASR_online(audio_file)
			ASR_cloud_running = False

		# try offline ASR if cloud ASR fails
		if type(asr_output)==str or not asr_output:
			if asr_model == None:
				return play_audio('voice/offline_asr_not_available.mp3', True, tv_name) if voice_prompt else "Offline ASR not available!"
			if ASR_server_running:
				return play_audio('voice/unfinished_offline_asr.mp3', True, tv_name) if voice_prompt else "Another offline ASR is running!"
			if voice_prompt:
				play_audio('voice/wait_for_asr.mp3', False, tv_name)

			context.restore()
			asr_output = get_ASR_offline(audio_file)

		print(f'ASR result: {asr_output}', file=sys.stderr)
		if asr_output=={} or type(asr_output)==str:
			return play_audio('voice/asr_error.mp3', True, tv_name) if voice_prompt else f"ASR error: {asr_output}"
		elif not asr_output['text']:
			return play_audio('voice/asr_fail.mp3', True, tv_name) if voice_prompt else "ASR output is empty!"
		else:
			handler(asr_output, tv_name, path_name, url_root.rstrip('/'))


def _play_last(name=None, url_root=None):
	tvd, tms, ii = get_tv_data(name), 0, 0
	if 'last_movie_drama' in tvd:
		pl, ii, tms = load_playable(get_tv_ip(name), '-1', tvd['last_movie_drama'])[:3]
	else:
		pl = Try(lambda: tvd['playlist'], lambda: json.loads(list(tvd['markers'].keys())[-1]), lambda: getAnyMediaList())
		if pl:
			ii, tms = tvd['markers'].get(json.dumps(pl), [tvd.get('cur_ii', 0), 0])
	if name in tv2lginfo:
		tv_on_if_off(name, True)
	tvPlay(f'{name} {tms} {ii}', json.dumps(pl), url_root)

@app.route('/play_last')
@app.route('/play_last/<tv_name>')
def play_last(tv_name=None):
	threading.Thread(target=_play_last, args=(tv_name, get_url_root(request))).start()
	return 'OK'

def handle_ASR_indir(asr_out, tv_name, rel_path, url_root):
	res = findMedia(asr_out['text'].strip(), asr_out['language'], base_path=SHARED_PATH+rel_path)
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
	ii = findSong(asr_out['text'].strip(), asr_out['language'], lst)
	setInfo(tv_name, asr_out["text"], asr_out['language'], 'S2T', '' if ii==None else lst[ii][len(SHARED_PATH):])
	if ii == None:
		play_audio('voice/asr_not_found.mp3', True, tv_name)
	else:
		play_audio('voice/asr_found.mp3', True, tv_name)
		if lst_filename:
			_tvPlay(f'{tv_name} 0 {ii}', json.dumps(lst)) if tv_name else play(f'0 {ii}', json.dumps(lst), url_root)
		else:
			playFrom(ii) if tv_name==None else tv_wscmd(tv_name, f'goto_idx {ii}')

def save_post_file(fn=DEFAULT_S2T_SND_FILE):
	if request.method!='POST': return ''
	with Open(fn, 'wb') as fp:
		fp.write(request.data)
	return fn

# Play spoken item on TV
@app.route('/play_spoken_indir', methods=['GET', 'POST'])
@app.route('/play_spoken_indir/<tv_name>', methods=['GET', 'POST'])
@app.route('/play_spoken_indir/<tv_name>/<path:rel_path>', methods=['GET', 'POST'])
def play_spoken_drama(tv_name=None, rel_path=''):
	is_post, url_root = save_post_file(), get_url_root(request)
	F = lambda: recog_and_play('' if is_post else 'voice/speak_drama.mp3', None if tv_name=='None' else tv_name,
		rel_path, handle_ASR_indir, url_root)
	if is_post:
		return F()
	threading.Thread(target=F).start()
	return 'OK'

@app.route('/play_spoken_inlst', methods=['GET', 'POST'])
@app.route('/play_spoken_inlst/<tv_name>', methods=['GET', 'POST'])
@app.route('/play_spoken_inlst/<tv_name>/<path:lst_filename>', methods=['GET', 'POST'])
def play_spoken_song(tv_name=None, lst_filename=''):
	is_post, url_root = save_post_file(), get_url_root(request)
	threading.Thread(target=recog_and_play, args=('' if is_post else 'voice/speak_song.mp3', None if tv_name=='None' else tv_name, 
		lst_filename, handle_ASR_inlst, url_root)).start()
	return 'OK'

# Play spoken file recorded locally on the local device
@app.route('/play_recorded', methods=['POST'])
def play_recorded():
	recfn = save_post_file()
	threading.Thread(target=recog_and_play, args=('', request.remote_addr, '', handle_ASR_indir, get_url_root(request), recfn)).start()
	return 'OK'

# For Ecovacs
@app.route('/ecovacs', defaults={'name': '', 'cmd':''})
@app.route('/ecovacs/<name>/<cmd>')
def ecovacs(name='', cmd=''):
	return RUN(f'./ecovacs-cmd.sh {name} {cmd} &')


# For OpenHomeKaraoke
@app.route('/KTV/<cmd>')
def KTV(cmd):
	global P_ktv
	if cmd=='on':
		tv_name, input_id = (KTV_SCREEN.split(':')+[''])[:2]
		stop()
		tv_on_if_off(tv_name, True)
		if input_id:
			tv_setInput(tv_name, input_id)
		set_audio_device(KTV_SPEAKER, 5)
		P_ktv = subprocess.Popen(['~/projects/pikaraoke/run-cloud.sh'], shell=True, preexec_fn=os.setsid)
	elif cmd=='off':
		os.killpg(os.getpgid(P_ktv.pid), signal.SIGKILL)
		unset_audio_device(KTV_SPEAKER)
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

def parseRC(txt):
	its = [L.split('\t') for L in txt.strip().splitlines()]
	return [(it[0], c, it[-1]) for it in its for c in it[1].replace('｜', '|').split('|')]

@app.route('/voice_cmd/<path:hub_pfx>', methods=['POST'])
def voice_cmd(hub_pfx):
	global ASR_cloud_running, ASR_server_running
	hub_pfx = hub_pfx.rstrip('/')
	try:
		# save recorded audio file
		audio_file = save_post_file()
		assert audio_file

		# try cloud ASR
		if ASR_CLOUD_URL and not ASR_cloud_running:
			ASR_cloud_running = True
			asr_output = get_ASR_online(audio_file)
			ASR_cloud_running = False

		# try offline ASR if cloud ASR fails
		if type(asr_output)==str or not asr_output:
			if asr_model == None:
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
			return 'Not found: {asr_str}'
		cmdID, cmdDesc, cmdExec = cmd_tbl[ii][:3]
		if '/play_spoken_' in cmdExec and cmdExec[0]=="'" and cmdExec[-1]=="'":
			return f"EXEC ASR({cmdExec})"
		else:
			get_http(hub_pfx + '/rl_run?' + cmdID)
		return f'OK: {cmdDesc}'
	except:
		return traceback.format_exc()


if __name__ == '__main__':
	parser = argparse.ArgumentParser(usage='$0 [options]', description='launch the smart home server',
			formatter_class=argparse.ArgumentDefaultsHelpFormatter)
	parser.add_argument('--port', '-p', type=int, default=8883, help='server port number')
	parser.add_argument('--ssl', '-ssl', help='server port number', action='store_true')
	parser.add_argument('--asr', '-a', help='host ASR server', action='store_true')
	parser.add_argument('--asr-model', '-am', default='base', help='ASR model to load')
	parser.add_argument('--no-console', '-nc', help='do not open console', action='store_true')
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

	# For capturing yt-dlp thread's STDIO
	enable_proxy()

	if not ssl:
		threading.Thread(target=lambda:app.run(host='0.0.0.0', port=port+1, threaded = True, ssl_context=('cert.pem', 'key.pem'))).start()
	threading.Thread(target=lambda:app.run(host='0.0.0.0', port=port, threaded = True, ssl_context=('cert.pem', 'key.pem') if ssl else None)).start()

	if no_console:
		sys.exit(0)

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

	save_playstate(prune_dict(ip2tvdata))
	import os
	os._exit(0)
