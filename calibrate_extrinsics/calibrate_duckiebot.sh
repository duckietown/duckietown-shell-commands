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

if [ $(docker -H "$DUCKIEBOT_NAME.local" inspect -f '{{.State.Running}}' $ros-picam) = "true" ]; then 
   echo "ros-picam container is running, and will now be stopped"
   docker -H "$DUCKIEBOT_NAME.local" stop ros-picam
else 
   echo "ros-picam container was not already running"
fi

TIMESTAMP=$(date +%Y%m%d%H%M%S)
NAME="out-calibrate-extrinsics-$DUCKIEBOT_NAME-$TIMESTAMP"
#SNAME="out-simulation-$DUCKIEBOT_NAME-$TIMESTAMP"
VNAME="out-pipeline-$DUCKIEBOT_NAME-$TIMESTAMP"

echo "********************"
echo "Place the Duckiebot on the calibration patterns and press ENTER."
read
 
docker -H "$DUCKIEBOT_NAME.local" run -it  --privileged -v /data:/data --net host $IMAGE_BASE /bin/bash -c "source /home/software/docker/env.sh && rosrun complete_image_pipeline calibrate_extrinsics -o /data/$NAME > /data/$NAME.log"
 


#echo "Running Simulated Verification"


#docker -H "$DUCKIEBOT_NAME.local" run -it  --privileged -v /data:/data --net host duckietown/rpi-duckiebot-base /bin/bash -c "source /home/software/docker/env.sh && rosrun complete_image_pipeline validate_calibration -o /data/$SNAME > /data/$SNAME.log"


echo "********************"
echo "Place the Duckiebot in a lane and press ENTER."
read

docker -H "$DUCKIEBOT_NAME.local" run -it  --privileged -v /data:/data --net host $IMAGE_BASE /bin/bash -c "source /home/software/docker/env.sh && rosrun complete_image_pipeline single_image_pipeline -o /data/$VNAME > /data/$VNAME.log"

