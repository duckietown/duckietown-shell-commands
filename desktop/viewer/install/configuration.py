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
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "-U",
            "--update",
            default=None,
            action="store_true",
            help="Update if already installed",
        )
        parser.add_argument(
            "-f",
            "--force",
            default=None,
            action="store_true",
            help="Force reinstall when the same version is already installed",
        )
        parser.add_argument(
            "-v",
            "--version",
            default=None,
            type=str,
            help="Install a specific version"
        )
        return parser

    @classmethod
    def aliases(cls) -> List[str]:
        """
        Alternative names for this command.
        """
        return []
