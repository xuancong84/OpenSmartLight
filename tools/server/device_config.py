
# all fields must be set, if absent put ''
KTV_SPEAKER='10:3C:88:17:20:78'
KTV_SCREEN='livingTV'
MP3_SPEAKER='54:B7:E5:9E:F4:14'
MP4_SPEAKER=['hdmi', 'audio.stereo']
MIC_RECORDER='usb'
TMP_DIR='/dev/shm'
DEFAULT_RECORDING_FILE=f'{TMP_DIR}/speech.m4a'
DEFAULT_SPEECH_FILE=f'{TMP_DIR}/speak.mp3'
DEFAULT_CONFIG_FILE='.config.json'
LG_TV_CONFIG_FILE='~/.lgtv/config.json'
LG_TV_BIN='./miniconda3/bin/lgtv --ssl'
SHARED_PATH='~/Public'
DOWNLOAD_PATH=SHARED_PATH+'/Download'
MAX_WALK_LEVEL=2
ASR_CLOUD='http://203.149.235.62:8883/run_asr/base'
VOICE_VOL=60
CUSTOM_CMDLINES={'macair_play':"ssh hetianfang@192.168.50.31 /Applications/Firefox.app/Contents/MacOS/firefox --new-tab '\"http://192.168.50.3:8883/webPlay/-1/\"'"}
