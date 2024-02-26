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

from utils.misc_utils import versiontuple


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
        if versiontuple(dt_data_api.__version__) < (1, 0, 1):
            dtslogger.error(f"You need to have the library dt-data-api>=1.0.1, "
                            f"the version {dt_data_api.__version__} was found instead.")
            return
        # make sure the app is not already installed
        installed_version = get_most_recent_version_installed()
        if installed_version is not None and not parsed.update:
            dtslogger.info(f"Found version 'v{installed_version}' already installed. \nUse "
                           f"-U/--update to update to the latest version (if any is available).")
            return
        # get latest version available on the DCSS
        latest = get_latest_version()
        # make sure the same version is not already installed (unless forced)
        app_dir = os.path.join(APP_RELEASES_DIR, f"v{latest}")
        if os.path.isdir(app_dir):
            if not parsed.force:
                dtslogger.info("You already have the latest version installed.")
                return
            else:
                dtslogger.info(f"Removing installed version 'v{latest}'...")
                subprocess.check_call(["rm", "-rf", app_dir])
        # download
        dtslogger.info(f"Downloading version v{latest}...")
        os.makedirs(app_dir)
        zip_remote = remote_zip_obj(latest)
        zip_local = os.path.join(app_dir, f"v{latest}.zip")
        shell.include.data.get.command(
            shell,
            [],
            parsed=SimpleNamespace(
                object=[zip_remote],
                file=[zip_local],
                space=DCSS_SPACE_NAME,
            )
        )
        dtslogger.info("Download completed.")
        # install
        dtslogger.info("Installing...")
        subprocess.check_call(["unzip", f"v{latest}.zip"], cwd=app_dir)
        # clean up
        dtslogger.info("Removing temporary files...")
        os.remove(zip_local)
        # ---
        dtslogger.info("Installation completed successfully!")
        dtslogger.info("""
        
        You can now run the Duckiematrix application using the command:
        
            >   dts matrix run --standalone --sandbox
        
        """)

    @staticmethod
    def complete(shell, word, line):
        return []
