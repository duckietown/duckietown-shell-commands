import argparse

from dt_shell import DTCommandAbs
from dt_shell.constants import DTShellConstants


class DTCommand(DTCommandAbs):

    @staticmethod
    def command(shell, args):
        parser = argparse.ArgumentParser(prog='dts challenges config')
        parser.add_argument('--docker-username', dest='username', help="Docker username", required=True)
        parsed = parser.parse_args(args)

        username = parsed.username

        shell.config[DTShellConstants.CONFIG_DOCKER_USERNAME] = username
        shell.save_config()
