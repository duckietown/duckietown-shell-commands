import argparse
from typing import Optional, List

from dt_shell.commands import DTCommandConfigurationAbs
from dt_shell.environments import ShellCommandEnvironmentAbs


class DTCommandConfiguration(DTCommandConfigurationAbs):

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
        parser = argparse.ArgumentParser("dts duckiebot keyboard_control")
        parser.add_argument(
            "-vv",
            default=False,
            action="store_true",
            help="Run in verbose mode"
        )
        parser.add_argument(
            "robot",
            help="Name of the robot to control"
        )
        return parser

    @classmethod
    def aliases(cls) -> List[str]:
        """
        Alternative names for this command.
        """
        return ["keyboard_controller", "joystick_control", "joystick", "jc", "joy"]
