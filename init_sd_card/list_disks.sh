#!/usr/bin/env sh

lsblk -p --output NAME,TYPE,SIZE,VENDOR | grep --color=never 'disk\|TYPE'
