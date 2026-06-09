import argparse
from typing import Optional, List

from dt_shell.commands import DTCommandConfigurationAbs
from dt_shell.environments import ShellCommandEnvironmentAbs

VALID_SPACES = ["user", "public", "private"]


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
        parser = argparse.ArgumentParser(prog="dts data push")
        parser.add_argument(
            "-S",
            "--space",
            default=None,
            choices=VALID_SPACES,
            help="Storage space the object should be uploaded to",
        )
        parser.add_argument(
            "-t",
            "--token",
            default=None,
            help="(Optional) Duckietown token to use for the upload action",
        )
        parser.add_argument(
            "-z",
            "--compress",
            default=False,
            action="store_true",
            help="Compress directory (required when 'file' is a directory)",
        )
        parser.add_argument(
            "--exclude",
            default=None,
            help="(Optional) Files to exclude when compressing a directory",
        )
        parser.add_argument("file", nargs=1, help="File or directory to upload")
        parser.add_argument("object", nargs=1, help="Destination path of the object")
        return parser

    @classmethod
    def aliases(cls) -> List[str]:
        """
        Alternative names for this command.
        """
        return []
