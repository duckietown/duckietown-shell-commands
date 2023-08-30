import argparse

from dt_shell import DTCommandAbs, dtslogger
from utils.docker_utils import DEFAULT_REGISTRY
from utils.misc_utils import hide_string
from utils.secrets_utils import SecretsManager, Secret


class DTCommand(DTCommandAbs):
    @staticmethod
    def command(shell, args, **kwargs):
        prog = "dts config docker credentials info"
        desc = "Show info about saved docker registry credentials"
        usage = f"\n\n\t\t{prog}"

        parser = argparse.ArgumentParser(prog=prog, description=desc, usage=usage)
        parser.add_argument(
            "server",
            help=f"Docker server (default: {DEFAULT_REGISTRY})",
            default=DEFAULT_REGISTRY,
            nargs="?",
        )
        parser.add_argument(
            "--show",
            help="Show credentials in plain",
            action="store_true",
            default=False,
        )
        parsed = parser.parse_args(args)

        server = parsed.server

        # ---

        secret_key: str = f"docker/credentials/{server}"
        if not SecretsManager.has(secret_key):
            dtslogger.warning(
                "\nNo docker credentials available.\n"
                "Please see how one could be configured using:\n\n"
                "\tdts config docker credentials set --help\n"
            )
            return False

        credentials: Secret = SecretsManager.get(secret_key)
        secret: str = credentials["secret"] if parsed.show else hide_string(credentials["secret"])

        dtslogger.info(
            f"Docker credentials:\n\n"
            f"\tregistry:   {server}\n"
            f"\tusername:   {credentials['username']}\n"
            f"\t  secret:   {secret}\n"
        )
