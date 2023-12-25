#!/bin/bash


export PATH=`dirname $0`/miniconda3/bin:$PATH

if [ -s secret.sh ]; then
	source secret.sh
fi

#deebot-t8 login --username $USERNAME --password PASSWORD --country sg --continent as
deebot-t8 device "$@"
