from __future__ import print_function

import argparse
import os
import subprocess
import sys
from os.path import join, realpath, dirname

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
        parser.add_argument('--network', default='host', help='Name of the network which to connect')
        parsed_args = parser.parse_args(args)

        duckiebot_ip = get_duckiebot_ip(duckiebot_name=parsed_args.hostname)
        script_file = join(dirname(realpath(__file__)), 'start_gui_tools.sh')
        script_cmd = '/bin/bash %s %s %s %s' % (script_file, parsed_args.hostname, duckiebot_ip, parsed_args.network)

        print('Running script: %s' % script_cmd)

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
