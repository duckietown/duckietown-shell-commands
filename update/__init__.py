import os
import shutil
import sys
from threading import Thread
from typing import List

import dt_shell
from dt_data_api import DataClient, Storage
from dt_shell import dtslogger, UserError
from dt_shell.constants import DTShellConstants

if sys.version_info < (3, 6):
    msg = "duckietown-shell-commands requires Python 3.6 and later.\nDetected %s." % str(sys.version)
    raise UserError(msg)

min_duckietown_shell = ".".join(["5", "2", "21"])
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
    # create billboards directory
    billboard_dir: str = os.path.join(os.path.expanduser(DTShellConstants.ROOT), "billboards")
    try:
        # open public storage
        dcss: DataClient = DataClient()
        storage: Storage = dcss.storage("public")
        # list all billboards on the cloud
        sources: List[str] = storage.list_objects(BILLBOARDS_DCSS_PREFIX)
        # clear local billboards
        os.makedirs(billboard_dir, exist_ok=True)
        shutil.rmtree(billboard_dir)
        os.makedirs(billboard_dir, exist_ok=True)
        # download billboards
        for source in sources:
            destination = os.path.join(billboard_dir, os.path.basename(source))
            storage.download(source, destination)
    except BaseException as e:
        dtslogger.debug(f"An error occurred while updating the billboards: {e}")
        return


# TODO: disabled to avoid exploding charges on AWS S3 due to high number of requests
Thread(target=update_billboard, daemon=True).start()
# TODO: disabled to avoid exploding charges on AWS S3 due to high number of requests


# noinspection PyUnresolvedReferences
from .command import DTCommand
