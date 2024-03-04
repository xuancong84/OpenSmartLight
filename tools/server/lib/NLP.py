import os, sys, io, string, json, subprocess, yt_dlp
import pykakasi, pinyin, logging, requests, shutil
from unidecode import unidecode
from urllib.parse import unquote

from lib.ChineseNumber import *
from lib.settings import *
from device_config import *

KKS = pykakasi.kakasi()
filelist, cookies_opt = [], []
downloading_songs = {}
to_pinyin = lambda t: pinyin.get(t, format='numerical')
translit = lambda t: unidecode(t).lower()
get_alpha = lambda t: ''.join([c for c in t if c in string.ascii_letters])
get_alnum = lambda t: ''.join([c for c in t if c in string.ascii_letters+string.digits])
to_romaji = lambda t: ' '.join([its['hepburn'] for its in KKS.convert(t)])
ls_media_files = lambda fullpath: sorted([f'{fullpath}/{f}'.replace('//','/') for f in os.listdir(fullpath) if not f.startswith('.') and '.'+f.split('.')[-1] in media_file_exts])
ls_subdir = lambda fullpath: sorted([g.rstrip('/') for f in os.listdir(fullpath) for g in [f'{fullpath}/{f}'.replace('//','/')] if not f.startswith('.') and os.path.isdir(g)])


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


# For yt-dlp
def call_yt_dlp(argv, get_stdout = False):
	ret_code = 0
	if get_stdout:
		old_stdout = sys.stdout
		sys.stdout = io.StringIO()
	try:
		yt_dlp.main(argv)
	except SystemExit as e:
		ret_code = e.code
	if get_stdout:
		ret_stdout = sys.stdout
		sys.stdout = old_stdout
		return ret_stdout.getvalue()
	return ret_code

def get_yt_dlp_json(url):
	out_json = call_yt_dlp(['-j', url], True).strip()
	if not out_json.startswith('{'):
		out_json = out_json[out_json.find('{'):]
	return json.loads(out_json)

def get_video_file_basename(url):
	try:
		info_json = get_yt_dlp_json(url)
		filename = f"{info_json['title']}.{info_json['ext']}"
	except:
		logging.error("Error parsing video id from url: " + url)
		return get_alnum(url.split('//')[-1])+'.mp4'
	
	return filename

def download_video(song_url, include_subtitles, high_quality, redownload):
	logging.info("Downloading video: " + song_url)
	downloading_songs[song_url] = 1
	out_bn = get_video_file_basename(song_url)
	tmp_fn = os.path.expanduser(f'{DOWNLOAD_PATH}/tmp/{out_bn}')
	out_fn = os.path.expanduser(f'{DOWNLOAD_PATH}/{out_bn}')

	# If file already present, skip downloading
	if get_filesize(out_fn)==0 or redownload:
		opt_quality = ['-f', 'bestvideo[height<=1080]+bestaudio[abr<=160]'] if high_quality else ['-f', 'mp4+m4a']
		opt_sub = ['--sub-langs', 'all', '--embed-subs'] if include_subtitles else []
		cmd = ['--fixup', 'force', '--socket-timeout', '3', '-R', 'infinite', '--remux-video', 'mp4'] \
			+ cookies_opt + opt_quality + ["-o", tmp_fn] + opt_sub + [song_url]
		logging.info("Youtube-dl command: " + " ".join(cmd))
		rc = call_yt_dlp(cmd)
		if get_filesize(tmp_fn)==0:
			logging.error("Error code while downloading, retrying without format options ...")
			cmd = ["-o", tmp_fn, '--socket-timeout', '3', '-R', 'infinite'] + [song_url]
			logging.debug("Youtube-dl command: " + " ".join(cmd))
			rc = call_yt_dlp(cmd)
		if get_filesize(tmp_fn):
			logging.debug("Song successfully downloaded: " + song_url)
			shutil.move(tmp_fn, out_fn)
			downloading_songs[song_url] = 0
		else:
			logging.error("Error downloading song: " + song_url)
			downloading_songs[song_url] = -1

	return out_fn if get_filesize(out_fn) else ''
