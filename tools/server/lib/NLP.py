import os, sys, io, re, time, string, json, threading, yt_dlp, gzip, math, multiprocessing
import pykakasi, pinyin, logging, requests, shutil, subprocess, asyncio, socket
import pandas as pd
import jionlp as jio
import tinytuya
from multiprocessing import Process
from strands import Agent
from strands.tools import tool
from unidecode import unidecode
from hanziconv import HanziConv
from urllib.parse import quote, unquote
from werkzeug import local
from googletrans import Translator
from pydub import AudioSegment as AudSeg
from langcodes import find as LC_find

sys.path.append('.')
from lib.utils import *
from lib.ChineseNumber import *
from lib.EnglishNumber import *
from lib.settings import *
from lib.DefaultRevisionDict import InfiniteDefaultRevisionDict
from device_config import *
from contextlib import redirect_stdout, redirect_stderr
from lib.HMC_model import Model as HMC_model

ggl_translator = Translator()
KKS = pykakasi.kakasi()

cookies_opt = []
detect_lang = lambda t: Try(lambda: asyncio.run(ggl_translator.detect(t)).lang, '')
to_pinyin = lambda t: pinyin.get(t, format='numerical')
translit = lambda t: unidecode(t).lower()
to_romaji = lambda t: ' '.join([its['hepburn'] for its in KKS.convert(t)])
ls_media_files = lambda fullpath, exts=media_file_exts: [trimpath(f'{fullpath}/{f}') for f in listdir(fullpath) if not f.startswith('.') and '.'+f.split('.')[-1].lower() in exts]
ls_subdir = lambda fullpath: [g.rstrip('/') for f in listdir(fullpath) for g in [trimpath(f'{fullpath}/{f}')] if not f.startswith('.') and isdir(g)]
mrl2path = lambda t: unquote(t).replace('file://', '').strip() if t.startswith('file://') else (t.strip() if t.startswith('/') else '')
is_json_lst = lambda s: s.startswith('["') and s.endswith('"]')
load_m3u = lambda fn: [i for L in Open(fn).readlines() for i in [mrl2path(L)] if i]
ip_strip = lambda ip: ip.split(':')[0] if (type(ip)==str and ':' in ip) else ip

class IP_Dict(dict):
	def _dispatch_(self, name, key, *args, **kwargs):
		F = getattr(self[key], name, None)
		return None if F is None else F(*args, **kwargs)

	def __getattr__(self, name):
		if name.startswith('_') and name.endswith('_'):
			raise AttributeError(name)

		def wrapper(key, *args, **kwargs):
			return self._dispatch_(name, key, *args, **kwargs)

		return wrapper

	def __getitem__(self, ip):
		# ip: x.x.x.x or x.x.x.x:port
		obj = super().get(ip, None)
		if obj != None:
			return obj
		if ':' in ip:
			ip = ip.split(':')[0]
			obj = super().get(ip, None)
			if obj != None:
				return obj
			for k,v in self.items():
				if k.startswith(ip+':'):
					return v
		else:
			for k,v in self.items():
				if k.startswith(ip+':'):
					return v
		return None
	
	def __contains__(self, key):
		return self[key] != None

# Map 'dev_name' to threading.Timer()
Timers = {}

def SetTimer(name, period, F, desc=''):
	DelTimer(name)
	Timers[name] = tt = threading.Timer(period, F)
	tt.start()
	tt.name, tt.desc, tt.start_time = name, desc, pd.Timestamp.now()

def DelTimer(name):
	if name in Timers:
		Timers.pop(name).cancel()

def get_url_root(r):
	os.last_url_root = r.url_root.rstrip('/') if r.url_root.count(':')>=2 else r.url_root.rstrip('/')+f':{r.server[1]}'
	return os.last_url_root

def Eval(cmd, default=None):
	try:
		return eval(cmd, globals(), globals())
	except:
		return default

# For running shell commands:
# RUN(): run a single command and return its output
# runsys(): quick alias to os.system()
# RUNCMD(): subprocess.run multiple, support python callables
# POPENCMD(): subprocess.Popen multiple, support python callables

@tool
def RUN(cmd, shell=True, timeout=3, **kwargs):
	"""Run shell commands using `subprocess.check_output()`.

	Args:
		cmd (str): command-line string
		shell (bool = True): whether run it in a bash shell
		timeout (int = 3): timeout in seconds
		**kwargs: other arguments to be passed to `subprocess.check_output()`

	Returns:
		(str): the command's stdout or stderr (upon error)
	"""
	LOG(f'RUN: {cmd}')
	try:
		ret = subprocess.check_output(cmd, shell=shell, timeout=timeout, **kwargs)
	except Exception as e:
		ret = str(e)
	return ret if type(ret)==str else ret.decode()

@tool
def runsys(*cmds, event=None, **kwargs):
	"""Run shell command(s) using `os.system()` or python function(s) until it finishes.

	Args:
		*cmds (tuple of (str, callable)): the shell command (if str), or the python function (if callable)

	Returns:
		(str): every command's:
		 - if no exception: exit code (or python function return casted to str)
		 - if exception: the Exception casted to str
		 joined by "\n\n".
	"""
	rets = []
	for cmd in cmds:
		LOG(f'RUNSYS: {cmd}')
		try:
			rets += [cmd() if callable(cmd) else os.system(cmd)]
		except Exception as e:
			rets += [e]
	if event!=None:
		event.set()
	return '\n\n'.join([str(ret) for ret in rets])

def RUNSYS(*cmds, **kwargs):
	threading.Thread(target=runsys, args=cmds, kwargs=kwargs).start()

@tool
def POPENCMD(*cmds, **kwargs):
	"""Run shell command(s) or python function(s) one by one, using `subprocess.Popen()` or `multiprocessing.Process()`.

	Args:
		*cmds (tuple of (str, list or callable)): the shell command (if str or list), or the python function (if callable)
		**kwargs: other arguments to be passed to `subprocess.check_output()`

	Returns:
		A tuple of each cmd's:
		 - if no exception: subprocess.CompletedProcess (for shell command) or return value (for Python callable)
		 - if exception: the Python Exception object
	"""
	rets = ()
	for cmd in cmds:
		LOG(f'RUN: {cmd}')
		try:
			if callable(cmd):
				ret = Process(target=cmd)
				ret.start()
			else:
				ret = subprocess.Popen(cmd, **kwargs)
		except Exception as e:
			ret = e
		rets += (ret, )
	return rets

@tool
def RUNCMD(*cmds, **kwargs):
	"""Run shell command(s) or python function(s) one by one, using `subprocess.run()` or `.call()`.

	Args:
		*cmds (tuple of (str, list or callable)): the shell command (if str or list), or the python function (if callable)
		**kwargs: other arguments to be passed to `subprocess.check_output()`

	Returns:
		A tuple of each cmd's:
		 - if no exception: subprocess.CompletedProcess (for shell command) or return value (for Python callable)
		 - if exception: the Python Exception object
	"""
	rets = ()
	for cmd in cmds:
		LOG(f'RUN: {cmd}')
		try:
			ret = cmd() if callable(cmd) else subprocess.run(cmd, **kwargs)
		except Exception as e:
			ret = e
		rets += (ret, )
	return rets

def run_thread(F, *args, **kwargs):
	thread = threading.Thread(target=lambda: F(*args, **kwargs))
	thread.start()
	return thread

get_filesize = lambda fn: Try(lambda: os.path.getsize(fn), 0)

def fuzzy(txt, dct=FUZZY_PINYIN):
	for src, tgt in dct.items():
		txt = txt.replace(src, tgt)
	return txt

def url_is_ip(url, ip):
	s1 = ''.join([c for c in url if c.isdigit() or c=='.'])
	s2 = ''.join([c for c in ip if c.isdigit() or c=='.'])
	return s1==s2

def isVideoFileExt(fn):
	for ext in video_file_exts:
		if fn.lower().endswith(ext):
			return True
	return False

def get_bak_fn(fn):
	dirname = os.path.dirname(fn)
	Try(lambda: os.makedirs(dirname+'/.orig'))
	return f'{dirname}/.orig/{os.path.basename(fn)}'

def norm_song_volume(fn):
	audio = AudSeg.from_file(fn)
	if isVideoFileExt(fn):
		if not os.path.exists(get_bak_fn(fn+'.m4a')):
			audio.export(get_bak_fn(fn+'.m4a'), format='ipod')
		audio += (STD_VOL_DBFS - audio.dBFS)
		audio.export(fn+'.m4a', format='ipod')
		RUN(['ffmpeg', '-y', '-i', fn, '-i', fn+'.m4a', '-c', 'copy', '-map', '0', '-map', '-0:a', '-map', '1:a', fn+'.tmp.mp4'], shell=False, timeout=None)
		os.system('sync')
		os.rename(f'{fn}.tmp.mp4', fn)
		os.system('sync')
		os.remove(fn+'.m4a')
	else:
		if not os.path.exists(get_bak_fn(fn+'.m4a')):
			os.rename(fn, get_bak_fn(fn+'.m4a'))
		audio += (STD_VOL_DBFS - audio.dBFS)
		audio.export(fn, format=('mp3' if fn.lower().endswith('.mp3') else 'ipod'))


fn2dur = InfiniteDefaultRevisionDict()	# cache for getDuration()
def getDuration(fn):
	if fn in fn2dur:
		return fn2dur[fn]
	res = RUN(['ffprobe', '-i', fn, '-show_entries', 'format=duration', '-v', 'quiet',  '-of', 'csv=p=0'], shell=False)
	ret = fn2dur[fn] = Try(lambda: float(res.strip()), 0)
	fn2dur.prune(max_items=100)
	return ret

def str_search(name, name_list):
	# 1. exact full match
	if name in name_list:
		return [ii for ii,name1 in enumerate(name_list) if name==name1]

	# 2. exact substring match
	res = [[ii, len(it)-len(name)] for ii,it in enumerate(name_list) if name in it]
	return [it[0] for it in sorted(res, key=lambda t:t[1])] if res else []

def asr_postprocess(txt):
	ret = txt.strip()
	for c in punctuation:
		ret = ret.strip(c)
	return ret.lower()

def filepath2songtitle(fn):
	bn = os.path.basename(unquote(fn).rstrip('/'))
	s = (bn if os.path.isdir(fn) else bn.rsplit('.', 1)[0]).strip()
	return os.path.basename(os.path.dirname(unquote(fn).rstrip('/')))+s if s.isdigit() else s


def findSong(name, lang=None, flist=[], unique=False):
	name = name.lower().strip()
	name_list = [filepath2songtitle(fn).lower() for fn in flist]

	# 0. pre-transform
	if lang == 'el':
		name = fuzzy(name, FUZZY_GREEK)
		name_list = [fuzzy(n, FUZZY_GREEK) for n in name_list]

	# 1. exact full match of original form
	if name in name_list:
		res = [ii for ii,name1 in enumerate(name_list) if name==name1]
		if len(res)==1 or not unique:
			return res[0]

	# 2. match by pinyin if Chinese or unknown
	if lang in [None, 'zh']:
		# 3. pinyin full match
		pinyin_list = [get_alnum(fuzzy(to_pinyin(num2zh(n)))) for n in name_list]
		pinyin_name = get_alnum(fuzzy(to_pinyin(num2zh(name))))
		res = str_search(pinyin_name, pinyin_list)
		if pinyin_name and res and (len(res)==1 or not unique):
			return res[0]
		pinyin_list = [get_alpha(fuzzy(to_pinyin(num2zh(n)))) for n in name_list]
		pinyin_name = get_alpha(fuzzy(to_pinyin(num2zh(name))))
		res = str_search(pinyin_name, pinyin_list)
		if pinyin_name and res and (len(res)==1 or not unique):
			return res[0]

	# 3. match by romaji if Japanese or unknown
	if lang in [None, 'ja']:
		# 5. romaji full match
		romaji_list = [get_alpha(to_romaji(n)) for n in name_list]
		romaji_name = get_alpha(to_romaji(name))
		res = str_search(romaji_name, romaji_list)
		if romaji_name and res and (len(res)==1 or not unique):
			return res[0]

	# 4. substring match
	res = str_search(name, name_list)
	if res and (len(res)==1 or not unique):
		return res[0]
	
	# 5. match by transliteration
	translit_list = [get_alpha(fuzzy(translit(n))) for n in name_list]
	translit_name = get_alpha(fuzzy(translit(name)))
	res = str_search(translit_name, translit_list)
	if translit_name and res and (len(res)==1 or not unique):
		return res[0]

	return None


def match_episode(episode:int, lst):
	for ii,it in enumerate(lst):
		for num_field in re.findall(r'[0-9]+', os.path.basename(it)):
			if int(num_field)==episode:
				return ii
	return min(episode-1, len(lst))

def findMedia(name, lang=None, stack=0, stem=None, episode=None, base_path=SHARED_PATH):
	if episode == None:
		stem, episode = name, ''
		if lang=='zh':
			if stem.endswith('集'):
				stem = stem[:-1].strip()
			while stem[-1].isdigit() or stem[-1] in NORMAL_CN_NUMBER:
				episode = stem[-1] + episode
				stem = stem[:-1].strip()
			if lang=='zh' and stem.endswith('第'):
				stem = stem[:-1].strip()
			episode = Try(lambda: int(episode if episode.isdigit() else zh2num(episode)), '')
		elif lang=='en':
			stem, episode = detect_trailing_number(name)
			if episode and stem.endswith(' episode'):
				stem = stem[:-8]
	d_lst = ls_subdir(base_path)
	lst = d_lst+ls_media_files(base_path)
	res = findSong(name, lang, lst)
	if res==None and name!=stem:
		res = findSong(stem, lang, lst)
		if res!=None and episode and isfile(lst[res]):
			res = None
	if res!=None:
		item = lst[res]
		if isfile(item):
			return item
		lst2 = ls_media_files(item)
		res = findSong(name, lang, lst2, True)	# full match takes precedence
		if res!=None:
			return (item, res)
		if episode and len(lst2)>=episode:
			return (item, match_episode(episode, lst2))
		return item
	if stack<MAX_WALK_LEVEL:
		for d in d_lst:
			res = findMedia(name, lang, stack+1, stem, episode, d)
			if res != None:
				return res
	return None


def getAnyMediaList(base_path=SHARED_PATH, exts=video_file_exts):
	lst = ls_media_files(base_path, exts)
	if lst: return lst
	for dir in ls_subdir(base_path):
		lst = getAnyMediaList(dir, exts)
		if lst: return lst
	return []

def fn2mediaType(fn):
	try:
		fext = '.' + fn.rsplit('.', 1)[1].lower()
		if fext == '.webm':
			obj = ffprobe_streams(fn)
			has_video = sum([o1["codec_type"]=='video' for o1 in obj['streams']])
			return 'video' if has_video else 'audio'
		if fext in audio_file_exts:
			return 'audio'
		if fext in video_file_exts:
			return 'video'
	except:
		pass
	return 'file'

def getMediaType(fn):
	# 4 classes: song, movie, drama, file
	try:
		if os.path.isdir(fn):
			lst = ls_media_files(fn)
			n_song = sum([fn2mediaType(f1)=='audio' for f1 in lst])/len(lst)
			if n_song==1:
				return 'song'
			if n_song==0:
				return 'drama' if len(lst)>=8 else 'movie'
		else:
			mediaType = fn2mediaType(fn)
			if mediaType == 'audio':
				return 'song'
			if mediaType == 'video':
				dur = getDuration(fn)
				return 'movie' if dur>6000 else ('drama' if dur>900 else 'song')
	except:
		pass
	return 'file'


# For yt-dlp
def parse_outfn(L, tmp_dir):
	out_fn = ''
	for L1 in L.splitlines():
		if L1.startswith('[') and tmp_dir in L1 and '.mp4' in L1:
			out_fn = L1[L1.find(tmp_dir):L1.rfind('.mp4')+4]
	return out_fn

def run_thread_redirect(func, stdout, stderr):
	with redirect_stdout(stdout):
		with redirect_stderr(stderr):
			func()

def call_yt_dlp(argv, mobile_ip, tmp_dir):
	out_fn = ''
	stdout, stderr = io.StringIO(), io.StringIO()
	thread = run_thread(lambda: run_thread_redirect(lambda: yt_dlp.main(argv), stdout, stderr))
	while thread.is_alive():
		time.sleep(1)
		L = stdout.getvalue()+stderr.getvalue()
		if not L: continue
		stdout.truncate(0), stdout.seek(0)
		stderr.truncate(0), stderr.seek(0)
		sys.stdout.write(L)
		sys.stdout.flush()
		Try(lambda: os.ip2ydsock[mobile_ip].send(L))
		out_fn = parse_outfn(L, tmp_dir) or out_fn
	return out_fn


def download_video(song_url, include_subtitles, high_quality, redownload, mobile_ip):
	logging.info("Downloading video: " + song_url)
	tmp_dir = expand_path(f'{DOWNLOAD_PATH}/tmp/')

	# If file already present, skip downloading
	cmd_base = ['--fixup', 'force', '--socket-timeout', '3', '-R', 'infinite', '--remux-video', 'mp4'] \
		+ cookies_opt + (['--force-overwrites'] if redownload else [])
	opt_quality = ['-f', 'bestvideo[height<=1080]+bestaudio[abr<=160]'] if high_quality else ['-f', 'mp4+m4a']
	opt_sub = ['--sub-langs', 'all', '--embed-subs'] if include_subtitles else []
	cmd = cmd_base + opt_quality + opt_sub + ["-o", tmp_dir+"%(title)s.%(ext)s"] + [song_url]
	logging.info("Youtube-dl command: " + " ".join(cmd))
	out_fn = call_yt_dlp(cmd, mobile_ip, tmp_dir)
	if not out_fn:
		logging.error("Error code while downloading, retrying without format options ...")
		cmd = cmd_base + ['-P', tmp_dir] + [song_url]
		logging.info("Youtube-dl command: " + " ".join(cmd))
		out_fn = call_yt_dlp(cmd, mobile_ip, tmp_dir)
	if get_filesize(out_fn):
		logging.info("Song successfully downloaded: " + song_url)
		ret_fn = expand_path(DOWNLOAD_PATH)+'/'+os.path.basename(out_fn)
		shutil.move(out_fn, ret_fn)
		return ret_fn
	else:
		logging.error("Error downloading song: " + song_url)

	return ''

def get_subts_tagInfo(t):
	out = [t.get('language', ''), t.get('title', '')]
	Try(lambda:out.remove(''))
	return (':'.join(out) if out else [f'{k}:{v}' for k,v in t.items()][0]).replace('\t', ' ').strip()

def ffprobe_streams(fn):
	out = RUN(['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_streams', fn], shell=False)
	return json.loads(out.strip())

BITMAP_SUBTITLE_CODECS = {'dvd_subtitle', 'hdmv_pgs_subtitle'}

fullpath2stt_info = {}
def list_subtitles(fullpath, force=False):
	realpath = os.path.realpath(fullpath)
	if force or realpath not in fullpath2stt_info:
		try:
			obj = ffprobe_streams(realpath)
			fullpath2stt_info[realpath] = [[get_subts_tagInfo(s['tags']), str(s["index"])+('.sup' if s["codec_name"] in BITMAP_SUBTITLE_CODECS else '.vtt'), s["codec_name"]]
								  for s in obj['streams'] if s['codec_type']=='subtitle']
		except Exception as e:
			fullpath2stt_info[realpath] = []
	return fullpath2stt_info[realpath]
	
def ble_gap_advertise(payload, duration=1):
	try:
		s = payload.lower()
		assert len(s)%2==0
		assert all(c in string.hexdigits for c in s)
		data = ' '.join([s[i:i+2] for i in range(0, len(s), 2)])

		runsys(f'sudo hciconfig hci0 up')
		runsys(f'sudo hcitool -i hci0 cmd 0x08 0x0008 {"%02x"%(len(s)//2)} {data}')
		runsys(f'sudo hcitool -i hci0 cmd 0x08 0x0006 a0 00 a0 00 03 00 00 00 00 00 00 00 00 07 00')
		runsys(f'sudo hcitool -i hci0 cmd 0x08 0x000a 01')
		time.sleep(duration)
		runsys(f'sudo hcitool -i hci0 cmd 0x08 0x000a 00')
		return True
	except:
		return False

def sec2hhmmss(sec, sub_second=False):
	try:
		s = float(sec)
		return f'{int(s//3600):02d}:{int((s%3600)//60):02d}:{int(s%60):02d}.{int(s%1*100):02d}'
	except:
		return ''

def hhmmss2sec(hms):
	hh, mm, ss = [float(i) for i in (['0', '0']+hms.split(':'))[-3:]]
	return hh*3600 + mm*60 + ss

def xauth_add(key=None):
	"""
	Xauth add magic key to screen :0
	"""
	try:
		mkey = key or RUN(['xauth', 'list'], shell=False).splitlines()[0].split()[-1]
		RUN(['xauth', 'add', ':0', '.', mkey], shell=False)
	except:
		pass


# Weather API
_weathercode_mapping = {
	0: "Clear sky",
	1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
	45: "Fog", 48: "Depositing rime fog",
	51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
	61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
	80: "Slight rain showers", 81: "Moderate rain showers", 82: "Violent rain showers",
	95: "Thunderstorm",
}
def _get_weather():
	# Define the coordinates (e.g., Singapore)
	params = {
		"latitude": GPS_LOCATION[0],
		"longitude": GPS_LOCATION[1],
		"current": ["temperature_2m", "relative_humidity_2m", "wind_speed_10m", "apparent_temperature", "weather_code"],
		"timezone": "auto"
	}
	response = requests.get("https://api.open-meteo.com/v1/forecast", params=params)
	try:
		data = response.json()['current']
		wt = {
			'temperature': data['temperature_2m'],
			'humidity': data['relative_humidity_2m'],
			'realfeel': data['apparent_temperature'],
			'weatherText': _weathercode_mapping.get(data['weather_code'], "Unknown condition")
		}
		print('_get_weather():', wt)
	except:
		print(f"Error in _get_weather(): {response.status_code}")
		wt = {}
	
	return wt

def get_weather():
	now = pd.Timestamp.now()
	try:
		last_wt = os.sys_state['_weather_']['last_wt']
		last_wt_tms = pd.Timestamp(os.sys_state['_weather_']['last_wt_tms'], unit='s')
		refresh = now-last_wt_tms>pd.to_timedelta('1H')
	except:
		refresh = True
	if refresh:
		last_wt = _get_weather()
		if last_wt:
			os.sys_state['_weather_']['last_wt'] = last_wt
			os.sys_state['_weather_']['last_wt_tms'] = now.timestamp()
			os.save_state()
		else:
			last_wt = os.sys_state['_weather_']['last_wt']
	return last_wt

# HMC models
hmc_models = {}
hmc_lastT = {}
def HMC_predict(name, x):
	if name not in hmc_models:
		hmc_models[name] = HMC_model(name)
	m = hmc_models[name]
	return m.predict(x)

def HMC_train(name, x, y):
	if name not in hmc_models:
		hmc_models[name] = HMC_model(name)
	m = hmc_models[name]
	tms = time.time()
	m.add(x, y, overwrite_last=(tms-hmc_lastT[name]<AUTO_LEARN_OWL_SEC))
	hmc_lastT[name] = tms


# DysonFan API
def dysonFanGetPower(name):
	try:
		fan = FAN_DATA[name]
		ser = fan['sn'].encode()
		msg1 = b'\x82\x99\x01\x00\x01\x00"438/{SER}/status/current\x01\x00#438/{SER}/status/software\x01\x00%438/{SER}/status/connection\x01\x00!438/{SER}/status/faults\x01'.replace(b'{SER}', ser)
		msg2 = b'2\xa4\x01\x00\x1b438/{SER}/command\x00\x02{\n  "g": "438/{SER}/command",\n  "mode-reason": "LAPP",\n  "msg": "REQUEST-CURRENT-STATE",\n  "time": "2024-01-01T13:25:18Z"\n}'.replace(b'{SER}', ser)
		s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		s.settimeout(5)
		s.connect((fan['IP'], fan['PORT']))
		s.sendall(msg1)
		s.recv(256)
		s.sendall(msg2)
		all=b''
		for i in range(10):
			data = s.recv(1024)
			all += data
			if b'"fpwr"' in data:
				p = data.find(b'"fpwr"')
				return data[p:p+16], all
		return 'Speed value not found'
	except:
		return traceback.format_exc()
os.dysonFanGetPower = dysonFanGetPower

def dysonFanGetSpeed(name):
	try:
		fan = FAN_DATA[name]
		ser = fan['sn'].encode()
		msg1 = b'\x82\x99\x01\x00\x01\x00"438/{SER}/status/current\x01\x00#438/{SER}/status/software\x01\x00%438/{SER}/status/connection\x01\x00!438/{SER}/status/faults\x01'.replace(b'{SER}', ser)
		msg2 = b'2\xa4\x01\x00\x1b438/{SER}/command\x00\x02{\n  "g": "438/{SER}/command",\n  "mode-reason": "LAPP",\n  "msg": "REQUEST-CURRENT-STATE",\n  "time": "2024-01-01T13:25:18Z"\n}'.replace(b'{SER}', ser)
		s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		s.settimeout(5)
		s.connect((fan['IP'], fan['PORT']))
		s.sendall(msg1)
		s.recv(256)
		s.sendall(msg2)
		for i in range(10):
			data = s.recv(1024)
			if b'"fnsp"' in data:
				p = data.find(b'"fnsp"')
				return int(b''.join([data[p+i:p+i+1] for i in range(6,13) if data[p+i:p+i+1].isdigit()]))
		return 'Speed value not found'
	except:
		return traceback.format_exc()
os.dysonFanGetSpeed = dysonFanGetSpeed

def dysonFanSetSpeed(name, speed):
	try:
		fan = FAN_DATA[name]
		ser = fan['sn'].encode()
		msg = b'2\xbc\x01\x00\x1b438/{SER}/command\x00\x04{\n  "data": {\n    "fnsp": "%04d"\n  },\n  "h": "438/{SER}/command",\n  "mode-reason": "LAPP",\n  "msg": "STATE-SET",\n  "time": "2023-12-20T10:26:49Z"\n}'.replace(b'{SER}', ser)
		s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		s.settimeout(5)
		s.connect((fan['IP'], fan['PORT']))
		s.sendall(msg % speed)
		s.close()
		return 'OK'
	except:
		return traceback.format_exc()
os.dysonFanSetSpeed = dysonFanSetSpeed

def dysonFanAdjSpeed(name, adjust):
	speed = dysonFanGetSpeed(name)
	if type(speed) != int:
		return speed
	return dysonFanSetSpeed(name, speed+adjust)
os.dysonFanAdjSpeed = dysonFanAdjSpeed
	

# Imported from Micropython lib
url_string = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.~/?'
def parse_data(s):
	if type(s)==int:
		h = hex(s)[2:]
		return bytes.fromhex(('0'+h) if len(h)&1 else h)
	if type(s)==str:
		return Try(lambda: bytes.fromhex(s), s.encode())
	return s

def url_encode(s):
	try:
		p = s.find('/', s.find('//')+2)
		return s[:p] + ''.join([(c if c in url_string else f'%{ord(c):x}') for c in s[p:]])
	except:
		return s
	
def send_tcp(obj):
	try:
		s = socket.socket()
		s.settimeout(3)
		s.connect((obj['IP'], obj['PORT']))
		data = parse_data(obj['data'])
		s.sendall(data)
		s.recv(obj.get('recv_size', 256))
		s.close()
		return f'OK, sent {len(data)} bytes'
	except Exception as e:
		LOG(e)
		return str(e)

def send_udp(obj):
	try:
		s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
		nsent = s.sendto(parse_data(obj['data']), (obj['IP'], obj['PORT']))
		s.close()
		return f'OK, sent {nsent} bytes'
	except Exception as e:
		LOG(e)
		return str(e)
	
def send_wol(obj):
	try:
		mac = obj['data']
		if len(mac) == 17:
			mac = mac.replace(mac[2], "")
		elif len(mac) != 12:
			return f"Incorrect MAC address format: {mac}"
		s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
		s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
		nsent = s.sendto(bytes.fromhex("F"*12 + mac*16), (obj.get('IP', '255.255.255.255'), obj.get('PORT', 9)))
		s.close()
		return f'OK, sent {nsent} bytes'
	except Exception as e:
		LOG(e)
		return str(e)

def send_cap(obj):
	s = None
	for L in open(obj['filename'], 'rb'):
		try:
			L = L.strip()
			if L.startswith(b'{'):
				obj = eval(L)
				s = socket.socket()
				s.settimeout(3)
				s.connect((obj['IP'], obj['PORT']))
				if 'data' in obj:
					s.sendall(parse_data(obj['data']))
			elif L.startswith(b'b'):
				s.sendall(eval(L))
			elif L.isdigit():
				s.recv(int(L)*2)
		except:
			pass
	try:
		s.close()
		return 'OK'
	except:
		return traceback.format_exc()

def RC_tuya_outlet(obj: dict):
	try:
		d = tinytuya.OutletDevice(
			dev_id=obj['dev_id'],
			address=obj.get('address', 'Auto'),      # Or set to 'Auto' to auto-discover IP address
			local_key=obj['local_key'], 
			version=obj.get('version', 3.3)
		)
		func = obj.get('func', lambda t: t.status())
		return func(d)
	except:
		return traceback.format_exc()

err = False
def execRC(s, stack=0):
	global err
	if stack==0:
		err = False
	if type(s)==bytes:
		s = s.decode()
	LOG(f'execRC({stack}): {str(s)}')
	if s is None: return 'OK'
	try:
		if callable(s):
			return s()
		elif type(s)==list:
			res = []
			for i in s:
				res += [execRC(i, stack+1)]
			return '\r\n'.join(res)
		elif type(s)==str:
			if s.startswith('http'):
				requests.get(url_encode(s),timeout=5).close()
			else:
				return s if err else execRC(Eval(s), stack+1)
		elif type(s)==dict:
			p = s.get('protocol', 'RF433')
			LOG(p, s)
			if p=='TCP':
				return send_tcp(s)
			elif p=='UDP':
				return send_udp(s)
			elif p=='WOL':
				return send_wol(s)
			elif p=='CAP':
				return send_cap(s)
			elif p=='BLE':
				return ble_gap_advertise(s['data'])
			elif p=='tuya_outlet':
				return RC_tuya_outlet(s)
	except:
		err = True
		e = traceback.format_exc()
		LOG(e)
		return str(e)
	return str(s)

def get_local_IP():
	s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
	s.connect(("8.8.8.8", 80))
	ret = s.getsockname()[0]
	s.close()
	return ret

def txt2time(txt):
	try:
		zhs = HanziConv.toSimplified(txt)
		obj = jio.ner.extract_time(zhs)[0]['detail']['time']
		if type(obj)==list:
			tm = pd.Timestamp(obj[0])
		elif type(obj)==dict:
			tm = pd.Timestamp.now() + pd.to_timedelta(sum([pd.to_timedelta(str(v)+k).total_seconds() for k,v in obj.items()]), 's')
		return tm
	except:
		return None

def cpufreq_list():
	ret = Try(lambda: open('/sys/bus/cpu/devices/cpu0/cpufreq/scaling_available_frequencies').read().strip().split(), [])
	if not ret:
		try:
			fmax = Try(lambda: open('/sys/bus/cpu/devices/cpu0/cpufreq/cpuinfo_max_freq').read().strip(), None)
			fmin = Try(lambda: open('/sys/bus/cpu/devices/cpu0/cpufreq/cpuinfo_min_freq').read().strip(), None)
			if fmax!=None and fmin!=None:
				f1, f2 = int(fmin), int(fmax)
				ndigits = 1 - int(math.log10(abs(f2)))
				ret = [str(round(v, ndigits)) for v in range(f1, f2, round((f2-f1)/10))]
		except:
			ret = []
	return ret

def cpufreq_set(perc=0):
	# perc: 0 (min), 1 (max)
	flist = cpufreq_list()
	if not flist:
		return False
	n = round((len(flist)-1)*perc)
	return runsys(f'sudo cpupower frequency-set -u {flist[n]}')


class ASR:
	def __init__(self, compo_name='', verbose=True) -> None:
		bk_name, model_name, bk_bit = (compo_name.split(':')+['',''])[:3]
		if bk_name == 'faster_whisper':
			from faster_whisper import WhisperModel
			model_name = model_name or 'large-v3'
			compute_type = bk_bit or 'int8'
			self.model = WhisperModel(model_name, compute_type=compute_type)
			self.transcribe = self._transcribe_faster_whisper
			if verbose:print(f'Offline {bk_name} ASR model `{model_name}:{compute_type}` loaded successfully ...', file=sys.stderr)
			self.name = ':'.join([bk_name, model_name, compute_type])
		elif bk_name == 'whisper':
			import whisper
			model_name = model_name or 'large-v3'
			self.model = whisper.load_model(model_name, in_memory=True)
			self.transcribe = self._transcribe_whisper
			if verbose:print(f'Offline {bk_name} ASR model `{model_name}` loaded successfully ...', file=sys.stderr)
			self.name = ':'.join([bk_name, model_name])
		elif bk_name == 'qwen':
			from qwen_asr import Qwen3ASRModel
			model_name = model_name or "Qwen/Qwen3-ASR-1.7B"
			self.model = Qwen3ASRModel.from_pretrained(model_name, dtype=torch.float16, device_map="cuda", max_inference_batch_size=1, max_new_tokens=1024)
			self.transcribe = self._transcribe_qwen
			if verbose:print(f'Offline {bk_name} ASR model `{model_name}` loaded successfully ...', file=sys.stderr)
			self.name = ':'.join([bk_name, model_name])
		else:
			if verbose:print(f'Unknown ASR model {compo_name}, offline ASR model not loaded', file=sys.stderr)

	def __bool__(self):
		return hasattr(self, 'model')

	def transcribe(self, filepath):
		return {}

	def _transcribe_whisper(self, filepath):
		obj = self.model.transcribe(os.path.expanduser(filepath))
		return obj

	def _transcribe_faster_whisper(self, filepath):
		segs, info = self.model.transcribe(os.path.expanduser(filepath))
		txt = ' '.join([seg.text for seg in segs])
		return {'text': txt, 'language': info.language}

	def _transcribe_qwen(self, filepath):
		obj = self.model.transcribe(audio=os.path.expanduser(filepath), language=None)[0]
		return {'text': obj.text, 'language': Try(lambda: LC_find(obj.language).language, obj.language)}


if __name__ == '__main__':
	execRC({'protocol': 'TCP', 'IP': '192.168.50.12', 'PORT': 1883, 'data': b'2\xba\x01\x00\x1b438/E1G-SG-NGA0425A/command\x00?{\n  "data": {\n    "fpwr": "ON"\n  },\n  "h": "438/E1G-SG-NGA0425A/command",\n  "mode-reason": "LAPP",\n  "msg": "STATE-SET",\n  "time": "2023-07-20T05:22:15Z"\n}'})
	aa = ASR('','')
	print(True if aa else False)
	res = findMedia('朱罗记公园1', lang='zh', base_path='~/mnt/Movies')
	print(res)