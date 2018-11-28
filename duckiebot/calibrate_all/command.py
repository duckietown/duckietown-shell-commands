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

from utils.docker_utils import setup_local_data_volume


class DTCommand(DTCommandAbs):

    @staticmethod
    def command(shell, args):
        script_file = join(dirname(realpath(__file__)), 'calibrate_duckiebot.sh')

        from utils.networking_utils import get_duckiebot_ip

        prog = 'dts duckiebot calibrate_all DUCKIEBOT_NAME'
        usage = """
Calibrate: 

    %(prog)s
"""

        parser = argparse.ArgumentParser(prog=prog, usage=usage)
        parser.add_argument('hostname', default=None, help='Name of the Duckiebot to calibrate')
        parsed_args = parser.parse_args(args)

        duckiebot_ip = get_duckiebot_ip(parsed_args.hostname)
        script_cmd = '/bin/bash %s %s %s' % (script_file, parsed_args.hostname, duckiebot_ip)

        env = {}
        env.update(os.environ)
        V = 'DOCKER_HOST'
        if V in env:
            msg = 'I will ignore %s because the calibrate command knows what it\'s doing.' % V
            dtslogger.info(msg)
            env.pop(V)

        ret = call(script_cmd, shell=True, stdin=sys.stdin, stderr=sys.stderr, stdout=sys.stdout, env=env)

        if ret == 0:
            dtslogger.info('Successfully completed calibration!')
        else:
            msg = ('An error occurred while running the calibration procedure, please check and try again (%s).' % ret)
            raise Exception(msg)


def calibrate(duckiebot_name, duckiebot_ip):
    from duckiebot import calibrate_wheels, calibrate_extrinsics
    from utils.docker_utils import get_remote_client, DUCKIEBOT_BASE, IMAGE_CALIBRATION
    local_client = check_docker_environment()
    duckiebot_client = get_remote_client(duckiebot_ip)
    operating_system = platform.system()

    duckiebot_client.images.pull(DUCKIEBOT_BASE)
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

    calibrate_extrinsics.calibrate(duckiebot_name, duckiebot_ip)
    calibrate_wheels.calibrate(duckiebot_ip)
