import glob
import os
import sys
from pathlib import Path
from threading import Thread
from typing import List, Optional, Dict

import dt_shell
from dt_shell import dtslogger, UserError
from dt_shell.constants import DTShellConstants

if sys.version_info < (3, 6):
    msg = "duckietown-shell-commands requires Python 3.6 and later.\nDetected %s." % str(sys.version)
    raise UserError(msg)

min_duckietown_shell = ".".join(["5", "5", "9"])
duckietown_shell_commands_version = "5.4.5"


BILLBOARDS_DCSS_PREFIX = "assets/dts/billboard/content/"


def parse_version(x):
    return tuple(int(_) for _ in x.split("."))


def render_version(t):
    return ".".join(str(_) for _ in t)


def check_compatible():
    dtslogger.debug(f"duckietown-shell-commands version {duckietown_shell_commands_version}")
    from dt_shell import OtherVersions

    OtherVersions.name2versions["duckietown-shell-commands"] = duckietown_shell_commands_version

    vnow = parse_version(dt_shell.__version__)
    vneed = parse_version(min_duckietown_shell)

    if vneed > vnow:
        msg = """

Detected Duckietown Shell %s but these commands (%s) need Duckietown Shell >= %s.
Please, update your Duckietown Shell using the following command,
\n\n
        python3 -m pip install --no-cache-dir -U "duckietown-shell>=%s"
\n\n.
""" % (
            render_version(vnow),
            duckietown_shell_commands_version,
            render_version(vneed),
            render_version(vneed),
        )

        raise UserError(msg)


check_compatible()


def update_billboard():
    import dt_data_api

    if parse_version(dt_data_api.__version__) < (1, 2, 0):
        # billboards are only supported with dt_data_api 1.2.0+
        return

    from dt_data_api import DataClient, Storage, Item

    # create billboards directory
    billboard_dir: str = os.path.join(os.path.expanduser(DTShellConstants.ROOT), "billboards", "v1")
    os.makedirs(billboard_dir, exist_ok=True)
    try:
        # open public storage
        dcss: DataClient = DataClient()
        storage: Storage = dcss.storage("public")
        # list all billboards on the cloud and locally
        remotes: List[Item] = storage.list_objects(BILLBOARDS_DCSS_PREFIX, items=True)
        locals: List[str] = [Path(src).stem for src in glob.glob(os.path.join(billboard_dir, "*"))]
        # billboard map, if value=None, the billboard does not exist on the cloud anymore
        billboards: Dict[str, Optional[str]] = {}
        # - add local billboards
        billboards.update({etag: None for etag in locals})
        # - add remote billboards
        billboards.update({r.etag: r.key for r in remotes})
        # remove old billboards
        for etag in locals:
            if billboards[etag] is None:
                # billboard does not exist on remote, remove
                dst: str = os.path.join(billboard_dir, f"{etag}.txt")
                dtslogger.debug(f"Removing old billboard file: {dst}")
                os.remove(dst)
        # download new billboards
        for remote in remotes:
            # compile local path
            dst: str = os.path.join(billboard_dir, f"{remote.etag}.txt")
            if os.path.exists(dst):
                # billboard already downloaded
                dtslogger.debug(f"Billboard [{remote.etag}] up-to-date!")
                continue
            # billboard needs to be downloaded
            src: str = billboards[remote.etag]
            dtslogger.debug(f"Downloading billboard public:[{src}] -> file:[{dst}]")
            storage.download(src, dst)
        # ---
        dtslogger.debug(f"All billboards downloaded!")

    except BaseException as e:
        dtslogger.warning(f"An error occurred while updating the billboards: {e}")
        return


# TODO: disabled to avoid exploding charges on AWS S3 due to high number of requests
Thread(target=update_billboard, daemon=True).start()
# TODO: disabled to avoid exploding charges on AWS S3 due to high number of requests


# noinspection PyUnresolvedReferences
from .command import DTCommand
