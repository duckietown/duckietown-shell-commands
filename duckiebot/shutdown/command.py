import argparse
import requests

from dt_shell import DTCommandAbs, dtslogger
from dt_shell import DTShell

from utils.misc_utils import sanitize_hostname


class DTCommand(DTCommandAbs):
    @staticmethod
    def command(shell: DTShell, args):
        prog = "dts duckiebot shutdown"
        parser = argparse.ArgumentParser(prog=prog)
        parser.add_argument(
            "robot",
            nargs=1,
            type=str,
            help="Duckiebot to shutdown",
        )
        parsed = parser.parse_args(args)
        # ---
        robot = parsed.robot[0]
        hostname = sanitize_hostname(robot)
        # ---
        dtslogger.info(f"Shutting down {robot}...")
        url = f"http://{hostname}/health/trigger/shutdown?token="
        try:
            dtslogger.debug(f"Calling URL '{url}'...")
            data = requests.get(url).json()
            assert data['status'] == 'needs-confirmation'
            assert 'token' in data
            url += data['token']
            dtslogger.debug(f"Calling URL '{url}'...")
            res = requests.get(url).json()
            assert res['status'] == 'ok'
        except BaseException as e:
            dtslogger.error(str(e))
            return
        # ---
        dtslogger.info("Signal sent, the robot should shutdown soon.")
