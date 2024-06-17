from types import SimpleNamespace

from utils.duckietown_viewer_utils import \
    APP_NAME

from dt_shell import DTCommandAbs, DTShell


class DTCommand(DTCommandAbs):

    help = f'Updates the {APP_NAME} application'

    @staticmethod
    def command(shell: DTShell, args, **kwargs):
        parsed = kwargs.get("parsed", None)
        if parsed is None:
            parsed = DTCommand.parser.parse_args(args)
        # ---

        shell.include.desktop.viewer.install.command(
            shell,
            [],
            parsed=SimpleNamespace(
                version=parsed.version,
                force=parsed.force,
                update=True,
            )
        )

    @staticmethod
    def complete(shell, word, line):
        return []
