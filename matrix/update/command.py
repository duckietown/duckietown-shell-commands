from types import SimpleNamespace

from dt_shell import DTCommandAbs, DTShell

from utils.duckiematrix_utils import \
    APP_NAME


class DTCommand(DTCommandAbs):

    help = f'Updates the {APP_NAME} application'

    @staticmethod
    def command(shell: DTShell, args, **kwargs):
        parsed = DTCommand._resolve_parsed(args, kwargs.get("parsed"))
        # ---
        shell.include.matrix.install.command(
            shell,
            [],
            parsed=SimpleNamespace(
                version=parsed.version,
                force=parsed.force,
                update=True,
                os_family=parsed.os_family,
                webgl=parsed.webgl,
            )
        )

    @staticmethod
    def complete(shell, word, line):
        return []
