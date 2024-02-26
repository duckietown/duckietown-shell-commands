import argparse

from dt_shell import DTCommandAbs, dtslogger
from dt_shell.profile import GenericCredentials
from utils.cli_utils import ask_confirmation
from utils.docker_utils import DEFAULT_REGISTRY


class DTCommand(DTCommandAbs):
    help = "Configure docker registry credentials"

    @staticmethod
    def command(shell, args, **kwargs):
        parser = argparse.ArgumentParser(
            prog="dts config docker credentials set",
            description="Save Docker logins locally for Duckietown",
        )
        parser.add_argument(
            "server",
            help=f"Docker server (default: {DEFAULT_REGISTRY})",
            default=DEFAULT_REGISTRY,
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

        # ---

        # - overwrite?
        if shell.profile.secrets.docker_credentials.contains(server):
            overwrite: bool = ask_confirmation(
                "A set of credentials for this Docker registry is already stored, if you continue, the "
                "old credentials will be overwritten.",
                default="y",
            )
            if not overwrite:
                dtslogger.info("Leaving credentials untouched")
                return False

        # - store secrets
        secret: GenericCredentials = GenericCredentials(username=username, password=password)
        shell.profile.secrets.docker_credentials.set(server, secret)

        dtslogger.info("Docker access credentials stored!")
