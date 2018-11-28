from __future__ import print_function

import argparse
import os
import platform
import subprocess
import sys
from os.path import join, realpath, dirname
from subprocess import call

from dt_shell import DTCommandAbs, dtslogger
from dt_shell.env_checks import check_docker_environment

from utils.cli_utils import get_clean_env, start_command_in_subprocess
from utils.docker_utils import setup_local_data_volume


class DTCommand(DTCommandAbs):

    @staticmethod
    def command(shell, args):
        script_file = join(dirname(realpath(__file__)), 'calibrate_duckiebot.sh')

        prog = 'dts duckiebot calibrate_intrinsics DUCKIEBOT_NAME'
        usage = """
Calibrate: 

    %(prog)s
"""
        from utils.networking_utils import get_duckiebot_ip

        parser = argparse.ArgumentParser(prog=prog, usage=usage)
        parser.add_argument('hostname', default=None, help='Name of the Duckiebot to calibrate')
        parsed_args = parser.parse_args(args)

        duckiebot_ip = get_duckiebot_ip(parsed_args.hostname)
        # shell.calibrate(duckiebot_name=args[0], duckiebot_ip=duckiebot_ip)
        script_cmd = '/bin/bash %s %s %s' % (script_file, parsed_args.hostname, duckiebot_ip)

        env = get_clean_env()
        ret = start_command_in_subprocess(script_cmd, env)

        if ret == 0:
            print('Done!')
        else:
            msg = ('An error occurred while running the calibration procedure, please check and try again (%s).' % ret)
            raise Exception(msg)


def calibrate(duckiebot_name, duckiebot_ip):
    import docker
    local_client = check_docker_environment()
    duckiebot_client = docker.DockerClient('tcp://' + duckiebot_ip + ':2375')
    operating_system = platform.system()

    IMAGE_CALIBRATION = 'duckietown/rpi-duckiebot-calibration:master18'
    IMAGE_BASE = 'duckietown/rpi-duckiebot-base:master18'

    duckiebot_client.images.pull(IMAGE_BASE)
    local_client.images.pull(IMAGE_CALIBRATION)

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
                                    volumes=setup_local_data_volume(),
                                    privileged=True,
                                    environment=env_vars)
    if operating_system == 'Darwin':
        IP = subprocess.check_output(['/bin/sh', '-c', 'ifconfig en0 | grep inet | awk \'$1=="inet" {print $2}\''])
        env_vars['IP'] = IP
        call(["xhost", "+IP"])
        local_client.containers.run(image=IMAGE_CALIBRATION,
                                    network_mode='host',
                                    volumes=setup_local_data_volume(),
                                    privileged=True,
                                    environment=env_vars)

    duckiebot_client.containers.get('ros-picam').stop()
