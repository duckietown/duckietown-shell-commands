import argparse
from dt_shell.commands import DTCommandConfigurationAbs
from dt_shell.environments import ShellCommandEnvironmentAbs
from typing import Optional, List
from utils.duckietown_viewer_utils import SUPPORTED_OS_FAMILIES

class DTCommandConfiguration(DTCommandConfigurationAbs):
    @classmethod
    def aliases(cls) -> List[str]:
        """
        Alternative names for this command.
        """
        return ["intrinsics_calibrator"]

    @classmethod
    def environment(cls, *args, **kwargs) -> Optional[ShellCommandEnvironmentAbs]:
        """
        The environment in which this command will run.
        """
        return None

    @classmethod
    def parser(cls, *args, **kwargs) -> Optional[argparse.ArgumentParser]:
        """
        The parser this command will use.
        """
        parser = argparse.ArgumentParser("dts duckiebot calibrate_intrinsics")
        parser.add_argument(
            "--fullscreen",
            default=False,
            action="store_true",
            help="Run in fullscreen mode"
        )
        parser.add_argument(
            "--on-top",
            default=False,
            action="store_true",
            help="Always stay on top of other windows"
        )
        parser.add_argument(
            "--verbose",
            "-vv",
            dest="verbose",
            default=False,
            action="store_true",
            help="Run in verbose mode"
        )
        parser.add_argument(
            "--enable-hardware-acceleration",
            default=False,
            action="store_true",
            help="Enable hardware acceleration"
        )
        parser.add_argument(
            "--browser",
            default=False,
            action="store_true",
            help="Run in browser mode"
        )
        parser.add_argument(
            "--no-pull",
            default=False,
            action="store_true",
            help="Do not attempt to update the backend container image"
        )
        parser.add_argument(
            "-os",
            "--os-family",
            default="",
            type=str,
            choices=SUPPORTED_OS_FAMILIES,
            help="Run for a given os-family",
        )
        parser.add_argument(
            "robot",
            help="Name of the robot to connect to"
        )
        return parser
