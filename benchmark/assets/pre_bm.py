#!/usr/bin/env python

"""Benchmark file run on the resp. duckiebot"""
import subprocess
import os
import io
import picamera
import json
import sys

CONTENT_SIZE = 512 #in KB min by elinux.org = 512K
COUNT_PER_ROUND = 512
NO_TESTS = 16
TEST_FN = 'test.tmp'
SD_OUT_FN = 'sd_speed.json'
META_OUT_FN = 'meta.json'
CONTAINERS = ['dt18_03_roscore_duckiebot-interface_1']

def log(s):
    """logs s in order to facilitate the readout via parmiko"""
    sys.stdout.write(s + "\n")
    sys.stdout.flush()

def subprocess_cmd(command):
    """runs command locally"""
    proc = subprocess.Popen([command], stderr=subprocess.PIPE, stdout=subprocess.PIPE, shell=True)
    return proc.communicate()[1].decode("utf-8") 


def stopContainers():
    """stop all docker containters"""
    for cont in CONTAINERS:
        subprocess_cmd("docker container stop " + cont)

def startContainers():
    """starts all docker containters"""
    for cont in CONTAINERS:
        subprocess_cmd("docker container start " + cont)


def sd_speed():
    """measures the read/write-speed of the current device and saves the result in resp. json"""
    def speed2int(speed):
        speed_no = float(speed[:4])
        if speed[-4] == 'G':
            speed_no*=1024
        return int(speed_no)
    
    log("Starting SD-Card speed check")

    read = []
    write = []
    for i in range(NO_TESTS):
        with open(TEST_FN, 'w') as file:
            test_file = os.path.join(os.getcwd(), TEST_FN)

            # read from dummy disk
            proc = subprocess_cmd('sync; dd if=/dev/zero of=%s bs=%sK count=%s'%(test_file, CONTENT_SIZE, COUNT_PER_ROUND))
            speed = proc[-10:-1]
            log('%s/%s, READ: %s'%(i+1, NO_TESTS, speed))
            
            read.append(speed2int(speed))

            # disable caching
            proc = subprocess_cmd('sync; echo 3 | sudo tee /proc/sys/vm/drop_caches')
            # write to dummy disk
            proc = subprocess_cmd('sync; dd if=%s of=/dev/zero bs=%sK count=%s'%(test_file, CONTENT_SIZE, COUNT_PER_ROUND))
            speed = proc[-10:-1]
            log('%s/%s, WRITE: %s'%(i+1, NO_TESTS, speed))
            write.append(speed2int(speed))

            # clean up
            subprocess_cmd('rm %s'%test_file)

    with open(SD_OUT_FN, 'w') as file:
        file.write(json.dumps({'read':read, 'write':write}))

def meta():
    """collects meta data from the autobot"""
    log("Collecting meta")
    meta = {}
    meta['pi_serial_no'] = subprocess_cmd('cat /proc/cpuinfo | grep ^Serial | cut -d":" -f2').strip()
    meta['pi_revision'] = subprocess_cmd('cat /proc/cpuinfo | grep ^Revision | cut -d":" -f2').strip()
    meta['pi_hardware'] = subprocess_cmd('cat /proc/cpuinfo | grep ^Hardware | cut -d":" -f2').strip()

    with picamera.PiCamera() as cam:
        meta['cam_revisison'] = str(cam.revision)
        meta['cam_framerate_range'] = str(cam.framerate_range)
        meta['cam_analog_gain'] = str(cam.analog_gain)
        meta['cam_brightness'] = str(cam.brightness)
        meta['cam_contrast'] = str(cam.contrast)
        meta['cam_sensor_mode'] = str(cam.sensor_mode)
        meta['cam_exposure_speed'] = str(cam.exposure_speed)

    with open(META_OUT_FN, 'w') as file:
        file.write(json.dumps(meta))


if __name__ == "__main__":
    sd_speed()
    stopContainers()
    meta()
    startContainers()

# run command
# dts devel build -f --arch amd64; and docker run -v /home/lujobi/data/:/data -e OUTFILE=out.json -it --rm duckietown/bm-preliminary-test:v1-amd64
