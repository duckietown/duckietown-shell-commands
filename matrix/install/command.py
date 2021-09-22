import argparse
import os

from dt_data_api import DataClient
from dt_shell import DTCommandAbs, dtslogger, DTShell

from utils.duckiematrix_utils import APP_NAME, DCSS_SPACE_NAME, DCSS_APP_PATH

#TODO: make sure dt-data-api is at least v0.2.0


class DTCommand(DTCommandAbs):

    help = f'Installs the {APP_NAME} application'

    @staticmethod
    def _parse_args(args):
        # configure arguments
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "-U",
            "--update",
            default=None,
            action="store_true",
            help="Update if already installed",
        )
        parser.add_argument(
            "-v",
            "--version",
            default=None,
            type=str,
            help="Install a specific version"
        )
        parsed, _ = parser.parse_known_args(args=args)
        return parsed

    @staticmethod
    def command(shell: DTShell, args, **kwargs):
        parsed = kwargs.get("parsed", None)
        if parsed is None:
            parsed = DTCommand._parse_args(args)
        # ---
        # get the token if it is set
        token = None
        # noinspection PyBroadException
        try:
            token = shell.get_dt1_token()
        except Exception:
            pass
        # create storage client
        client = DataClient(token)
        storage = client.storage(DCSS_SPACE_NAME)
        # get latest version
        latest_version_obj = os.path.join(DCSS_APP_PATH, "latest")
        download = storage.download(latest_version_obj)
        download.join()
        latest = download.data

        print(latest)


    @staticmethod
    def complete(shell, word, line):
        return []
