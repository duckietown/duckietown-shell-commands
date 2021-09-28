import argparse
import os
import subprocess
from types import SimpleNamespace

import dt_data_api

from dt_shell import DTCommandAbs, dtslogger, DTShell
from utils.duckiematrix_utils import \
    APP_NAME, \
    DCSS_SPACE_NAME, \
    APP_RELEASES_DIR, \
    get_most_recent_version_installed, \
    remote_zip_obj, \
    get_latest_version

from utils.duckietown_utils import get_distro_version
from utils.misc_utils import versiontuple


class DTCommand(DTCommandAbs):

    help = f'Updates the {APP_NAME} application'

    @staticmethod
    def _parse_args(args):
        # configure arguments
        parser = argparse.ArgumentParser()
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
                update=True,
            )
        )

    @staticmethod
    def complete(shell, word, line):
        return []
