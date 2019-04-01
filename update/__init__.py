import sys

import dt_shell

if sys.version_info < (3, 6):
    msg = 'duckietown-shell-commands requires Python 3.6 and later. Detected %s.' % str(sys.version_info)
    sys.exit(msg)

from .command import *

min_duckietown_shell = '4.0.1'
duckietown_shell_commands_version = '4.0.1'


def parse_version(x):
    return tuple(int(_) for _ in x.split('.'))


def render_version(t):
    return ".".join(str(_) for _ in t)


def check_compatible():
    sys.stderr.write('Duckietown Shell commands version %s\n' % duckietown_shell_commands_version)
    OtherVersions = getattr(dt_shell, 'OtherVersions', {})
    OtherVersions.name2versions['duckietown-shell-commands'] = duckietown_shell_commands_version

    vnow = parse_version(dt_shell.__version__)
    vneed = parse_version(min_duckietown_shell)

    if vneed > vnow:
        msg = '''

Detected Duckietown Shell %s but these commands (%s) need Duckietown Shell >= %s.
''' % (render_version(vnow), duckietown_shell_commands_version, render_version(vneed))

        from dt_shell import UserError

        raise UserError(msg)


check_compatible()
