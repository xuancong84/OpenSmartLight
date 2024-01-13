import os, sys, vlc, subprocess, random, time, threading

inst = vlc.Instance()
filelist = [L.strip() for L in open('/home/xuancong/test.m3u') if not L.startswith('#')]
#random.shuffle(filelist)
playlist = inst.media_list_new(filelist)
player = inst.media_list_player_new()
player.set_media_list(playlist)

mplayer=player.get_media_player()
event = vlc.EventType()
isFirst=True
isJustAfterBoot=False
em=mplayer.event_manager()

def show_subtitle(show=True):
	if show and mplayer.video_get_spu_count()>=2:
		mplayer.video_set_spu(2)
		print(f'Set subtitle = {show}', file=sys.stderr)

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
	threading.Timer(wait_tm+2, lambda:show_subtitle(True)).start()
	isFirst = False


em.event_attach(event.MediaPlayerOpening, keep_fullscreen)

player.play()
