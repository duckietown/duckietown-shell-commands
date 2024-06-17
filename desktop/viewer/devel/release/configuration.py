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
            "-f",
            "--force",
            default=None,
            action="store_true",
            help="Force upload when the same version already exists on the DCSS",
        )
        parser.add_argument(
            "-os",
            "--os-family",
            default=None,
            type=str,
            help="Release for a given os-family",
        )
        parser.add_argument(
            "-t",
            "--token",
            default=None,
            help="(Optional) Duckietown token to use for the upload action",
        )
        return parser

    @classmethod
    def aliases(cls) -> List[str]:
        """
        Alternative names for this command.
        """
        return []
