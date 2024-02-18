#!/usr/bin/env bash

INPATH=./mp3_in
OUTPATH=../server/voice

cd "`dirname $0`"

objs=(asr_error 1018 \
asr_fail 1006 \
asr_found_drama 1026 \
asr_found_movie 1025 \
asr_found 1004 \
asr_not_found_drama 1027 \
asr_not_found 1019 \
offline_asr_not_available 1022 \
playlist_empty 1020 \
processing 1009 \
speak_drama 1024 \
speak_song 1008 \
unfinished_offline_asr 1023 \
wait_for_asr 1021 \
cur_song_title 11111
)

need_pad=' 1027 1026 '

for i in `seq 0 2 $[${#objs[@]}-1]`; do
	fin="`ls $INPATH/\[${objs[i+1]}\]*.mp3`"
	fout="$OUTPATH/${objs[i]}.mp3"
	ffmpeg -y -i "$fin" -af "adelay=300ms:all=true" "$fout"
	if [[ $need_pad == *${objs[i+1]}* ]]; then
		mv "$fout" "$fout.mp3"
		ffmpeg -y -i "$fout.mp3" -af "apad=pad_dur=200ms" "$fout"
	fi
	#wget -O /dev/null "http://192.168.50.3:8883/tv_runjs?masterTV/play_audio('/voice/`basename $fout`')"
	#sleep 5
done

