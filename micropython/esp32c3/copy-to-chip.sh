#!/usr/bin/env bash

set -e


if [ -e /dev/ttyUSB* ]; then
	export dev=`echo /dev/ttyUSB*`
elif [ -e /dev/tty.wchusbs* ]; then
	export dev=`echo /dev/tty.wchusbs*`
elif [ -e /dev/tty.usbserial-* ]; then
	export dev=`echo /dev/tty.usbserial*`
elif [ -e /dev/tty.usbm* ]; then
	export dev=`echo /dev/tty.usbm*`
elif [ -e /dev/ttyACM* ]; then
	export dev=`echo /dev/ttyACM*`
elif [ -e /dev/ttyACM* ]; then
	export dev=`echo /dev/ttyACM*`
else
	echo 'Error: no device found in /dev/ttyUSB* or /dev/ttyACM*'
	exit 1
fi

pyboard() {
	~/anaconda3/bin/python ~/bin/pyboard.py --device $dev -b 115200 "$@"
}

copy_if() {
	for f in "$@"; do
		if [ -s "$f" ]; then
			pyboard -f cp "$f" :"$f"
		fi
	done
}

copy2root_if() {
	for f in "$@"; do
		if [ -s "$f" ]; then
			pyboard -f cp "$f" :
		fi
	done
}

mpy-cross ../microWebSrv.py
pyboard -f cp ../microWebSrv.mpy :

for f in main.py modules.py rescue.py lib*.py; do 
	mpy-cross $f
	fmpy=${f::-3}.mpy
	echo "Copying $fmpy ..."
	copy_if $fmpy
done

if ! pyboard -f ls static/; then
	set +e
	pyboard -f mkdir  static
	set -e
fi

copy_if static/*
copy_if *.tcp
copy_if webrepl_cfg.py
copy_if secret.py

for arg in "$@"; do
	if [ -d "$arg" ]; then
		copy2root_if $arg/*
	elif [ -f "$arg" ]; then
		copy_if "$arg"
	fi
done

copy_if boot.py
