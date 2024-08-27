#!/usr/bin/env python3
# This file contains non-UI-adjustable settings that configures your entire home setup

import os, sys
from collections import defaultdict

# all fields must be set, if absent put ''
KTV_SPEAKER='10:3C:88:17:20:78'
KTV_SCREEN='livingTV:HDMI_1'
MP3_SPEAKER='54:B7:E5:9E:F4:14'
MP4_SPEAKER=['hdmi', 'audio.stereo']
BLE_DEVICES=[{'name':'living room ceiling light player', 'MAC':'99:52:A0:B7:E8:8F'}]
MIC_RECORDER='usb'
TMP_DIR='/dev/shm'
DEFAULT_S2T_SND_FILE=f'{TMP_DIR}/speech.webm'
DEFAULT_T2S_SND_FILE=f'{TMP_DIR}/speak.mp3'
PLAYSTATE_FILE='.playstate.json.gz'
DRAMA_DURATION_TH=1200
LG_TV_CONFIG_FILE='~/.lgtv/config.json'
LG_TV_BIN='./miniconda3/bin/lgtv --ssl'
SHARED_PATH='~/Public'
DOWNLOAD_PATH=SHARED_PATH+'/Download'
MAX_WALK_LEVEL=2
ASR_CLOUD_URL='http://localhost:8883/run_asr/base'
ASR_CLOUD_TIMEOUT=8
VOICE_VOL=defaultdict(lambda: None, {None: 60})
STD_VOL_DBFS=-21
DEBUG_LOG = True
CUSTOM_CMDLINES={}
HUBS={}

ASRchip_voice_IP='http://192.168.50.4'
ASRchip_voice_hex = {
	'speak_drama': ('a5650a', 3.5),
	'speak_song': ('a5640a', 3),
	'asr_not_found': ('a5020a', 3),
	'asr_not_found_drama': ('a5020a', 3),
	'asr_not_found_file': ('a5020a', 3),
	'asr_found': ('a5000a', 3)
}

VOICE_CMD_FFWD_DCT = {
	'快进到': 'auto',
	'快进': 'auto',
	'电视机快进到': 'livingTV',
	'电视机快进': 'livingTV',
	'客厅电视机快进到': 'livingTV',
	'客厅电视机快进': 'livingTV',
	'播放器快进到': None,
	'播放器快进': None,
	'主人房电视机快进到': 'masterTV',
	'主人房电视机快进': 'masterTV',
	'客人房电视机快进到': 'commonTV',
	'客人房电视机快进': 'commonTV',
	
	'快退到': 'auto',
	'快退': 'auto',
	'电视机快退到': 'livingTV',
	'电视机快退': 'livingTV',
	'客厅电视机快退到': 'livingTV',
	'客厅电视机快退': 'livingTV',
	'播放器快退到': None,
	'播放器快退': None,
	'主人房电视机快退到': 'masterTV',
	'主人房电视机快退': 'masterTV',
	'客人房电视机快退到': 'commonTV',
	'客人房电视机快退': 'commonTV',
}

if os.path.isfile('secret.py'):
	from secret import *

SECRET_VARS = ['ASR_CLOUD_URL', 'CUSTOM_CMDLINES', 'HUBS']