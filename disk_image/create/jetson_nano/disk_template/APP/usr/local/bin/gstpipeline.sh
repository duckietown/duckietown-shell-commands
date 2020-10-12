#! /bin/bash

gst-launch-1.0 -v nvarguscamerasrc ! 'video/x-raw(memory:NVMM), format=NV12, width=3264, height=2464, framerate=20/1' ! nvvidconv ! 'video/x-raw, width=640, height=480, format=I420, framerate=20/1' ! videoconvert ! identity drop-allocation=1 ! 'video/x-raw, width=640, height=480, format=RGB, framerate=20/1' ! v4l2sink device=/dev/video2

