#!/usr/bin/env bash

if [ -z "$1" ]; then
    echo "No Duckiebot name received, aborting!"
    exit 1
fi

echo "$1.local"

DUCKIEBOT_IP=$(ping -c1 "$1.local" | grep -oP 'PING.*?\(\K[^)]+')
MDNS_ALIAS="$1.local"

if [ -z "$DUCKIEBOT_IP" ]; then
    DUCKIEBOT_IP=$(ping -c1 $1 | grep -oP 'PING.*?\(\K[^)]+')
    MDNS_ALIAS="$1"
fi

if [ -z "$DUCKIEBOT_IP" ]; then
    echo "Unable to locate locate $1, aborting!"
    exit 1
fi

platform='unknown'
unamestr=$(uname)
if [[ "$unamestr" == 'Linux' ]]; then
   platform='linux'
elif [[ "$unamestr" == 'Darwin' ]]; then
   platform='macos'
fi

if [[ $platform == 'linux' ]]; then
  xhost +
  docker run -it --net host --privileged --env ROS_MASTER=$MDNS_ALIAS --env="DISPLAY" --env="QT_X11_NO_MITSHM=1" duckietown/rpi-gui-tools /bin/bash -c "echo $DUCKIEBOT_IP $MDNS_ALIAS | sudo tee -a /etc/hosts && bash"
elif [[ $platform == 'macos' ]]; then
  IP=$(ifconfig en0 | grep inet | awk '$1=="inet" {print $2}')
  xhost +$IP
  docker run -it --net host --privileged --env ROS_MASTER=$MDNS_ALIAS --env="QT_X11_NO_MITSHM=1" -e DISPLAY=$IP:0 -v /tmp/.X11-unix:/tmp/.X11-unix duckietown/rpi-gui-tools  /bin/bash -c "echo $DUCKIEBOT_IP $MDNS_ALIAS | sudo tee -a /etc/hosts && bash"
fi
