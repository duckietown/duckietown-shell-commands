from __future__ import print_function

import argparse
import os
import subprocess
import sys
from os.path import join, realpath, dirname

from dt_shell import dtslogger

from dt_shell import DTCommandAbs
from utils.networking import get_duckiebot_ip


class DTCommand(DTCommandAbs):

    @staticmethod
    def command(shell, args):
        script_file = join(dirname(realpath(__file__)), 'start_keyboard_control.sh')
        prog = 'dts keyboard_control DUCKIEBOT_NAME'
        usage = """
Keyboard control: 

    %(prog)s
"""

        parser = argparse.ArgumentParser(prog=prog, usage=usage)
        parser.add_argument('hostname', default=None, help='Name of the Duckiebot to calibrate')
        parser.add_argument('--cli', dest = 'cli', default=False, action='store_true',
                            help='A flag, if set will run with CLI instead of with GUI')
        parsed_args = parser.parse_args(args)

        if not parsed_args.cli:
            duckiebot_ip = get_duckiebot_ip(duckiebot_name=parsed_args.hostname)

            env = {}
            env.update(os.environ)
            V = 'DOCKER_HOST'
            if V in env:
                msg = 'I will ignore %s in the environment because we want to run things on the laptop.' % V
                dtslogger.info(msg)
                env.pop(V)

            script_cmd = '/bin/bash %s %s %s' % (script_file, parsed_args.hostname, duckiebot_ip)

            print('Running %s' % script_cmd)
            ret = subprocess.call(script_cmd, shell=True, stdin=sys.stdin, stderr=sys.stderr, stdout=sys.stdout, env=env)

            if ret == 0:
                print('Done!')
            else:
                msg = ('An error occurred while starting the GUI tools container, please check and try again (%s).' % ret)
                raise Exception(msg)
        else:
            env = {}
            env.update(os.environ)
            script_cmd = 'docker -H %s.local run -it --rm --privileged --network=host -v /data:/data duckietown/rpi-duckiebot-joy-cli:master18' % parsed_args.hostname
            print('Running %s' % script_cmd)
            ret = subprocess.call(script_cmd, shell=True, stdin=sys.stdin, stderr=sys.stderr, stdout=sys.stdout, env=env)
            if ret == 0:
                print('Done!')
            else:
                msg = ('An error occurred while starting the joystick CLI container, please check and try again (%s).' % ret)
                raise Exception(msg)


