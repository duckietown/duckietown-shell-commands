from utils.duckietown_viewer_utils import \
    APP_NAME, \
    ensure_duckietown_viewer_installed

from dt_shell import DTCommandAbs, DTShell


class DTCommand(DTCommandAbs):

    help = f'Installs the {APP_NAME} application'

    @staticmethod
    def command(shell: DTShell, args, **kwargs):
        parsed = DTCommand._resolve_parsed(args, kwargs.get("parsed"))
        # ---
        ensure_duckietown_viewer_installed(
            version=parsed.version,
            update=bool(parsed.update),
            force=bool(parsed.force),
        )

    @staticmethod
    def complete(shell, word, line):
        return []
