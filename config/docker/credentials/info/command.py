import argparse

from dt_shell import DTCommandAbs, dtslogger
from dt_shell.profile import GenericCredentials
from utils.docker_utils import DEFAULT_REGISTRY
from utils.misc_utils import hide_string


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

        if not shell.profile.secrets.docker_credentials.contains(server):
            dtslogger.warning(
                f"\nNo docker credentials available for server '{server}'.\n"
                "Please, set it first using the command:\n\n"
                "\tdts config docker credentials set [registry] --username <username> --password <password>\n"
            )
            return False

        credentials: GenericCredentials = shell.profile.secrets.docker_credentials.get(server)
        secret: str = credentials.password if parsed.show else hide_string(credentials.password)

        dtslogger.info(
            f"Docker credentials:\n\n"
            f"\tregistry:   {server}\n"
            f"\tusername:   {credentials.username}\n"
            f"\tpassword:   {secret}\n"
        )
