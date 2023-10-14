# NOTE: this file is ignored by duckietown-shell v6.0.0 and newer

import sys

import dt_shell
from dt_shell import dtslogger, UserError

from utils.misc_utils import parse_version, render_version

if sys.version_info < (3, 6):
    msg = "duckietown-shell-commands requires Python 3.6 and later.\nDetected %s." % str(sys.version)
    raise UserError(msg)

min_duckietown_shell = ".".join(["5", "5", "9"])
max_duckietown_shell_major: int = 99
duckietown_shell_commands_version = "6.0.0"


BILLBOARDS_DCSS_PREFIX = "assets/dts/billboard/content/"


def check_compatible():
    dtslogger.debug(f"duckietown-shell-commands version {duckietown_shell_commands_version}")
    from dt_shell import OtherVersions

    OtherVersions.name2versions["duckietown-shell-commands"] = duckietown_shell_commands_version

    vnow = parse_version(dt_shell.__version__)
    vneed = parse_version(min_duckietown_shell)

    if vnow[0] > max_duckietown_shell_major:
        msg = """

Detected Duckietown Shell %s but these commands (%s) only support up to Duckietown Shell v%s.
Please, downgrade your Duckietown Shell using the following command,
\n\n
        python3 -m pip install --no-cache-dir -U "duckietown-shell>=%s,<%s"
\n\n.
""" % (
            render_version(vnow),
            duckietown_shell_commands_version,
            max_duckietown_shell_major,
            render_version(vneed),
            max_duckietown_shell_major,
        )
        raise UserError(msg)

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


# noinspection PyUnresolvedReferences
from .command import DTCommand
