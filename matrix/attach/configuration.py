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
        parser = argparse.ArgumentParser(prog="dts matrix attach")
        parser.add_argument(
            "-e",
            "--engine",
            dest="engine_hostname",
            default=None,
            type=str,
            help="Hostname or IP address of the engine to attach the robot to"
        )
        parser.add_argument(
            "-d",
            "--dreamwalk",
            default=False,
            action="store_true",
            help="Enable dreamwalking (physical robots only)"
        )
        parser.add_argument("robot", nargs=1, help="Name of the robot to attach to the Matrix")
        parser.add_argument("entity", nargs=1, help="Name of the Duckiematrix entity to attach the robot to")
        # ---
        return parser

    @classmethod
    def aliases(cls) -> List[str]:
        """
        Alternative names for this command.
        """
        return []
