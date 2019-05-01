from __future__ import print_function

import argparse
from os.path import join, realpath, dirname

from dt_shell import DTCommandAbs

from utils.cli_utils import start_command_in_subprocess
from utils.docker_utils import start_gui_tools
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
        parsed_args = parser.parse_args(args)

        if parsed_args.sim:
            duckiebot_ip = "localhost"
        else:
            duckiebot_ip = get_duckiebot_ip(duckiebot_name=parsed_args.hostname)
        script_file = join(dirname(realpath(__file__)), 'start_gui_tools.sh')
        script_cmd = '/bin/bash %s %s %s %s' % (script_file, parsed_args.hostname, duckiebot_ip, parsed_args.network)
            
        start_command_in_subprocess(script_cmd)
        # TODO: call

        start_gui_tools(script_cmd)
