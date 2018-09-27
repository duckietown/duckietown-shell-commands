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
docker -H "$DUCKIEBOT_NAME.local" pull duckietown/rpi-duckiebot-base

if [[ $platform == 'linux' ]]; then
  xhost +
  docker run -it --net host -v $HOME/data:/data --privileged --env ROS_MASTER=$DUCKIEBOT_NAME --env DUCKIEBOT_NAME=$DUCKIEBOT_NAME --env DUCKIEBOT_IP=$DUCKIEBOT_IP --env="DISPLAY" --env QT_X11_NO_MITSHM=1 duckietown/rpi-duckiebot-calibration
elif [[ $platform == 'macos' ]]; then
  IP=$(ifconfig en0 | grep inet | awk '$1=="inet" {print $2}')
  xhost +$IP
  docker run -it --net host -v $HOME/data:/data --privileged --env ROS_MASTER=$DUCKIEBOT_NAME --env DUCKIEBOT_NAME=$DUCKIEBOT_NAME --env DUCKIEBOT_IP=$DUCKIEBOT_IP --env QT_X11_NO_MITSHM=1 -e DISPLAY=$IP:0 -v /tmp/.X11-unix:/tmp/.X11-unix duckietown/rpi-duckiebot-calibration
fi

docker -H "$DUCKIEBOT_NAME.local" stop ros-picam

TIMESTAMP=$(date +%Y%m%d%H%M%S)
NAME="out-calibrate-extrinsics-$TIMESTAMP"
VNAME="out-pipeline-$TIMESTAMP"

echo "********************"
echo "Place the Duckiebot on the calibration patterns and press ENTER."
read

docker -H "$DUCKIEBOT_NAME.local" run -it  --privileged -v /data:/data --net host duckietown/rpi-duckiebot-base /bin/bash -c "source /home/software/docker/env.sh && rosrun complete_image_pipeline calibrate_extrinsics -o /data/$NAME > /data/$NAME.log"
rosrun calibrate_extrinsics -o /data/$NAME > /data/$NAME.log

echo "********************"
echo "Place the Duckiebot in a lane and press ENTER."
read

docker -H "$DUCKIEBOT_NAME.local" run -it  --privileged -v /data:/data --net host duckietown/rpi-duckiebot-base /bin/bash -c "source /home/software/docker/env.sh && rosrun complete_image_pipeline single_image_pipeline -o /data/$VNAME > /data/$VNAME.log"

echo "********************"
echo "To perform the wheel calibration, follow the steps described in the Duckiebook."
echo "http://docs.duckietown.org/DT18/opmanual_duckiebot/out/wheel_calibration.html"
echo "You will now be given a container running on the Duckiebot for wheel calibration."
read

docker -H "$DUCKIEBOT_NAME.local" run -it --net host --privileged  duckietown/rpi-duckiebot-base /bin/bash
