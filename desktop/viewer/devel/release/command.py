import os
from types import SimpleNamespace
from typing import Optional

import yaml
from utils.duckietown_viewer_utils import \
    DCSS_SPACE_NAME, \
    remote_zip_obj, \
    get_latest_version, \
    is_version_released, \
    mark_as_latest_version, \
    get_os_family
from utils.misc_utils import versiontuple

from dt_shell import DTCommandAbs, dtslogger, DTShell


class DTCommand(DTCommandAbs):

    help = f'Creates a new release of the Duckietown Viewer application and pushes it to the DCSS.'

    @staticmethod
    def command(shell: DTShell, args, **kwargs):
        parsed = kwargs.get("parsed", None)
        if parsed is None:
            parsed = DTCommand.parser.parse_args(args)
        # ---

        # make sure we are in the right place
        os_family = parsed.os_family or get_os_family()
        build_dir_rel = f"./release"
        build_dir = os.path.abspath(build_dir_rel)
        if not os.path.isdir(build_dir):
            dtslogger.error(f"Directory '{build_dir_rel}' not found. Are you running this command "
                            "from the root of the duckietown-viewer repository?")
            return

        # read latest-{os_family}.json
        yaml_fp = os.path.join(build_dir, f"latest-{os_family}.yml")
        if not os.path.isfile(yaml_fp):
            dtslogger.error(f"File '{build_dir_rel}/latest-{os_family}.yml' not found. "
                            f"Have you built the app?")
            return

        # load metadata
        with open(yaml_fp, "rt") as fin:
            meta = yaml.safe_load(fin.read())
        release_version = meta["version"]

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
        latest: Optional[str] = get_latest_version(os_family)
        if latest is not None and versiontuple(latest) > versiontuple(release_version):
            dtslogger.warn(f"The version v{latest} was found on the DCSS, are you releasing "
                           f"an older version? (use -f/--force to continue)")
            if not parsed.force:
                return
            else:
                dtslogger.warn("Forced!")

        # upload
        dtslogger.info(f"Uploading version v{release_version}...")
        local_file = os.path.join(build_dir, meta["path"])
        zip_remote = remote_zip_obj(release_version, os_family)
        shell.include.data.push.command(
            shell,
            [],
            parsed=SimpleNamespace(
                file=[local_file],
                object=[zip_remote],
                token=token,
                space=DCSS_SPACE_NAME,
                compress=True
            )
        )

        # mark this as latest (if needed)
        if latest is None or versiontuple(latest) < versiontuple(release_version):
            mark_as_latest_version(token, release_version, os_family)

        dtslogger.info(f"Congrats! You just released version v{release_version}.")

    @staticmethod
    def complete(shell, word, line):
        return []
