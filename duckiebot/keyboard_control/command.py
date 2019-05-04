from __future__ import print_function


import argparse
from os.path import join, realpath, dirname

from dt_shell import DTCommandAbs, dtslogger
from dt_shell.env_checks import check_docker_environment
from utils.networking_utils import get_duckiebot_ip
from utils.docker_utils import remove_if_running, continuously_monitor
from utils.cli_utils import start_command_in_subprocess

class DTCommand(DTCommandAbs):

    @staticmethod
    def command(shell, args):
        prog = 'dts duckiebot keyboard_control DUCKIEBOT_NAME'
        usage = """
Keyboard control: 

    %(prog)s
"""

        parser = argparse.ArgumentParser(prog=prog, usage=usage)
        parser.add_argument('hostname', default=None, help='Name of the Duckiebot to calibrate')
        parser.add_argument('--cli', dest='cli', default=False, action='store_true',
                            help='A flag, if set will run with CLI instead of with GUI')
        parser.add_argument('--base_image', dest='image',
                            default="duckietown/rpi-duckiebot-base:master19-no-arm",
                            help="The base image, probably don't change the default")
        parsed_args = parser.parse_args(args)

        if not parsed_args.cli:
            run_gui_controller(parsed_args.hostname)
        else:
            run_cli_controller(parsed_args.hostname, parsed_args.image)


def run_gui_controller(hostname):
    duckiebot_ip = get_duckiebot_ip(duckiebot_name=hostname)
    script_file = join(dirname(realpath(__file__)), 'start_keyboard_control.sh')

    run_cmd = '/bin/bash %s %s %s' % (script_file, hostname, duckiebot_ip)
    print('Running %s' % run_cmd)
    start_command_in_subprocess(run_cmd)


def run_cli_controller(hostname,image):
    client=check_docker_environment()
    container_name = "joystick_cli"
    remove_if_running(client, container_name)
    duckiebot_ip=get_duckiebot_ip(hostname)
    env = {'ROS_MASTER':hostname,
            'DUCKIEBOT_NAME':hostname,
            'ROS_MASTER_URI':'http://%s:11311' % duckiebot_ip}

    dtslogger.info("Running %s on localhost with environment vars: %s" %
                   (container_name, env))

    cmd = "python misc/virtualJoy/joy_cli.py %s" % hostname

    params = {'image': image,
                'name': container_name,
                'network_mode': 'host',
                'environment': env,
                'privileged': True,
                'stdin_open': True,
                'tty':True,
                'command': cmd,
              'detach':True
              }

    container = client.containers.run(**params)

    cmd = 'docker attach %s' % container_name
    start_command_in_subprocess(cmd)