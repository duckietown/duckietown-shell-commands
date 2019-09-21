from os.path import dirname, join, realpath

from dt_shell import DTCommandAbs, DTShell
from utils.cli_utils import start_command_in_subprocess


class DTCommand(DTCommandAbs):
    @staticmethod
    def command(shell: DTShell, args):
        script_file = join(dirname(realpath(__file__)), "start_hatchery.sh")

        script_cmd = "/bin/sh %s" % script_file
        start_command_in_subprocess(script_cmd)
