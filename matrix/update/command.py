import argparse
from types import SimpleNamespace

from dt_shell import DTCommandAbs, DTShell

from utils.duckiematrix_utils import \
    APP_NAME


class DTCommand(DTCommandAbs):

    help = f'Updates the {APP_NAME} application'

    @staticmethod
    def _parse_args(args):
        # configure arguments
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "-f",
            "--force",
            default=None,
            action="store_true",
            help="Force reinstall when the same version is already installed",
        )
        parser.add_argument(
            "-v",
            "--version",
            default=None,
            type=str,
            help="Update to a specific version"
        )
        parsed, _ = parser.parse_known_args(args=args)
        return parsed

    @staticmethod
    def command(shell: DTShell, args, **kwargs):
        parsed = kwargs.get("parsed", None)
        if parsed is None:
            parsed = DTCommand._parse_args(args)
        # ---
        shell.include.matrix.install.command(
            shell,
            [],
            parsed=SimpleNamespace(
                version=parsed.version,
                force=parsed.force,
                update=True,
            )
        )

    @staticmethod
    def complete(shell, word, line):
        return []
