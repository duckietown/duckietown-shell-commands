import argparse
import getpass
import os
import subprocess
import threading
import time
import docker

from dt_shell import DTCommandAbs, dtslogger
from dt_shell.env_checks import check_docker_environment

from utils.docker_utils import default_env, bind_duckiebot_data_dir
from utils.networking_utils import get_duckiebot_ip

usage = """

## Basic usage

    Runs a demo on the Duckiebot

        $ dts duckiebot demo --demo_name [DEMO_NAME] --duckiebot_name [DUCKIEBOT_NAME]

"""


class DTCommand(DTCommandAbs):

    @staticmethod
    def command(shell, args):
        prog = 'dts duckiebot demo'
        parser = argparse.ArgumentParser(prog=prog, usage=usage)

        group = parser.add_argument_group('Basic')

        parser.add_argument('--demo_name', default=None,
                            help="Name of the demo to run")

        parser.add_argument('--duckiebot_name', default=None,
                            help="Name of the Duckiebot on which to run the demo")
        
        group.add_argument('--image', help="Docker image to use, you probably don't need to change ", default="duckietown/rpi-duckiebot-base:master19")

        parsed = parser.parse_args(args)

        local_client = check_docker_environment()
        demo_name=parsed.demo_name
        duckiebot_name = parsed.duckiebot_name
        duckiebot_ip = get_duckiebot_ip(parsed.duckiebot_name)
        duckiebot_client = docker.DockerClient('tcp://' + duckiebot_ip + ':2375')

        image_base=parsed.image
        env_vars = default_env(duckiebot_name,duckiebot_ip)

        duckiebot_client.images.pull(image_base)

        duckiebot_client.containers.prune()

        duckiebot_client.containers.run(image=image_base,
                                        command='roslaunch duckietown %s.launch veh:=%s' % (demo_name, duckiebot_name),
                                        network_mode='host',
                                        volumes=bind_duckiebot_data_dir(),
                                        privileged=True,
                                        name='demo_%s' % demo_name,
                                        environment=env_vars)
