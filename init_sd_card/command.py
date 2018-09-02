from __future__ import print_function
from dt_shell import DTCommandAbs
from os.path import join, realpath, dirname
import subprocess
import os
import sys
class DTCommand(DTCommandAbs):

    @staticmethod
    def command(shell, args):
        script_file = join(dirname(realpath(__file__)), '..', 'init_sd_card.scripts', 'init_sd_card.sh')
        if not os.path.exists(script_file):
            msg = 'Could not find script %s' % script_file
            raise Exception(msg)
        script_cmd = '/bin/bash %s' % script_file
        subprocess.call(script_cmd, shell=True, stdin=sys.stdin, stderr=sys.stderr, stdout=sys.stdout)
        #process.communicate()
        if process.returncode == 0:
            print( 'Done!' )
        else:
            msg = ( 'An error occurred while initializing the SD card, please check and try again (%s).'% process.returncode )
            raise Exception(msg)
