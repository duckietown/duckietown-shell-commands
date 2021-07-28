import argparse

import yaml
import requests
from dt_shell import DTCommandAbs, dtslogger, DTShell

from utils.misc_utils import sanitize_hostname


class DTCommand(DTCommandAbs):

    help = "Shows info about the battery"

    @staticmethod
    def command(shell: DTShell, args):
        prog = "dts duckiebot battery info DUCKIEBOT_NAME"
        parser = argparse.ArgumentParser(prog=prog)
        parser.add_argument("duckiebot", default=None, help="Name of the Duckiebot")
        parsed = parser.parse_args(args)
        # fetch data from the health API
        hostname = sanitize_hostname(parsed.duckiebot)
        url = f"http://{hostname}/health/battery"
        dtslogger.info(f"Fetching data from robot '{parsed.duckiebot}'...")
        data = requests.get(url).json()
        print(yaml.dump(data))
