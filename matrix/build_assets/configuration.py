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
        parser = argparse.ArgumentParser(prog="dts matrix build_assets")
        parser.add_argument(
            "-m",
            "--map",
            required=True,
            type=str,
            help="Directory containing the map to build the assets for",
        )
        parser.add_argument(
            "-vv",
            "--verbose",
            default=False,
            action="store_true",
            help="Run in verbose mode",
        )
        return parser

    @classmethod
    def aliases(cls) -> List[str]:
        """
        Alternative names for this command.
        """
        return []
