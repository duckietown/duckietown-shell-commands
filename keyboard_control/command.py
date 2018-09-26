from __future__ import print_function

import os
import re
import subprocess
import sys
from os.path import join, realpath, dirname

from dt_shell import DTCommandAbs

from utils.networking import get_duckiebot_ip

class DTCommand(DTCommandAbs):

    @staticmethod
    def command(shell, args):
        script_file = join(dirname(realpath(__file__)), 'start_keyboard_control.sh')

        if len(args) < 1:
            raise Exception('Usage: calibrate <DUCKIEBOT_NAME_GOES_HERE>')

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

def get_ip_from_ping(alias):
    response = os.popen('ping -c 1 %s' % alias).read()
    m = re.search('PING.*?\((.*?)\)+', response)
    if m:
        return m.group(1)
    else:
        raise Exception("Unable to locate %s, aborting!" % alias)
