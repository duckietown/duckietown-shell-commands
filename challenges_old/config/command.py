import argparse

from dt_shell import DTCommandAbs, DTShell

__all__ = ["DTCommand"]


class DTCommand(DTCommandAbs):
    @staticmethod
    def command(shell: DTShell, args):
        parser = argparse.ArgumentParser(prog="dts challenges config")
        parser.add_argument("--docker-username", dest="username", help="Docker username")
        parser.add_argument("--docker-password", dest="password", help="Docker password")
        parsed = parser.parse_args(args)

        username = parsed.username
        password  = parsed.password

        if username is not None:
            shell.shell_config.docker_username = username
        if password is not None:
            shell.shell_config.docker_password = password
        shell.save_config()
        if username is None and password is None:
            msg = 'You should pass at least one parameter'
            DTCommandAbs.fail(msg)


