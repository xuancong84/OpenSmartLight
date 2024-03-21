import os, sys, io, time, string, json, threading, yt_dlp
import pykakasi, pinyin, logging, requests, shutil
from unidecode import unidecode
from urllib.parse import unquote
from werkzeug import local

from lib.ChineseNumber import *
from lib.settings import *
from device_config import *

KKS = pykakasi.kakasi()
filelist, cookies_opt = [], []
Open = lambda t, *args: open(os.path.expandvars(os.path.expanduser(t)), *args)
listdir = lambda t: os.listdir(os.path.expandvars(os.path.expanduser(t)))
showdir = lambda t: [(p+'/' if os.path.isdir(t+p) else p) for p in sorted(listdir(t)) if not p.startswith('.')]
to_pinyin = lambda t: pinyin.get(t, format='numerical')
translit = lambda t: unidecode(t).lower()
get_alpha = lambda t: ''.join([c for c in t if c in string.ascii_letters])
get_alnum = lambda t: ''.join([c for c in t if c in string.ascii_letters+string.digits])
to_romaji = lambda t: ' '.join([its['hepburn'] for its in KKS.convert(t)])
ls_media_files = lambda fullpath: sorted([f'{fullpath}/{f}'.replace('//','/') for f in listdir(fullpath) if not f.startswith('.') and '.'+f.split('.')[-1] in media_file_exts])
ls_subdir = lambda fullpath: sorted([g.rstrip('/') for f in listdir(fullpath) for g in [f'{fullpath}/{f}'.replace('//','/')] if not f.startswith('.') and os.path.isdir(g)])
mrl2path = lambda t: unquote(t).replace('file://', '').strip() if t.startswith('file://') else (t.strip() if t.startswith('/') else '')
is_json_lst = lambda s: s.startswith('["') and s.endswith('"]')
load_m3u = lambda fn: [i for L in Open(fn).readlines() for i in [mrl2path(L)] if i]
get_url_root = lambda r: r.url_root.rstrip('/') if r.url_root.count(':')>=2 else r.url_root.rstrip('/')+f':{r.server[1]}'


def Try(fn, default=None):
	try:
		return fn()
	except Exception as e:
		return str(e) if default=='ERROR_MSG' else default

get_filesize = lambda fn: Try(lambda: os.path.getsize(fn), 0)

def fuzzy(txt, dct=FUZZY_PINYIN):
	for src, tgt in dct.items():
		txt = txt.replace(src, tgt)
	return txt


def str_search(name, name_list):
	# 1. exact full match
	if name in name_list:
		return [ii for ii,name1 in enumerate(name_list) if name==name1]

	# 2. exact substring match
	res = [[ii, len(it)-len(name)] for ii,it in enumerate(name_list) if name in it]
	return [it[0] for it in sorted(res, key=lambda t:t[1])] if res else []


def filepath2songtitle(fn):
	s = os.path.basename(unquote(fn).rstrip('/')).split('.')[0].strip()
	return os.path.basename(os.path.dirname(unquote(fn).rstrip('/')))+s if s.isdigit() else s


def findSong(name, lang=None, flist=filelist, unique=False):
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


def findMedia(name, lang=None, stack=0, stem=None, episode=None, base_path=SHARED_PATH):
	if episode == None:
		stem = name
		episode = ''
		if lang=='zh' and stem.endswith('集'):
			stem = stem[:-1]
		while stem[-1].isdigit() or (lang=='zh' and stem[-1] in NORMAL_CN_NUMBER):
			episode = stem[-1] + episode
			stem = stem[:-1]
		if lang=='zh' and stem.endswith('第'):
			stem = stem[:-1]
		episode = Try(lambda: int(episode if episode.isdigit() else zh2num(episode)), '')
	f_lst = ls_media_files(base_path)
	d_lst = ls_subdir(base_path)
	lst = f_lst+d_lst
	res = findSong(name, lang, lst)
	if res==None and name!=stem:
		res = findSong(stem, lang, lst)
	if res!=None:
		item = lst[res]
		if os.path.isfile(item):
			return item
		lst2 = ls_media_files(item)
		res = findSong(name, lang, lst2, True)	# full match takes precedence
		if res!=None:
			return (item, res)
		if episode and len(lst2)>=episode:
			return (item, episode-1)
		return item
	if stack<MAX_WALK_LEVEL:
		for d in d_lst:
			res = findMedia(name, lang, stack+1, stem, episode, d)
			if res != None:
				return res
	return None


# For getting thread's STDIO
orig___stdout__ = sys.__stdout__
orig___stderr__ = sys.__stderr__
orig_stdout = sys.stdout
orig_stderr = sys.stderr
thread_proxies = {}

def redirect(thread_id=None):
	"""
	Enables the redirect for the current thread's output to a single StringIO
	object and returns the object.

	:return: The StringIO object.
	:rtype: ``io.StringIO``
	"""
	# Use the current thread's identity if not given
	ident = thread_id or threading.currentThread().ident

	# Enable the redirect and return the StringIO object.
	thread_proxies[ident] = io.StringIO()
	return thread_proxies[ident]

def stop_redirect(thread_id=None):
	"""
	Enables the redirect for the current thread's output to a single StringIO
	object and returns the object.

	:return: The final string value.
	:rtype: ``str``
	"""
	# Use the current thread's identity if not given
	ident = thread_id or threading.currentThread().ident
	return thread_proxies.pop(ident, None)

def _get_stream(original):
	"""
	Returns the inner function for use in the LocalProxy object.

	:param original: The stream to be returned if thread is not proxied.
	:type original: ``file``
	:return: The inner function for use in the LocalProxy object.
	:rtype: ``function``
	"""
	def proxy():
		"""
		Returns the original stream if the current thread is not proxied,
		otherwise we return the proxied item.

		:return: The stream object for the current thread.
		:rtype: ``file``
		"""
		# Get the current thread's identity.
		ident = threading.currentThread().ident

		# Return the proxy, otherwise return the original.
		return thread_proxies.get(ident, original)

	# Return the inner function.
	return proxy

def enable_proxy():
	# Overwrites __stdout__, __stderr__, stdout, and stderr with the proxied objects.
	sys.__stdout__ = local.LocalProxy(_get_stream(orig___stdout__))
	sys.__stderr__ = local.LocalProxy(_get_stream(orig___stderr__))
	sys.stdout = local.LocalProxy(_get_stream(orig_stdout))
	sys.stderr = local.LocalProxy(_get_stream(orig_stderr))

def disable_proxy():
	# Overwrites __stdout__, __stderr__, stdout, and stderr with the original
	sys.__stdout__ = orig___stdout__
	sys.__stderr__ = orig___stderr__
	sys.stdout = orig_stdout
	sys.stderr = orig_stderr


# For yt-dlp
def parse_outfn(L):
	out_fn = ''
	for L1 in L.splitlines():
		if L1.startswith('[download] ') and L1.endswith(' has already been downloaded'):
			out_fn = L1[11:-28]
		if L1.startswith('[Merger] Merging formats into '):
			out_fn = L1[30:].strip().strip('"')
	return out_fn

def call_yt_dlp(argv, mobile_ip):
	out_fn = ''
	thread = threading.Thread(target=lambda: yt_dlp.main(argv))
	thread.start()
	while thread.ident==None:pass
	tid = thread.ident
	sio = redirect(tid)
	while thread.is_alive():
		time.sleep(1)
		L = sio.getvalue()
		if not L: continue
		sys.stdout.write(L)
		Try(lambda: os.ip2ydsock[mobile_ip].send(L))
		out_fn = parse_outfn(L) or out_fn
		sio.truncate(0)
		sio.seek(0)

	return out_fn or parse_outfn(sio.getvalue())

def download_video(song_url, include_subtitles, high_quality, redownload, mobile_ip):
	logging.info("Downloading video: " + song_url)
	tmp_dir = os.path.expanduser(f'{DOWNLOAD_PATH}/tmp/')

	# If file already present, skip downloading
	opt_quality = ['-f', 'bestvideo[height<=1080]+bestaudio[abr<=160]'] if high_quality else ['-f', 'mp4+m4a']
	opt_sub = ['--sub-langs', 'all', '--embed-subs'] if include_subtitles else []
	cmd = ['--fixup', 'force', '--socket-timeout', '3', '-R', 'infinite'] \
		+ cookies_opt + opt_quality + opt_sub + (['--force-overwrites'] if redownload else []) \
		+ ["-o", tmp_dir+"%(title)s.%(ext)s"] + [song_url]
	logging.info("Youtube-dl command: " + " ".join(cmd))
	out_fn = call_yt_dlp(cmd, mobile_ip)
	if not out_fn:
		logging.error("Error code while downloading, retrying without format options ...")
		cmd = ['--socket-timeout', '3', '-R', 'infinite', '-P', tmp_dir] + [song_url]
		logging.debug("Youtube-dl command: " + " ".join(cmd))
		out_fn = call_yt_dlp(cmd, mobile_ip)
	if get_filesize(out_fn):
		logging.debug("Song successfully downloaded: " + song_url)
		ret_fn = os.path.expanduser(DOWNLOAD_PATH)+'/'+os.path.basename(out_fn)
		shutil.move(out_fn, ret_fn)
		return ret_fn
	else:
		logging.error("Error downloading song: " + song_url)

	return ''
