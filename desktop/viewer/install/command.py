import os
import subprocess
from types import SimpleNamespace

from utils.duckietown_viewer_utils import \
    APP_NAME, \
    DCSS_SPACE_NAME, \
    APP_RELEASES_DIR, \
    get_most_recent_version_installed, \
    remote_zip_obj, \
    get_latest_version

from dt_shell import DTCommandAbs, dtslogger, DTShell


class DTCommand(DTCommandAbs):

    help = f'Installs the {APP_NAME} application'

    @staticmethod
    def command(shell: DTShell, args, **kwargs):
        parsed = kwargs.get("parsed", None)
        if parsed is None:
            parsed = DTCommand.parser.parse_args(args)
        # ---

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

    @staticmethod
    def complete(shell, word, line):
        return []
