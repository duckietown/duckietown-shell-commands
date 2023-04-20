import argparse

from dt_shell import DTCommandAbs, dtslogger


class DTCommand(DTCommandAbs):
    help = "Configure docker registry credentials"

    usage = f"""
Usage:

    dts config docker --username <your-docker-username> --password <your-docker-access-token> [optional-docker-server]
"""

    @staticmethod
    def command(shell, args, **kwargs):
        parser = argparse.ArgumentParser(
            prog="dts config docker",
            description=(
                "Save Docker logins locally for Duckietown use. "
                "The credentials are stored in plain text in ~/.dt-shell/config.yaml."
            ),
        )
        parser.add_argument(
            "server",
            help="Docker server (default: docker.io)",
            default="docker.io",
            nargs="?",
        )
        parser.add_argument(
            "--username",
            help="Docker username",
            required=True,
        )
        parser.add_argument(
            "--password",
            help="Docker access token (preferred) or Docker password",
            required=True,
        )
        parsed = parser.parse_args(args)

        username = parsed.username
        password = parsed.password

        server = parsed.server

        if server not in shell.shell_config.docker_credentials:
            shell.shell_config.docker_credentials[server] = {}
        
        if username is None and password is None:
            dtslogger.warning(DTCommand.usage)
            exit(4)

        if username is not None:
            shell.shell_config.docker_credentials[server]["username"] = username
        if password is not None:
            shell.shell_config.docker_credentials[server]["secret"] = password

        shell.save_config()
        dtslogger.info("Docker access credentials stored!")
