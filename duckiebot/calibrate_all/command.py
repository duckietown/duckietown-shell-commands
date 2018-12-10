from __future__ import print_function

import argparse
import platform
import subprocess
from os.path import join, realpath, dirname
from subprocess import call

from dt_shell import DTCommandAbs, dtslogger
from dt_shell.env_checks import check_docker_environment

from utils.cli_utils import get_clean_env, start_command_in_subprocess
from utils.docker_utils import bind_local_data_dir, default_env


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

        env = get_clean_env()

        ret = start_command_in_subprocess(script_cmd, env)

        if ret == 0:
            dtslogger.info('Successfully completed calibration!')
        else:
            msg = ('An error occurred while running the calibration procedure, please check and try again (%s).' % ret)
            raise Exception(msg)


def calibrate(duckiebot_name, duckiebot_ip):
    from duckiebot import calibrate_wheels, calibrate_extrinsics
    from utils.docker_utils import get_remote_client, RPI_DUCKIEBOT_BASE, RPI_DUCKIEBOT_CALIBRATION
    local_client = check_docker_environment()
    duckiebot_client = get_remote_client(duckiebot_ip)
    operating_system = platform.system()

    duckiebot_client.images.pull(RPI_DUCKIEBOT_BASE)
    local_client.images.pull(RPI_DUCKIEBOT_CALIBRATION)

    env_vars = default_env(duckiebot_name, duckiebot_ip)

    if operating_system == 'Linux':
        call(["xhost", "+"])
        local_client.containers.run(image=RPI_DUCKIEBOT_CALIBRATION,
                                    network_mode='host',
                                    volumes=bind_local_data_dir(),
                                    privileged=True,
                                    environment=env_vars)
    if operating_system == 'Darwin':
        IP = subprocess.check_output(['/bin/sh', '-c', 'ifconfig en0 | grep inet | awk \'$1=="inet" {print $2}\''])
        env_vars['IP'] = IP
        call(["xhost", "+IP"])
        local_client.containers.run(image=RPI_DUCKIEBOT_CALIBRATION,
                                    network_mode='host',
                                    volumes=bind_local_data_dir(),
                                    privileged=True,
                                    environment=env_vars)

    calibrate_extrinsics.calibrate(duckiebot_name, duckiebot_ip)
    calibrate_wheels.calibrate(duckiebot_ip)
