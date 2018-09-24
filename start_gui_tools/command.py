from __future__ import print_function

import os
import re
import subprocess
import sys
from os.path import join, realpath, dirname

from dt_shell import DTCommandAbs


class DTCommand(DTCommandAbs):

    @staticmethod
    def command(shell, args):
        script_file = join(dirname(realpath(__file__)), 'start_gui_tools.sh')

        if len(args) < 1:
            raise Exception('No Duckiebot name received, aborting!')

        try:
            mdns_alias = '%s.local' % args[0]
            duckiebot_ip = get_ip_from_ping(mdns_alias)
        except:
            mdns_alias = args[0]
            duckiebot_ip = get_ip_from_ping(mdns_alias)

        script_cmd = '/bin/bash %s %s %s' % (script_file, mdns_alias, duckiebot_ip)
        print('Running %s' % script_cmd)
        ret = subprocess.call(script_cmd, shell=True, stdin=sys.stdin, stderr=sys.stderr, stdout=sys.stdout)
        # process.communicate()
        if ret == 0:
            print('Done!')
        else:
            msg = ('An error occurred while starting the GUI tools container, please check and try again (%s).' % ret)
            raise Exception(msg)

def get_ip_from_ping(alias):
    response = os.popen('ping -c 1 -w2 %s' % alias).read()
    m = re.search('PING.*?\((.*)\)+', response)
    if m:
        return m.group(1)
    else:
        raise Exception("Unable to locate locate alias, aborting!")
