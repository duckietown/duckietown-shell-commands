from __future__ import print_function

import os
import re
import subprocess
import sys
from os.path import join, realpath, dirname

from dt_shell import DTCommandAbs

from utils.networking import get_duckiebot_ip
<<<<<<< HEAD
=======

>>>>>>> 284cc91aa0d633c1dcdcfff41b000efde2d56391

class DTCommand(DTCommandAbs):

    @staticmethod
    def command(shell, args):
        script_file = join(dirname(realpath(__file__)), 'start_keyboard_control.sh')

        if len(args) < 1:
            raise Exception('No Duckiebot name received, aborting!')

        get_duckiebot_ip(duckiebot_name=args[0])

        duckiebot_ip = get_duckiebot_ip(args[0])
        script_cmd = '/bin/bash %s %s %s' % (script_file, args[0], duckiebot_ip)
        print('Running %s' % script_cmd)
        ret = subprocess.call(script_cmd, shell=True, stdin=sys.stdin, stderr=sys.stderr, stdout=sys.stdout)
        # process.communicate()
        if ret == 0:
            print('Done!')
        else:
            msg = ('An error occurred while starting the GUI tools container, please check and try again (%s).' % ret)
            raise Exception(msg)
