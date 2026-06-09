import argparse

from dt_shell import DTCommandAbs, dtslogger
from utils.misc_utils import hide_string


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
        parsed = kwargs.get("parsed", None)
        if parsed is None:
            parsed = parser.parse_args(args)
        else:
            parsed = DTCommand._resolve_parsed([], parsed, parser=parser)

        # ---

        secret_key: str = "github/credentials/token"
        if not shell.profile.secrets.contains(secret_key):
            dtslogger.warning(
                "\nNo github credentials found.\n"
                "Please, set it first using the command:\n\n"
                "\tdts config github credentials set --username <username> --token <token>\n"
            )
            return False

        credentials: dict = shell.profile.secrets.get(secret_key)
        token: str = credentials["token"] if parsed.show else hide_string(credentials["token"])

        dtslogger.info(
            f"GitHub credentials:\n\n"
            f"\tusername:   {credentials['username']}\n"
            f"\t  secret:   {token}\n"
        )
