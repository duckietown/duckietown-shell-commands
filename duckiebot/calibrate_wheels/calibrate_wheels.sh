#!/usr/bin/env bash

DUCKIEBOT_NAME="$1"
DUCKIEBOT_IP="$2"

IMAGE_CALIBRATION=duckietown/rpi-duckiebot-calibration:master18
IMAGE_BASE=duckietown/rpi-duckiebot-base:master18

docker pull $IMAGE_CALIBRATION
docker -H "$DUCKIEBOT_NAME.local" pull $IMAGE_BASE

if [[ $(docker -H "$DUCKIEBOT_NAME.local" inspect -f '{{.State.Running}}' 'ros-picam') == "true" ]]; then
   echo "********************"
   echo "ros-picam container is running, and will now be stopped"
   docker -H "$DUCKIEBOT_NAME.local" stop ros-picam
else 
   echo "********************"
   echo "ros-picam container was not already running"
fi
echo "********************"


echo "********************"
echo "To perform the wheel calibration, follow the steps described in the Duckiebook."
echo "http://docs.duckietown.org/DT18/opmanual_duckiebot/out/wheel_calibration.html"
echo "You will now be given a container running on the Duckiebot for wheel calibration (press enter):"
read

docker -H "$DUCKIEBOT_NAME.local" run -it --privileged -v /data:/data --net host $IMAGE_BASE /bin/bash
