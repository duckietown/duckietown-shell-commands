import argparse

from dt_shell import DTCommandAbs, DTShell

__all__ = ["DTCommand"]


class DTCommand(DTCommandAbs):
    @staticmethod
    def command(shell: DTShell, args):
        parser = argparse.ArgumentParser(prog="dts challenges config")
        parser.add_argument(
            "--docker-username", dest="username", help="Docker username", required=True
        )
        parsed = parser.parse_args(args)

        username = parsed.username

        shell.shell_config.docker_username = username
        shell.save_config()
