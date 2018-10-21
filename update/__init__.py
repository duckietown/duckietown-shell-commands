from .command import *

min_duckietown_shell = '3.0.24'
duckietown_shell_commands_version = '1.0.10'


def parse_version(x):
    return tuple(int(_) for _ in x.split('.'))


def render_version(t):
    return ".".join(str(_) for _ in t)


def check_compatible():
    import sys
    import dt_shell
    sys.stderr.write('Duckietown Shell commands version %s\n' % duckietown_shell_commands_version)
    OtherVersions = getattr(dt_shell, 'OtherVersions', {})
    OtherVersions.name2versions['duckietown-shell-commands'] = duckietown_shell_commands_version

    vnow = parse_version(dt_shell.__version__)
    vneed = parse_version(min_duckietown_shell)

    if vneed > vnow:
        msg = '''\

Detected Duckietown Shell %s but these commands (%s) need Duckietown Shell >= %s.
''' % (render_version(vnow), duckietown_shell_commands_version, render_version(vneed))

        from dt_shell import UserError

        raise UserError(msg)


check_compatible()
