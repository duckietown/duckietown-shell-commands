from __future__ import print_function

import subprocess
import sys
from os.path import join, realpath, dirname

import docker
from os.path import expanduser
import platform
from subprocess import call
from dt_shell import DTCommandAbs

from utils.networking import get_duckiebot_ip


class DTCommand(DTCommandAbs):

    @staticmethod
    def command(shell, args):
        script_file = join(dirname(realpath(__file__)), 'calibrate_duckiebot.sh')

        if len(args) < 1:
            raise Exception('Usage: calibrate <DUCKIEBOT_NAME_GOES_HERE>')

        duckiebot_ip = get_duckiebot_ip(args[0])
        #shell.calibrate(duckiebot_name=args[0], duckiebot_ip=duckiebot_ip)
        script_cmd = '/bin/bash %s %s %s' % (script_file, args[0], duckiebot_ip)

        ret = call(script_cmd, shell=True, stdin=sys.stdin, stderr=sys.stderr, stdout=sys.stdout)
        # process.communicate()
        if ret == 0:
            print('Done!')
        else:
            msg = ('An error occurred while running the calibration procedure, please check and try again (%s).' % ret)
            raise Exception(msg)

    def calibrate(self, duckiebot_name, duckiebot_ip):
        local_client = docker.from_env()
        duckiebot_client = docker.DockerClient()
        operating_system = platform.system()

        duckiebot_client.images.pull('duckietown/rpi-duckiebot-base')
        local_client.images.pull('duckietown/rpi-duckiebot-calibration')
        user_home = expanduser("~")
        datavol = {'%s/data' % user_home: {'bind':'/data'}}

        env_vars = {
            'ROS_MASTER': duckiebot_name,
            'DUCKIEBOT_NAME': duckiebot_name,
            'DUCKIEBOT_IP': duckiebot_ip,
            'QT_X11_NO_MITSHM': True
        }

        if operating_system == 'Linux':
            call(["xhost", "+"])
            local_client.containers.run(image='duckietown/rpi-duckiebot-calibration',
                                        network_mode='host',
                                        volumes=datavol,
                                        privileged=True)
        if operating_system == 'Darwin':
            call(["xhost", "+IP"])


