from __future__ import print_function

import argparse
import os
import sys
from os.path import join, realpath, dirname
from subprocess import call

from dt_shell import DTCommandAbs, dtslogger
from dt_shell.env_checks import check_docker_environment
from past.builtins import raw_input


class DTCommand(DTCommandAbs):

    @staticmethod
    def command(shell, args):
        script_file = join(dirname(realpath(__file__)), 'calibrate_duckiebot.sh')

        prog = 'dts duckiebot calibrate_wheels DUCKIEBOT_NAME'
        usage = """
Calibrate: 

    %(prog)s
"""

        from utils.networking import get_duckiebot_ip

        parser = argparse.ArgumentParser(prog=prog, usage=usage)
        parser.add_argument('hostname', default=None, help='Name of the Duckiebot to calibrate')
        parsed_args = parser.parse_args(args)

        duckiebot_ip = get_duckiebot_ip(parsed_args.hostname)
        # shell.calibrate(duckiebot_name=args[0], duckiebot_ip=duckiebot_ip)
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
            print('Done!')
        else:
            msg = ('An error occurred while running the calibration procedure, please check and try again (%s).' % ret)
            raise Exception(msg)


def calibrate(duckiebot_ip):
    import docker
    local_client = check_docker_environment()

    from utils.docker_utils import IMAGE_CALIBRATION
    duckiebot_client = docker.DockerClient('tcp://' + duckiebot_ip + ':2375')

    local_client.images.pull(IMAGE_CALIBRATION)
    raw_input("""{}\nTo perform the wheel calibration, follow the steps described in the Duckiebook.
    http://docs.duckietown.org/DT18/opmanual_duckiebot/out/wheel_calibration.html
    You will now be given a container running on the Duckiebot for wheel calibration.""".format('*' * 20))

    duckiebot_client.containers.run(image=IMAGE_CALIBRATION,
                                    privileged=True,
                                    network_mode='host',
                                    datavol={'/data': {'bind': '/data'}},
                                    command='/bin/bash')
