import argparse
import os

from dt_shell import DTCommandAbs, DTShell


class DTCommand(DTCommandAbs):

    help = "Take a picture with a Duckiebot"

    @staticmethod
    def command(shell: DTShell, args):
        prog = "dts start_gui_tools DUCKIEBOT_NAME"
        parser = argparse.ArgumentParser(prog=prog)
        parser.add_argument("hostname", nargs="?", default=None, help="Name of the Duckiebot")
        parser.add_argument(
            "--pull",
            action="store_true",
            default=False,
            help="Pull the dt-gui-tools image",
        )
        # parse arguments
        parsed = parser.parse_args(args)
        # extend args
        parsed.launcher = "social"
        parsed.mount = f"{os.getcwd()}:/data/pictures"
        # call start_gui_tools
        shell.include.start_gui_tools.command(shell, args, parsed=parsed)
