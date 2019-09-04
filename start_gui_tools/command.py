from __future__ import print_function

import argparse
import os
import subprocess
import platform
import socket
from dt_shell import DTCommandAbs, dtslogger
from dt_shell.env_checks import check_docker_environment
from utils.docker_utils import remove_if_running
from utils.cli_utils import start_command_in_subprocess
from utils.networking_utils import get_duckiebot_ip


class DTCommand(DTCommandAbs):
    @staticmethod
    def command(shell, args):
        prog = 'dts start_gui_tools DUCKIEBOT_NAME'
        usage = """
Keyboard control: 

    %(prog)s
"""

        parser = argparse.ArgumentParser(prog=prog, usage=usage)
        parser.add_argument('hostname', default=None, help='Name of the Duckiebot to calibrate')
        parser.add_argument('--network', default='host', help='Name of the network which to connect')
        parser.add_argument('--sim', action='store_true', default=False,
                            help='are we running in simulator?')
        parser.add_argument('--base_image', dest='image',
                            default="duckietown/rpi-duckiebot-base:master19-no-arm",
                            help="The base image, probably don't change the default")
        parsed_args = parser.parse_args(args)

        if parsed_args.sim:
            duckiebot_ip = "localhost"
        else:
            duckiebot_ip = get_duckiebot_ip(duckiebot_name=parsed_args.hostname)

        hostname = parsed_args.hostname
        image = parsed_args.image

        client = check_docker_environment()
        container_name = "interactive_gui_tools_%s" % hostname
        remove_if_running(client, container_name)

        if parsed_args.sim:
            env = {'HOSTNAME': 'default',
                   'ROS_MASTER': hostname,
                   'DUCKIEBOT_NAME': hostname,
                   'ROS_MASTER_URI': 'http://%s:11311' % hostname}
        else:
            env = {'HOSTNAME': hostname,
                   'ROS_MASTER': hostname,
                   'DUCKIEBOT_NAME': hostname,
                   'ROS_MASTER_URI': 'http://%s:11311' % duckiebot_ip}

        env['QT_X11_NO_MITSHM'] = 1

        volumes = {}



        p = platform.system().lower()
        if 'darwin' in p:
            subprocess.call(["xhost", "+", '127.0.0.1'])
            env['DISPLAY'] = 'host.docker.internal:0'
            volumes = {
                '/tmp/.X11-unix': {'bind': '/tmp/.X11-unix', 'mode': 'rw'}
            }
        else:
            subprocess.call(["xhost", "+"])
            env['DISPLAY'] = os.environ['DISPLAY']

        dtslogger.info("Running %s on localhost with environment vars: %s" %
                       (container_name, env))

        cmd = "/bin/bash"

        params = {'image': image,
                  'name': container_name,
                  'network_mode': parsed_args.network,
                  'environment': env,
                  'privileged': True,
                  'stdin_open': True,
                  'tty': True,
                  'detach': True,
                  'command': cmd,
                  'volumes': volumes
                  }

        container = client.containers.run(**params)
        attach_cmd = 'docker attach %s' % container_name
        start_command_in_subprocess(attach_cmd)
