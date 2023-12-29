import os, sys, vlc, subprocess, random, time, threading
inst = vlc.Instance()
filelist = [L.strip() for L in open('/home/xuancong/Desktop/videos.m3u') if not L.startswith('#')]
random.shuffle(filelist)
playlist = inst.media_list_new(filelist)
player = inst.media_list_player_new()
player.set_media_list(playlist)

p=player.get_media_player()
event = vlc.EventType()
isFirst=True
em=p.event_manager()

def cb_tmadv(ev):
	em.event_detach(event.MediaPlayerTimeChanged)
	p.set_fullscreen(True)
	print('b')

em.event_attach(event.MediaPlayerOpening, lambda t:(threading.Timer(.8, lambda:p.set_fullscreen(False)).start(),
													threading.Timer(1.0, lambda:p.set_fullscreen(True)).start()))

player.play()
