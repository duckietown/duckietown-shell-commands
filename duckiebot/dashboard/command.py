import webbrowser

from dt_shell import DTCommandAbs, DTShell
from utils.networking_utils import best_host_for_robot


class DTCommand(DTCommandAbs):
    help = "Opens the dashboard for a DT robot"

    @staticmethod
    def command(shell: DTShell, args, **kwargs):
        parsed = DTCommand._resolve_parsed(args, kwargs.get("parsed"))
        page = parsed.page.strip("/") if parsed.page else ""
        if page:
            page += "/"
        hostname = best_host_for_robot(parsed.robot)
        webbrowser.open(f"http://{hostname}/dashboard/{page}")
