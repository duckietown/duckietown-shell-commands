import argparse
import json
import os

from dt_shell import DTCommandAbs, dtslogger, DTShell
from utils.duckiematrix_utils import \
    APP_NAME, \
    get_most_recent_version_installed, \
    get_path_to_install, \
    get_os_family


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
        parser.add_argument(
            "--webgl",
            default=False,
            action="store_true",
            help="Show info about the WebGL version"
        )
        parsed, _ = parser.parse_known_args(args=args)
        return parsed

    @staticmethod
    def command(shell: DTShell, args, **kwargs):
        parsed = kwargs.get("parsed", None)
        if parsed is None:
            parsed = DTCommand._parse_args(args)
        # ---
        os_family = "webgl" if parsed.webgl else get_os_family()
        version = parsed.version if parsed.version else get_most_recent_version_installed(os_family)
        if version is None:
            dtslogger.error(
                f"Version v{parsed.version} not found."
                if parsed.version is not None else
                f"No versions found installed.")
            return
        # ---
        install_dir = get_path_to_install(version)
        capitalized_app_name = APP_NAME.capitalize()
        meta_fp = os.path.join(install_dir, f"{capitalized_app_name}.json")
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
