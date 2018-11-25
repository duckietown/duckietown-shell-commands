from __future__ import print_function

import argparse
from os.path import join, realpath, dirname

from dt_shell import DTCommandAbs

from utils.cli_utils import start_command_in_subprocess
from utils.networking_utils import get_duckiebot_ip


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
        parsed_args = parser.parse_args(args)

        if not parsed_args.cli:
            run_gui_controller(parsed_args.hostname)
        else:
            run_cli_controller(parsed_args.hostname)


def run_gui_controller(hostname):
    duckiebot_ip = get_duckiebot_ip(duckiebot_name=hostname)
    script_file = join(dirname(realpath(__file__)), 'start_keyboard_control.sh')

    run_cmd = '/bin/bash %s %s %s' % (script_file, hostname, duckiebot_ip)
    print('Running %s' % run_cmd)
    start_command_in_subprocess(run_cmd)


def run_cli_controller(hostname):
    run_cmd = 'docker -H %s.local run -it --rm --privileged --network=host -v /data:/data duckietown/rpi-duckiebot-joy-cli:master18' % hostname
    print('Running %s' % run_cmd)
    start_command_in_subprocess(run_cmd)
