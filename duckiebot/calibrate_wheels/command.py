from __future__ import print_function

import argparse
from os.path import join, realpath, dirname

from dt_shell import DTCommandAbs
from dt_shell.env_checks import check_docker_environment
from past.builtins import raw_input

from utils.cli_utils import start_command_in_subprocess
from utils.docker_utils import bind_duckiebot_data_dir, attach_terminal
from utils.networking_utils import get_duckiebot_ip


class DTCommand(DTCommandAbs):

    @staticmethod
    def command(shell, args):
        script_file = join(dirname(realpath(__file__)), 'calibrate_wheels.sh')

        prog = 'dts duckiebot calibrate_wheels DUCKIEBOT_NAME'
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

        start_command_in_subprocess(script_cmd)


def calibrate(hostname):
    duckiebot_ip = get_duckiebot_ip(hostname)
    import docker
    local_client = check_docker_environment()

    from utils.docker_utils import RPI_DUCKIEBOT_CALIBRATION
    duckiebot_client = docker.DockerClient('tcp://' + duckiebot_ip + ':2375')

    local_client.images.pull(RPI_DUCKIEBOT_CALIBRATION)
    raw_input("""{}\nTo perform the wheel calibration, follow the steps described in the Duckiebook.
    http://docs.duckietown.org/DT18/opmanual_duckiebot/out/wheel_calibration.html
    You will now be given a container running on the Duckiebot for wheel calibration.""".format('*' * 20))

    wheel_calibration_container = duckiebot_client.containers.run(image=RPI_DUCKIEBOT_CALIBRATION,
                                                                  privileged=True,
                                                                  network_mode='host',
                                                                  tty=True,
                                                                  datavol=bind_duckiebot_data_dir(),
                                                                  command='/bin/bash')

    attach_terminal(wheel_calibration_container.name, hostname)
