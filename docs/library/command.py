import webbrowser
from dt_shell import DTCommandAbs, DTShell


class DTCommand(DTCommandAbs):
    help = "Opens the DT Documentation Library"

    @staticmethod
    def command(shell: DTShell, args, **kwargs):
        parsed = DTCommand._resolve_parsed(args, kwargs.get("parsed"))
        if parsed.daffy:
            version = "daffy"
        else:
            version = "ente"
        webbrowser.open(f"https://docs.duckietown.com/{version}/")
