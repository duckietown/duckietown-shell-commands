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

    help = 'Creates new release(s) of the Duckietown Viewer application and pushes them to the DCSS. Supports releasing multiple architectures.'

    @staticmethod
    def command(shell: DTShell, args, **kwargs):
        parsed = DTCommand._resolve_parsed(args, kwargs.get("parsed"))
        # ---

        # make sure we are in the right place
        build_dir_rel = "./release"
        build_dir = os.path.abspath(build_dir_rel)
        if not os.path.isdir(build_dir):
            dtslogger.error(f"Directory '{build_dir_rel}' not found. Are you running this command "
                            "from the root of the duckietown-viewer repository?")
            return

        # determine which OS families to release
        os_families = []
        if parsed.all_archs:
            # find all available latest-*.yml files
            import glob
            yaml_files = glob.glob(os.path.join(build_dir, "latest-*.yml"))
            os_families = [os.path.basename(fp)[7:-4] for fp in yaml_files]  # extract os_family from filename
            if not os_families:
                dtslogger.error("No latest-*.yml files found in the release directory.")
                return
            dtslogger.info(f"Found architectures: {', '.join(os_families)}")
        elif parsed.os_family:
            os_families = parsed.os_family
        else:
            os_families = [get_os_family()]

        # make sure we have a token
        token: str = parsed.token
        if token is None:
            token = shell.profile.secrets.dt_token

        # release each OS family
        for os_family in os_families:
            DTCommand._release_single_architecture(shell, os_family, build_dir, build_dir_rel, token, parsed.force)

        dtslogger.info(f"Congrats! You just released {len(os_families)} architecture(s): {', '.join(os_families)}.")

    @staticmethod
    def _release_single_architecture(shell: DTShell, os_family: str, build_dir: str, build_dir_rel: str, token: str, force: bool):
        dtslogger.info(f"\n--- Releasing {os_family} ---")
        
        # read latest-{os_family}.yml
        yaml_fp = os.path.join(build_dir, f"latest-{os_family}.yml")
        if not os.path.isfile(yaml_fp):
            dtslogger.error(f"File '{build_dir_rel}/latest-{os_family}.yml' not found. "
                            f"Have you built the {os_family} app?")
            return

        # load metadata
        with open(yaml_fp, "rt") as fin:
            meta = yaml.safe_load(fin.read())
        release_version = meta["version"]

        dtslogger.info(f"Release version: v{release_version}")

        # check whether the same version was already released
        if is_version_released(release_version, os_family):
            dtslogger.warn(f"The version v{release_version} for OS Family '{os_family}' was found "
                           f"already on the DCSS, are you re-releasing this version? "
                           f"(use -f/--force to continue)")
            if not force:
                dtslogger.warn(f"Skipping {os_family} release.")
                return
            else:
                dtslogger.warn("Forced!")

        # check whether we are releasing an older version
        latest: Optional[str] = get_latest_version(os_family)
        if latest is not None and versiontuple(latest) > versiontuple(release_version):
            dtslogger.warn(f"The version v{latest} was found on the DCSS, are you releasing "
                           f"an older version? (use -f/--force to continue)")
            if not force:
                dtslogger.warn(f"Skipping {os_family} release.")
                return
            else:
                dtslogger.warn("Forced!")

        # upload
        dtslogger.info(f"Uploading {os_family} version v{release_version}...")
        local_file = os.path.join(build_dir, meta["path"])
        if not os.path.isfile(local_file):
            dtslogger.error(f"Local file '{local_file}' not found for {os_family}.")
            return
            
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

        dtslogger.info(f"Successfully released {os_family} v{release_version}.")

    @staticmethod
    def complete(shell, word, line):
        return []
