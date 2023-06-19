import argparse

from dt_shell import DTCommandAbs, dtslogger
from utils.misc_utils import hide_string
from utils.secrets_utils import SecretsManager, Secret


class DTCommand(DTCommandAbs):

    @staticmethod
    def command(shell, args, **kwargs):
        prog = "dts config github credentials info"
        desc = "Show info about saved GitHub credentials"
        usage = f"\n\n\t\t{prog}"

        parser = argparse.ArgumentParser(prog=prog, description=desc, usage=usage)
        parser.add_argument(
            "--show",
            help="Show credentials in plain",
            action="store_true",
            default=False,
        )
        parsed = parser.parse_args(args)

        # ---

        secret_key: str = "github/credentials/token"
        if not SecretsManager.has(secret_key):
            dtslogger.warning("\nNo github credentials found.\n"
                              "Please see how one could be configured using:\n\n"
                              "\tdts config github credentials set --help\n")
            return False

        credentials: Secret = SecretsManager.get(secret_key)
        secret: str = credentials['secret'] if parsed.show else hide_string(credentials['secret'])

        dtslogger.info(f"GitHub credentials:\n\n"
                       f"\tusername:   {credentials['username']}\n"
                       f"\t  secret:   {secret}\n")
