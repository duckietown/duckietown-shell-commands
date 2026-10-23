import os
from pathlib import Path
import re
import tempfile
from types import SimpleNamespace

import dt_data_api
import requests

from dt_shell import DTCommandAbs, dtslogger, DTShell
from dt_shell.exceptions import UserError
from dt_shell.renderer import install_renderer_archive, verify_renderer_release
from utils.data_endpoint_utils import create_data_client
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
        target = "webgl" if webgl else os_family
        if target not in ("linux", "macos", "windows", "webgl"):
            raise UserError(f"Unsupported renderer platform '{target}'.")
        version = parsed.version
        if version and re.fullmatch(r"\d+\.\d+\.\d+", version) is None:
            raise UserError("A renderer version must have the form 0.12.0.")
        data_client = create_data_client(shell)
        installed_version = None
        installed_verified = False
        network_errors = (
            OSError, requests.RequestException, dt_data_api.APIError, dt_data_api.TransferError,
        )
        if version:
            latest_version = version
        else:
            # make sure the app is not already installed
            installed_version = get_most_recent_version_installed(os_family, webgl)
            if installed_version is not None:
                installed_path = get_path_to_install(os_family, installed_version, webgl)
                try:
                    verify_renderer_release(
                        Path(installed_path), version=installed_version, os_family=target,
                    )
                    installed_verified = True
                except UserError as error:
                    dtslogger.warning(f"The installed renderer is not a verified release: {error}")
            if installed_version is not None and not parsed.update:
                if not installed_verified:
                    raise UserError("Reinstall the renderer with 'dts matrix install --update --force'.")
                dtslogger.info(f"Found version 'v{installed_version}' already installed. \nUse "
                            f"-U/--update to update to the latest version (if any is available).")
                return
            # get latest version available on the DCSS
            try:
                latest_version = get_latest_version(os_family, webgl, client=data_client)
            except network_errors as error:
                if not installed_verified:
                    raise UserError(f"Could not check renderer releases and no verified installation is available: {error}") from error
                dtslogger.warning(
                    f"Could not check for renderer updates: {error}. "
                    f"Using the verified installed version v{installed_version}."
                )
                return
        if re.fullmatch(r"\d+\.\d+\.\d+", latest_version) is None:
            raise UserError("The renderer service returned an invalid version.")
        latest = latest_version + "-" + ("webgl" if webgl else os_family)
        app_dir = os.path.join(APP_RELEASES_DIR, f"v{latest}")
        remote_checksum = None
        if os.path.isdir(app_dir):
            verified = False
            try:
                verify_renderer_release(Path(app_dir), version=latest_version, os_family=target)
                verified = True
            except UserError as error:
                dtslogger.warning(f"The installed renderer failed verification and will be replaced: {error}")
            try:
                remote_checksum = get_remote_release_checksum(
                    latest_version, os_family, webgl, client=data_client
                )
            except network_errors as error:
                dtslogger.warning(f"Could not fetch release metadata for 'v{latest}': {error}")
            local_checksum = get_installed_release_checksum(os_family, latest_version, webgl)
            if verified and not parsed.force and remote_checksum is None:
                dtslogger.info(f"You already have version 'v{latest}' installed.")
                return
            if verified and not parsed.force and local_checksum == remote_checksum:
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
        # download
        dtslogger.info(f"Downloading version v{latest}...")
        zip_remote = remote_zip_obj(latest_version, os_family, webgl)
        os.makedirs(APP_RELEASES_DIR, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".renderer-download-", dir=APP_RELEASES_DIR) as temporary:
            zip_local = Path(temporary) / "release.zip"
            try:
                shell.include.data.get.command(
                    shell,
                    [],
                    parsed=SimpleNamespace(
                        object=[zip_remote],
                        file=[str(zip_local)],
                        space=DCSS_SPACE_NAME,
                    )
                )
            except network_errors as error:
                raise UserError(
                    f"Could not download the renderer; the existing installation was not changed: {error}"
                ) from error
            if not zip_local.is_file():
                raise UserError("The renderer download did not produce an archive.")
            dtslogger.info("Verifying and installing the signed renderer release...")
            install_renderer_archive(
                zip_local, Path(app_dir), version=latest_version, os_family=target,
            )
        if remote_checksum is None:
            try:
                remote_checksum = get_remote_release_checksum(
                    latest_version, os_family, webgl, client=data_client
                )
            except network_errors as error:
                dtslogger.warning(f"Could not fetch optional release checksum metadata for 'v{latest}': {error}")
        if remote_checksum is not None:
            try:
                write_installed_release_checksum(app_dir, remote_checksum)
            except OSError as error:
                dtslogger.warning(f"Installed the verified renderer, but could not save optional checksum metadata: {error}")
        # ---
        dtslogger.info("Installation completed successfully!")

    @staticmethod
    def complete(shell, word, line):
        return []
