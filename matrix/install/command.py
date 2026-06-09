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
    get_latest_version, \
    get_os_family

from utils.misc_utils import versiontuple


class DTCommand(DTCommandAbs):

    help = f'Installs the {APP_NAME} application'

    @staticmethod
    def command(shell: DTShell, args, **kwargs):
        parsed = DTCommand._resolve_parsed(args, kwargs.get("parsed"))
        # ---
        if versiontuple(dt_data_api.__version__) < (1, 0, 1):
            dtslogger.error(f"You need to have the library dt-data-api>=1.0.1, "
                            f"the version {dt_data_api.__version__} was found instead.")
            return
        os_family = parsed.os_family
        webgl = parsed.webgl
        if os_family:
            if webgl:
                dtslogger.error("You cannot use -os/--os-family and --webgl together.")
                return
        else:
            os_family = get_os_family()
        version = parsed.version
        if version:
            latest_version = version
        else:
            # make sure the app is not already installed
            installed_version = get_most_recent_version_installed(os_family, webgl)
            if installed_version is not None and not parsed.update:
                dtslogger.info(f"Found version 'v{installed_version}' already installed. \nUse "
                            f"-U/--update to update to the latest version (if any is available).")
                return
            # get latest version available on the DCSS
            latest_version = get_latest_version(os_family, webgl)
        latest = latest_version + "-" + ("webgl" if webgl else os_family)
        if not version:
            # compare installed and latest versions
            if installed_version:
                if installed_version == latest:
                    return
                app_dir = os.path.join(APP_RELEASES_DIR, f"v{installed_version}")
                subprocess.check_call(["rm", "-rf", app_dir])
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
        zip_remote = remote_zip_obj(latest_version, os_family, webgl)
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
