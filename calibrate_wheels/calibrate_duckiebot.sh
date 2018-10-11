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

docker -H "$DUCKIEBOT_NAME.local" stop ros-picam

echo "********************"
echo "To perform the wheel calibration, follow the steps described in the Duckiebook."
echo "http://docs.duckietown.org/DT18/opmanual_duckiebot/out/wheel_calibration.html"
echo "You will now be given a container running on the Duckiebot for wheel calibration."
read

docker -H "$DUCKIEBOT_NAME.local" run -it --net host --privileged  $IMAGE_BASE /bin/bash
