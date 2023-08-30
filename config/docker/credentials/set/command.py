import argparse

from dt_shell import DTCommandAbs, dtslogger
from utils.cli_utils import ask_confirmation
from utils.docker_utils import DEFAULT_REGISTRY
from utils.secrets_utils import SecretsManager


class DTCommand(DTCommandAbs):
    help = "Configure docker registry credentials"

    usage = f"""
Usage:

    dts config docker credentials set --username <your-docker-username> --password <your-docker-access-token> [optional-docker-server]
"""

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

        # set secrets
        secret_key: str = f"docker/credentials/{server}"
        # - overwrite?
        if SecretsManager.has(secret_key):
            overwrite: bool = ask_confirmation(
                "A set of credentials for this Docker registry is already stored, if you continue, the "
                "old credentials will be overwritten.",
                default="y",
            )
            if not overwrite:
                dtslogger.info("Leaving credentials untouched")
                return False

        # - store secrets
        secret_value: dict = {"username": username, "secret": password}
        SecretsManager.set(secret_key, secret_value)

        # ---

        # => Legacy credentials store
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
        # <= Legacy credentials store

        dtslogger.info("Docker access credentials stored!")
