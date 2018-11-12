from __future__ import print_function

import argparse
import os
import platform
import subprocess
import time
from os.path import join, realpath, dirname
from subprocess import call

from dt_shell import DTCommandAbs
from dt_shell.env_checks import check_docker_environment
from past.builtins import raw_input

from utils.docker_utils import RPI_DUCKIEBOT_ROS_PICAM


class DTCommand(DTCommandAbs):

    @staticmethod
    def command(shell, args):
        script_file = join(dirname(realpath(__file__)), 'calibrate_duckiebot.sh')

        prog = 'dts duckiebot camera DUCKIEBOT_NAME'
        usage = """
Stream camera images: 

    %(prog)s
"""

        from utils.networking import get_duckiebot_ip

        parser = argparse.ArgumentParser(prog=prog, usage=usage)
        parser.add_argument('hostname', default=None, help='Name of the Duckiebot')
        parsed_args = parser.parse_args(args)

        duckiebot_ip = get_duckiebot_ip(parsed_args.hostname)

        view_camera(duckiebot_name=parsed_args.hostname, duckiebot_ip=duckiebot_ip)


def view_camera(duckiebot_name, duckiebot_ip):
    import docker
    from utils.docker_utils import RPI_GUI_TOOLS

    raw_input("""{}\nWe will now open a camera feed by running xhost+ and opening rqt_image_view...""".format('*' * 20))
    local_client = check_docker_environment()
    duckiebot_client = docker.DockerClient('tcp://' + duckiebot_ip + ':2375')
    operating_system = platform.system()

    local_client.images.pull(RPI_GUI_TOOLS)
    duckiebot_client.images.pull(RPI_DUCKIEBOT_ROS_PICAM)

    env_vars = {
        'ROS_MASTER': duckiebot_name,
        'DUCKIEBOT_NAME': duckiebot_name,
        'DUCKIEBOT_IP': duckiebot_ip,
        'QT_X11_NO_MITSHM': 1,
    }

    print("Running with" + str(env_vars))

    duckiebot_client.containers.run(image=RPI_DUCKIEBOT_ROS_PICAM,
                                    network_mode='host',
                                    devices=['/dev/vchiq'],
                                    detach=True,
                                    environment=env_vars)

    print("Waiting a few seconds for Duckiebot camera container to warm up...")
    time.sleep(3)

    if operating_system == 'Linux':
        call(["xhost", "+"])
        env_vars['DISPLAY'] = ':0'
        local_client.containers.run(image=RPI_GUI_TOOLS,
                                    privileged=True,
                                    network_mode='host',
                                    environment=env_vars,
                                    command='bash -c "source /home/software/docker/env.sh && rqt_image_view"')

    elif operating_system == 'Darwin':
        IP = subprocess.check_output(['/bin/sh', '-c', 'ifconfig en0 | grep inet | awk \'$1=="inet" {print $2}\''])
        env_vars['IP'] = IP
        call(["xhost", "+IP"])
        local_client.containers.run(image=RPI_GUI_TOOLS,
                                    privileged=True,
                                    network_mode='host',
                                    environment=env_vars,
                                    command='rqt_image_view')