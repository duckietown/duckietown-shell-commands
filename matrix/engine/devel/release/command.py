from dt_shell import DTCommandAbs, DTShell
from utils.engine_authorization import publish


class DTCommand(DTCommandAbs):
    help = "Publish an already-signed Duckiematrix Engine image catalog."

    @staticmethod
    def command(shell: DTShell, args, **kwargs):
        return publish(shell, DTCommand._resolve_parsed(args, kwargs.get("parsed")))
