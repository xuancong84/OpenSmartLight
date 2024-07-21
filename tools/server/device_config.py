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

if os.path.isfile('secret.py'):
	from secret import *

SECRET_VARS = ['ASR_CLOUD_URL', 'CUSTOM_CMDLINES', 'HUBS']