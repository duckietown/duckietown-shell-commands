from __future__ import print_function

import sys
from os.path import join, realpath, dirname
import argparse
import os
import platform
import subprocess
from subprocess import call, check_output

from dt_shell import DTCommandAbs, dtslogger

from utils.networking import get_duckiebot_ip


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
        parsed_args = parser.parse_args(args)

        duckiebot_ip = get_duckiebot_ip(duckiebot_name=parsed_args.hostname)
        script_file = join(dirname(realpath(__file__)), 'start_gui_tools.sh')
        script_cmd = '/bin/bash %s %s %s' % (script_file, parsed_args.hostname, duckiebot_ip)
        print('Running %s' % script_cmd)

        env = {}
        env.update(os.environ)
        V = 'DOCKER_HOST'
        if V in env:
            msg = 'I will ignore %s in the environment because we want to run things on the laptop.' % V
            dtslogger.info(msg)
            env.pop(V)

        ret = subprocess.call(script_cmd, shell=True, stdin=sys.stdin, stderr=sys.stderr, stdout=sys.stdout, env=env)

        if ret == 0:
            print('Done!')
        else:
            msg = ('An error occurred while starting the GUI tools container, please check and try again (%s).' % ret)
            raise Exception(msg)


def start_gui_tools(duckiebot_name):
    duckiebot_ip = get_duckiebot_ip(duckiebot_name)
    import docker
    local_client = docker.from_env()
    operating_system = platform.system()

    IMAGE_RPI_GUI_TOOLS = 'duckietown/rpi-gui-tools:master18'

    local_client.images.pull(IMAGE_RPI_GUI_TOOLS)

    env_vars = { 'ROS_MASTER': duckiebot_name, 'DUCKIEBOT_NAME': duckiebot_name, 'DUCKIEBOT_IP': duckiebot_ip, 'QT_X11_NO_MITSHM': True, 'DISPLAY': True }

    if operating_system == 'Linux':
        call(["xhost", "+"])
        local_client.containers.run(image=IMAGE_RPI_GUI_TOOLS, network_mode='host', privileged=True, environment=env_vars, command="/bin/bash")
    elif operating_system == 'Darwin':
        IP = check_output(['/bin/sh', '-c', 'ifconfig en0 | grep inet | awk \'$1=="inet" {print $2}\''])
        env_vars['IP'] = IP
        call(["xhost", "+IP"])
        local_client.containers.run(image=IMAGE_RPI_GUI_TOOLS,
                                    network_mode='host',
                                    privileged=True,
                                    environment=env_vars)
