import sys

import dt_shell
from dt_shell import dtslogger, UserError

if sys.version_info < (3, 6):
    msg = "duckietown-shell-commands requires Python 3.6 and later.\nDetected %s." % str(sys.version)
    raise UserError(msg)

min_duckietown_shell = ".".join(["5", "1", "16"])
duckietown_shell_commands_version = "5.1.0"


def parse_version(x):
    return tuple(int(_) for _ in x.split("."))


def render_version(t):
    return ".".join(str(_) for _ in t)


def check_compatible():
    dtslogger.info("duckietown-shell-commands %s" % duckietown_shell_commands_version)
    from dt_shell import OtherVersions

    OtherVersions.name2versions["duckietown-shell-commands"] = duckietown_shell_commands_version

    vnow = parse_version(dt_shell.__version__)
    vneed = parse_version(min_duckietown_shell)

    if vneed > vnow:
        msg = """

Detected Duckietown Shell %s but these commands (%s) need Duckietown Shell >= %s.
Please, update your Duckietown Shell using the following command,
\n\n
        pip3 install --no-cache-dir -U "duckietown-shell>=%s"
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
