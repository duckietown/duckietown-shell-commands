import argparse
import json
import os
from types import SimpleNamespace

import dt_data_api

from dt_shell import DTCommandAbs, dtslogger, DTShell
from utils.duckiematrix_utils import \
    APP_NAME, \
    DCSS_SPACE_NAME, \
    remote_zip_obj, \
    get_latest_version, \
    is_version_released, \
    mark_as_latest_version, \
    get_os_family

from utils.misc_utils import versiontuple


class DTCommand(DTCommandAbs):

    help = f'Creates a new release of the {APP_NAME} application and pushes it to the DCSS.'

    @staticmethod
    def _parse_args(args):
        # configure arguments
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "-f",
            "--force",
            default=None,
            action="store_true",
            help="Force upload when the same version already exists on the DCSS",
        )
        parser.add_argument(
            "-os",
            "--os-family",
            default=None,
            type=str,
            help="Release for a given os-family",
        )
        parser.add_argument(
            "-t",
            "--token",
            default=None,
            help="(Optional) Duckietown token to use for the upload action",
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

        # make sure we are in the right place
        os_family = parsed.os_family or get_os_family()
        build_dir_rel = f"./Release/{os_family}"
        build_dir = os.path.abspath(build_dir_rel)
        if not os.path.isdir(build_dir):
            dtslogger.error(f"Directory '{build_dir_rel}' not found. Are you running this command "
                            "from the root of the duckiematrix project?")
            return

        # read app.json
        json_fp = os.path.join(build_dir, f"{APP_NAME}.json")
        if not os.path.isfile(json_fp):
            dtslogger.error(f"File '{build_dir_rel}/{APP_NAME}.json' not found. "
                            f"Did you build the app?")
            return

        # load metadata
        with open(json_fp, "rt") as fin:
            meta = json.loads(fin.read())
        release_version = meta["version"]
        os_family = meta["target"]["operating_system_family"].lower()

        # make sure we have a token
        token: str = parsed.token
        if token is None:
            token = shell.profile.secrets.dt_token

        # check whether the same version was already released
        if is_version_released(release_version, os_family):
            dtslogger.warn(f"The version v{release_version} for OS Family '{os_family}' was found "
                           f"already on the DCSS, are you re-releasing this version? "
                           f"(use -f/--force to continue)")
            if not parsed.force:
                return
            else:
                dtslogger.warn("Forced!")

        # check whether we are releasing an older version
        latest = get_latest_version(os_family)
        if versiontuple(latest) > versiontuple(release_version):
            dtslogger.warn(f"The version v{latest} was found on the DCSS, are you releasing "
                           f"an older version? (use -f/--force to continue)")
            if not parsed.force:
                return
            else:
                dtslogger.warn("Forced!")

        # upload
        dtslogger.info(f"Uploading version v{release_version}...")
        zip_remote = remote_zip_obj(release_version, os_family)
        shell.include.data.push.command(
            shell,
            [],
            parsed=SimpleNamespace(
                file=[build_dir],
                object=[zip_remote],
                token=token,
                space=DCSS_SPACE_NAME,
                exclude="duckiematrix_BackUpThisFolder_ButDontShipItWithYourGame/*,"
                        "duckiematrix_BurstDebugInformation_DoNotShip/*",
                compress=True
            )
        )

        # mark this as latest (if needed)
        if versiontuple(latest) < versiontuple(release_version):
            mark_as_latest_version(token, release_version, os_family)

        dtslogger.info(f"Congrats! You just released version v{release_version}.")

    @staticmethod
    def complete(shell, word, line):
        return []
