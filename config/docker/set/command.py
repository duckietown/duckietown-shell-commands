import argparse
import os
from typing import List

from dt_shell import DTCommandAbs, dtslogger, DTShell


class DTCommand(DTCommandAbs):
    help = "Configure docker registry credentials"

    usage = f"""
Usage:

    dts config docker --docker-username <your-docker-username> --docker-password <your-docker-access-token> [--docker-registry <optional-specific-registry>]
"""

    @staticmethod
    def command(shell, args, **kwargs):
        parser = argparse.ArgumentParser(prog="dts config docker")
        parser.add_argument(
            "--docker-registry",
            "--docker-server",
            dest="server",
            help="Docker server",
            default="docker.io",
        )
        parser.add_argument(
            "--docker-username",
            dest="username",
            help="Docker username",
            required=True,
        )
        parser.add_argument(
            "--docker-password",
            dest="password",
            help="Docker password or Docker token",
            required=True,
        )
        parsed = parser.parse_args(args)

        username = parsed.username
        password = parsed.password

        server = parsed.server

        if server not in shell.shell_config.docker_credentials:
            shell.shell_config.docker_credentials[server] = {}
        
        if username is None and password is None:
            print(DTCommand.usage)
            exit(4)

        if username is not None:
            shell.shell_config.docker_username = username
            shell.shell_config.docker_credentials[server]["username"] = username
        if password is not None:
            shell.shell_config.docker_password = password
            shell.shell_config.docker_credentials[server]["secret"] = password

        shell.save_config()
        dtslogger.info("Docker access credentials stored!")
