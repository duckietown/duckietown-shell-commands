from __future__ import print_function

import subprocess
import sys

from dt_shell import DTCommandAbs


class DTCommand(DTCommandAbs):

    @staticmethod
    def command(shell, args):
        script_cmd = '/bin/bash start_gui_tools.sh %r' % args[0]
        ret = subprocess.call(script_cmd, shell=True, stdin=sys.stdin, stderr=sys.stderr, stdout=sys.stdout)
        # process.communicate()
        if ret == 0:
            print('Done!')
        else:
            msg = ('An error occurred while starting the GUI tools container, please check and try again (%s).' % ret)
            raise Exception(msg)
