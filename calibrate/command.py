from __future__ import print_function

import os
import platform
import sys
from os.path import join, realpath, dirname, expanduser
from subprocess import call

from dt_shell import DTCommandAbs, dtslogger
from utils.networking import get_duckiebot_ip


class DTCommand(DTCommandAbs):

    @staticmethod
    def command(shell, args):
        script_file = join(dirname(realpath(__file__)), 'calibrate_duckiebot.sh')

        if len(args) < 1:
            raise Exception('Usage: calibrate <DUCKIEBOT_NAME_GOES_HERE>')

        duckiebot_ip = get_duckiebot_ip(args[0])
        # shell.calibrate(duckiebot_name=args[0], duckiebot_ip=duckiebot_ip)
        script_cmd = '/bin/bash %s %s %s' % (script_file, args[0], duckiebot_ip)

        env = {}
        env.update(os.environ)
        V = 'DOCKER_HOST'
        if V in env:
            msg = 'I will ignore %s because the calibrate command knows what it\'s doing.' % V
            dtslogger.info(msg)
            env.pop(V)

        ret = call(script_cmd, shell=True, stdin=sys.stdin, stderr=sys.stderr, stdout=sys.stdout, env=env)

        if ret == 0:
            print('Done!')
        else:
            msg = ('An error occurred while running the calibration procedure, please check and try again (%s).' % ret)
            raise Exception(msg)

    def calibrate(self, duckiebot_name, duckiebot_ip):
        import docker
        local_client = docker.from_env()
        duckiebot_client = docker.DockerClient()
        operating_system = platform.system()

        IMAGE_CALIBRATION = 'duckietown/rpi-duckiebot-calibration:master18'
        IMAGE_BASE = 'duckietown/rpi-duckiebot-base:master18'

        duckiebot_client.images.pull(IMAGE_BASE)
        local_client.images.pull(IMAGE_CALIBRATION)
        user_home = expanduser("~")
        datavol = {'%s/data' % user_home: {'bind': '/data'}}

        env_vars = {
            'ROS_MASTER': duckiebot_name,
            'DUCKIEBOT_NAME': duckiebot_name,
            'DUCKIEBOT_IP': duckiebot_ip,
            'QT_X11_NO_MITSHM': True
        }

        if operating_system == 'Linux':
            call(["xhost", "+"])
            local_client.containers.run(image=IMAGE_CALIBRATION,
                                        network_mode='host',
                                        volumes=datavol,
                                        privileged=True)
        if operating_system == 'Darwin':
            call(["xhost", "+IP"])
