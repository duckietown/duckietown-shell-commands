import argparse

from dt_shell import DTCommandAbs, dtslogger
from utils.cli_utils import ask_confirmation
from utils.secrets_utils import SecretsManager


class DTCommand(DTCommandAbs):
    help = "Configure GitHub credentials"

    usage = f"""
Usage:

    dts config github credentials set --username <your-github-username> --token <your-github-access-token>
"""

    @staticmethod
    def command(shell, args, **kwargs):
        parser = argparse.ArgumentParser(
            prog="dts config github credentials set",
            description=("Save github logins locally for Duckietown"),
        )
        parser.add_argument(
            "--username",
            help="GitHub username",
            required=True,
        )
        parser.add_argument(
            "--token",
            help="GitHub access token",
            required=True,
        )
        parsed = parser.parse_args(args)

        username = parsed.username
        token = parsed.token

        # ---

        # set secrets
        secret_key: str = "github/credentials/token"
        # - overwrite?
        if SecretsManager.has(secret_key):
            overwrite: bool = ask_confirmation(
                "A set of credentials for GitHub is already stored, if you continue, the "
                "old credentials will be overwritten.",
                default="y",
            )
            if not overwrite:
                dtslogger.info("Leaving credentials untouched")
                return False

        # - store secrets
        secret_value: dict = {"username": username, "secret": token}
        SecretsManager.set(secret_key, secret_value)

        dtslogger.info("GitHub access credentials stored!")
