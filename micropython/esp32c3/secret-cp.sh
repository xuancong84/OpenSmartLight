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

#pyboard -f cp secret9.py :secret.py

set +e
pyboard -f mkdir  codes
set -e

for f in main.py modules.py rescue.py lib*.py; do 
	mpy-cross $f
	fmpy=${f::-3}.mpy
	echo "Copying $fmpy ..."
	pyboard -f cp $fmpy :
done

pyboard -f cp rc-codes.txt :

set +e
pyboard -f mkdir  static
set -e

pyboard -f cp static/* :static/
pyboard -f cp ../*.tcp :
pyboard -f cp boot.py :

