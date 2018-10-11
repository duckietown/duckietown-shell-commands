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
 
IMAGE_CALIBRATION=duckietown/rpi-duckiebot-calibration:master18
IMAGE_BASE=duckietown/rpi-duckiebot-base:master18

docker pull $IMAGE_CALIBRATION
docker -H "$DUCKIEBOT_NAME.local" pull $IMAGE_BASE

if [[ $platform == 'linux' ]]; then
  xhost +
  docker run -it --net host -v /data:/data --privileged --env ROS_MASTER=$DUCKIEBOT_NAME --env DUCKIEBOT_NAME=$DUCKIEBOT_NAME --env DUCKIEBOT_IP=$DUCKIEBOT_IP --env="DISPLAY" --env QT_X11_NO_MITSHM=1 $IMAGE_CALIBRATION
elif [[ $platform == 'macos' ]]; then
  IP=$(ifconfig en0 | grep inet | awk '$1=="inet" {print $2}')
  xhost +$IP
  docker run -it --net host -v $HOME/data:/data --privileged --env ROS_MASTER=$DUCKIEBOT_NAME --env DUCKIEBOT_NAME=$DUCKIEBOT_NAME --env DUCKIEBOT_IP=$DUCKIEBOT_IP --env QT_X11_NO_MITSHM=1 -e DISPLAY=$IP:0 -v /tmp/.X11-unix:/tmp/.X11-unix $IMAGE_CALIBRATION
 
fi

docker -H "$DUCKIEBOT_NAME.local" stop ros-picam
