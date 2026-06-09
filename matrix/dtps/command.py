import webbrowser

from dt_shell import DTCommandAbs, DTShell

DEFAULT_DUCKIEMATRIX_ENGINE_PORT = 7501


class DTCommand(DTCommandAbs):
    help = "Opens the DT Postal Service (DTPS) topic list for the Duckiematrix"

    @staticmethod
    def command(shell: DTShell, args, **kwargs):
        parsed = DTCommand._resolve_parsed(args, kwargs.get("parsed"))
        engine_hostname = parsed.engine_hostname if parsed.engine_hostname is not None else "localhost"
        topic = parsed.topic.strip("/") if parsed.topic else ""
        if topic:
            topic += "/"
        webbrowser.open(f"http://{engine_hostname}:{DEFAULT_DUCKIEMATRIX_ENGINE_PORT}/{topic}")
