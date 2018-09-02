from __future__ import print_function

import os
import subprocess
import sys
from os.path import join, realpath, dirname

from dt_shell import DTCommandAbs


class DTCommand(DTCommandAbs):

    @staticmethod
    def command(shell, args):
        script_file = join(dirname(realpath(__file__)), '..', 'init_sd_card.scripts', 'init_sd_card.sh')
        if not os.path.exists(script_file):
            msg = 'Could not find script %s' % script_file
            raise Exception(msg)
        script_cmd = '/bin/bash %s' % script_file
        token = shell.get_dt1_token()
        env = dict(DUCKIE_TOKEN=token)
        ret = subprocess.call(script_cmd, shell=True, stdin=sys.stdin, stderr=sys.stderr, stdout=sys.stdout, env=env)
        # process.communicate()
        if ret == 0:
            print('Done!')
        else:
            msg = ('An error occurred while initializing the SD card, please check and try again (%s).' % ret)
            raise Exception(msg)
