#!/usr/bin/env bash

DUCKIEBOT_NAME="$1"
DUCKIEBOT_IP="$2"

platform='unknown'
unamestr=$(uname)
if [[ "$unamestr" == 'Linux' ]]; then
   platform='linux'
elif [[ "$unamestr" == 'Darwin' ]]; then
   platform='macos'
fi

docker pull duckietown/rpi-gui-tools

if [[ $platform == 'linux' ]]; then
  xhost +
  docker run -it --net host --privileged --env ROS_MASTER=$DUCKIEBOT_NAME --env="DISPLAY" --env="QT_X11_NO_MITSHM=1" duckietown/rpi-gui-tools /bin/bash -c "echo $DUCKIEBOT_IP $DUCKIEBOT_NAME $DUCKIEBOT_NAME.local | sudo tee -a /etc/hosts && bash"
elif [[ $platform == 'macos' ]]; then
  IP=$(ifconfig en0 | grep inet | awk '$1=="inet" {print $2}')
  xhost +$IP
  docker run -it --net host --privileged --env ROS_MASTER=$DUCKIEBOT_NAME --env="QT_X11_NO_MITSHM=1" -e DISPLAY=$IP:0 -v /tmp/.X11-unix:/tmp/.X11-unix duckietown/rpi-gui-tools  /bin/bash -c "echo $DUCKIEBOT_IP $DUCKIEBOT_NAME $DUCKIEBOT_NAME.local | sudo tee -a /etc/hosts && bash"
fi
