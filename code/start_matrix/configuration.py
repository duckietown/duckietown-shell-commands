import argparse
import os
from typing import Optional, List

from dt_shell.commands import DTCommandConfigurationAbs
from dt_shell.environments import ShellCommandEnvironmentAbs
from utils.misc_utils import get_user_login


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
            "-C",
            "--workdir",
            default=os.getcwd(),
            help="Directory containing the project to work on"
        )
        parser.add_argument(
            "--no-pull",
            action="store_true",
            default=False,
            help="Prevent from pulling the latest duckiematrix image"
        )
        parser.add_argument(
            "--recipe",
            default=None,
            help="Path to use if specifying a custom local recipe path",
        )
        parser.add_argument(
            "--recipe-version",
            default=None,
            help="Branch to use if specifying a test branch of the recipes repository",
        )
        parser.add_argument(
            "--no-renderer",
            action="store_true",
            default=False,
            help="Run the matrix without a renderer (engine only)",
        )
        parser.add_argument(
            "-v",
            "--verbose",
            action="store_true",
            default=False,
            help="Be verbose",
        )
        parser.add_argument(
            "--no-tutorial",
            default=False,
            action="store_true",
            help="Disable showing the tutorial",
        )
        parser.add_argument(
            "--browser",
            default=False,
            action="store_true",
            help="Run in browser mode"
        )
        # ---
        return parser

    @classmethod
    def aliases(cls) -> List[str]:
        """
        Alternative names for this command.
        """
        return ["wb"]
