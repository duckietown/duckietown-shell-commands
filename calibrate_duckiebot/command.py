from __future__ import print_function

import subprocess
import sys
from os.path import join, realpath, dirname

from dt_shell import DTCommandAbs

from calibrate_duckiebot.networking import get_ip_from_ping


class DTCommand(DTCommandAbs):

    @staticmethod
    def command(shell, args):
        script_file = join(dirname(realpath(__file__)), 'calibrate_duckiebot.sh')

        duckiebot_ip = get_ip_from_ping(args[0])
        script_cmd = '/bin/bash %s %s %s' % (script_file, args[0], duckiebot_ip)

        ret = subprocess.call(script_cmd, shell=True, stdin=sys.stdin, stderr=sys.stderr, stdout=sys.stdout)
        # process.communicate()
        if ret == 0:
            print('Done!')
        else:
            msg = ('An error occurred while running the calibration procedure, please check and try again (%s).' % ret)
            raise Exception(msg)
