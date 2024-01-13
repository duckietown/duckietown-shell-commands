import os
import argparse
from typing import Optional

from dt_shell.commands import DTCommandConfigurationAbs


class DTCommandConfiguration(DTCommandConfigurationAbs):

    @classmethod
    def parser(cls, *args, **kwargs) -> Optional[argparse.ArgumentParser]:
        """
        The parser this command will use.
        """
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "-C",
            "--workdir",
            default=os.getcwd(),
            help="Directory containing the project to pip-resolve",
        )
        parser.add_argument(
            "--fix",
            default=False,
            action="store_true",
            help="Fix problems as they are found",
        )
        parser.add_argument(
            "--ci",
            default=False,
            action="store_true",
            help="Overwrites configuration for CI (Continuous Integration)",
        )
        parser.add_argument(
            "-v", "--verbose", default=False, action="store_true", help="Be verbose"
        )
        # ---
        return parser
