#!/usr/bin/env bash

# TODO: Complete migration to command.py, just need to verify it works on the Duckiebot

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


echo "********************"
echo "To perform the wheel calibration, follow the steps described in the Duckiebook."
echo "http://docs.duckietown.org/DT18/opmanual_duckiebot/out/wheel_calibration.html"
echo "You will now be given a container running on the Duckiebot for wheel calibration."
read

docker -H "$DUCKIEBOT_NAME.local" run -it --net host --privileged  $IMAGE_BASE /bin/bash

