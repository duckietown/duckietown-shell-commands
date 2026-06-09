import webbrowser

from dt_shell import DTCommandAbs, DTShell


class DTCommand(DTCommandAbs):
    help = "Opens the dashboard for a DT robot"

    @staticmethod
    def command(shell: DTShell, args, **kwargs):
        parsed = DTCommand._resolve_parsed(args, kwargs.get("parsed"))
        page = parsed.page.strip("/") if parsed.page else ""
        if page:
            page += "/"
        webbrowser.open(f"http://{parsed.robot}.local/dashboard/{page}")
