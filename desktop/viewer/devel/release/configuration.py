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
            action="append",
            help="Release for given os-family(ies). Use multiple times for multiple architectures (e.g., -os linux -os linux-arm64)",
        )
        parser.add_argument(
            "--all-archs",
            default=False,
            action="store_true",
            help="Release all available architectures found in the release directory",
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
