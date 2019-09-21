

from os.path import join, realpath, dirname

from dt_shell import DTCommandAbs

from utils.cli_utils import start_command_in_subprocess


from dt_shell import DTShell


class DTCommand(DTCommandAbs):
    @staticmethod
    def command(shell: DTShell, args):
        script_file = join(dirname(realpath(__file__)), "start_hatchery.sh")

        script_cmd = "/bin/sh %s" % script_file
        start_command_in_subprocess(script_cmd)
