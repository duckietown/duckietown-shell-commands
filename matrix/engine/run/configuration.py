import argparse
from typing import Optional, List

from dt_shell.commands import DTCommandConfigurationAbs


class DTCommandConfiguration(DTCommandConfigurationAbs):

    @classmethod
    def parser(cls, *args, **kwargs) -> Optional[argparse.ArgumentParser]:
        """
        The parser this command will use.
        """
        # configure arguments
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "-m",
            "--map",
            default=None,
            type=str,
            help="Directory containing the map to load"
        )
        parser.add_argument(
            "--sandbox",
            default=False,
            action="store_true",
            help="Run in a sandbox map"
        )
        parser.add_argument(
            "-n",
            "--renderers",
            default=1,
            type=int,
            help="(Advanced) Number of renderers to run"
        )
        parser.add_argument(
            "--gym",
            "--simulation",
            dest="simulation",
            default=False,
            action="store_true",
            help="Run in simulation mode"
        )
        parser.add_argument(
            "-t", "-dt",
            "--delta-t",
            default=None,
            type=float,
            help="Time step (gym mode only)",
        )
        parser.add_argument(
            "--link",
            dest="links",
            nargs=2,
            action="append",
            default=[],
            metavar=("matrix", "world"),
            help="Link robots inside the matrix to robots outside",
        )
        parser.add_argument(
            "--build-assets",
            default=False,
            action="store_true",
            help="Build assets and exit"
        )
        parser.add_argument(
            "--no-pull",
            default=False,
            action="store_true",
            help="Do not attempt to update the engine container image"
        )
        parser.add_argument(
            "--expose-ports",
            default=False,
            action="store_true",
            help="Expose all the ports with the host"
        )
        parser.add_argument(
            "--static-ports",
            default=False,
            action="store_true",
            help="Assign default values to all the ports"
        )
        parser.add_argument(
            "-vv",
            "--verbose",
            default=False,
            action="store_true",
            help="Run in verbose mode"
        )
        # ---
        return parser

    @classmethod
    def aliases(cls) -> List[str]:
        """
        Alternative names for this command.
        """
        return ["buildx"]
