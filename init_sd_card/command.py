from __future__ import print_function
from dt_shell import DTCommandAbs
from os.path import join, realpath, dirname
import subprocess
import os

class DTCommand(DTCommandAbs):

    @staticmethod
    def command(shell, args):
        script_file = join(dirname(realpath(__file__)), '..', 'init_sd_card.scripts', 'init_sd_card.sh')
        if not os.path.exists(script_file):
            msg = 'Could not find script %s' % script_file
            raise Exception(msg)
        script_cmd = '/bin/bash %s' % script_file
        process = subprocess.Popen(script_cmd, shell=True, stdout=subprocess.PIPE)
        process.wait()
        if process.returncode == 0:
            print( 'Done!' )
        else:
            msg = ( 'An error occurred while initializing the SD card, please check and try again.' )
            raise Exception(msg)
