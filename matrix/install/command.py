import os
import subprocess
from types import SimpleNamespace

import dt_data_api

from dt_shell import DTCommandAbs, dtslogger, DTShell
from utils.duckiematrix_utils import \
    APP_NAME, \
    DCSS_SPACE_NAME, \
    APP_RELEASES_DIR, \
    get_installed_release_checksum, \
    get_most_recent_version_installed, \
    get_path_to_install, \
    get_remote_release_checksum, \
    remote_zip_obj, \
    get_latest_version, \
    get_os_family, \
    write_installed_release_checksum

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
        installed_version = None
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
        app_dir = os.path.join(APP_RELEASES_DIR, f"v{latest}")
        remote_checksum = None
        if os.path.isdir(app_dir):
            try:
                remote_checksum = get_remote_release_checksum(latest_version, os_family, webgl)
            except Exception as e:
                dtslogger.debug(f"Could not fetch release checksum for 'v{latest}': {e}")
            local_checksum = get_installed_release_checksum(os_family, latest_version, webgl)
            if not parsed.force and remote_checksum is None:
                dtslogger.info(f"You already have version 'v{latest}' installed.")
                return
            if not parsed.force and local_checksum == remote_checksum:
                dtslogger.info(f"You already have version 'v{latest}' installed.")
                return
            if not parsed.force:
                if local_checksum is None:
                    dtslogger.info(
                        f"Installed version 'v{latest}' has no stored checksum."
                    )
                else:
                    dtslogger.info(
                        f"Installed version 'v{latest}' differs from the release checksum."
                    )
            dtslogger.info(f"Removing installed version 'v{latest}'...")
            subprocess.check_call(["rm", "-rf", app_dir])
        elif not version and installed_version is not None and installed_version != latest_version:
            installed_app_dir = get_path_to_install(os_family, installed_version, webgl)
            if installed_app_dir is not None:
                dtslogger.info(
                    f"Removing installed version 'v{installed_version}-{('webgl' if webgl else os_family)}'..."
                )
                subprocess.check_call(["rm", "-rf", installed_app_dir])
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
        if remote_checksum is None:
            try:
                remote_checksum = get_remote_release_checksum(latest_version, os_family, webgl)
            except Exception as e:
                dtslogger.debug(f"Could not store release checksum for 'v{latest}': {e}")
        if remote_checksum is not None:
            write_installed_release_checksum(app_dir, remote_checksum)
        # clean up
        dtslogger.info("Removing temporary files...")
        os.remove(zip_local)
        # ---
        dtslogger.info("Installation completed successfully!")

    @staticmethod
    def complete(shell, word, line):
        return []
