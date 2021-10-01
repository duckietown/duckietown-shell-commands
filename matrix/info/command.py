import argparse
import json
import os

from dt_shell import DTCommandAbs, dtslogger, DTShell
from utils.duckiematrix_utils import \
    APP_NAME, \
    get_most_recent_version_installed, \
    get_path_to_install


class DTCommand(DTCommandAbs):

    help = f'Shows information about the installed version of the {APP_NAME} application'

    @staticmethod
    def _parse_args(args):
        # configure arguments
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "-v",
            "--version",
            default=None,
            type=str,
            help="Show info about a specific version"
        )
        parsed, _ = parser.parse_known_args(args=args)
        return parsed

    @staticmethod
    def command(shell: DTShell, args, **kwargs):
        parsed = kwargs.get("parsed", None)
        if parsed is None:
            parsed = DTCommand._parse_args(args)
        # ---
        version = parsed.version if parsed.version else get_most_recent_version_installed()
        if version is None:
            dtslogger.error(
                f"Version v{parsed.version} not found."
                if parsed.version is not None else
                f"No versions found installed.")
            return
        # ---
        install_dir = get_path_to_install(version)
        meta_fp = os.path.join(install_dir, f"{APP_NAME}.json")
        with open(meta_fp, 'rt') as fin:
            meta = json.load(fin)
        # ---
        meta["installation_path"] = install_dir
        # ---
        print("Renderer (Build):")
        for key, value in meta.items():
            key_txt = f"{key}:".replace("_", " ").title().ljust(24, " ")
            print(f"    {key_txt}\t{value}")
        print()

    @staticmethod
    def complete(shell, word, line):
        return []
