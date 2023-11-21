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
        # configure arguments
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "-C", "--workdir", default=os.getcwd(), help="Directory containing the project to build"
        )
        parser.add_argument(
            "-n", "--dry-run", default=False, action="store_true", help="Don't write any files, just pretend."
        )
        parser.add_argument(
            "part",
            nargs="?",
            choices=["major", "minor", "patch"],
            default="patch",
            help="Part of the version to bump",
        )
        # ---
        return parser
