import webbrowser

from dt_shell import DTCommandAbs, DTShell
from utils.networking_utils import best_host_for_robot


class DTCommand(DTCommandAbs):
    help = "Opens the DT Postal Service (DTPS) topic list for a DT robot"

    @staticmethod
    def command(shell: DTShell, args, **kwargs):
        parsed = DTCommand._resolve_parsed(args, kwargs.get("parsed"))
        port = 11411 if parsed.kv_store else 11911
        topic = parsed.topic.strip("/") if parsed.topic else ""
        if topic:
            topic += "/"
        hostname = best_host_for_robot(parsed.robot)
        webbrowser.open(f"http://{hostname}:{port}/{topic}")
