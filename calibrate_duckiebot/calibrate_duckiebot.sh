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

docker pull duckietown/rpi-duckiebot-calibration

if [[ $platform == 'linux' ]]; then
  xhost +
  docker run -it --net host -v /data:/data --privileged --env ROS_MASTER=$DUCKIEBOT_NAME --env DUCKIEBOT_NAME=$DUCKIEBOT_NAME --env DUCKIEBOT_IP=$DUCKIEBOT_IP --env="DISPLAY" --env QT_X11_NO_MITSHM=1 duckietown/rpi-duckiebot-calibration
elif [[ $platform == 'macos' ]]; then
  IP=$(ifconfig en0 | grep inet | awk '$1=="inet" {print $2}')
  xhost +$IP
  docker run -it --net host -v /data:~/data --privileged --env ROS_MASTER=$DUCKIEBOT_NAME --env DUCKIEBOT_NAME=$DUCKIEBOT_NAME --env DUCKIEBOT_IP=$DUCKIEBOT_IP --env QT_X11_NO_MITSHM=1 -e DISPLAY=$IP:0 -v /tmp/.X11-unix:/tmp/.X11-unix duckietown/rpi-duckiebot-calibration
fi
