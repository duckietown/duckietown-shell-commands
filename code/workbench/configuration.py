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
            "-H",
            "--machine",
            default=None,
            help="Docker socket or robot name to run the agent on"
        )
        parser.add_argument(
            "-R",
            "--robot",
            default=None,
            help="Name of the robot to connect this agent to",
        )
        parser.add_argument(
            "-u",
            "--username",
            default=get_user_login(),
            help="The docker registry username to use",
        )

        parser.add_argument(
            "-m",
            "--matrix",
            default=False,
            action="store_true",
            help="Should we also run the duckiematrix at the same time?"
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
            "--local",
            action="store_true",
            default=False,
            help="Should we run the code on the local machine rather than the robot?",
        )

        parser.add_argument(
            "--keep",
            action="store_true",
            default=False,
            help="Do not auto-remove containers once done. Produces garbage containers but it is "
                 "useful for debugging.",
        )


        parser.add_argument(
            "-L",
            "--launcher",
            default=None,
            help="The launcher to use as entrypoint to the agent container",
        )
        parser.add_argument(
            "--shell",
            action="store_true",
            default=False,
            help="Attach an interactive shell to the running workbench container",
        )
        parser.add_argument("-v", "--verbose", default=False, action="store_true", help="Be verbose")
        # ---
        return parser

    @classmethod
    def aliases(cls) -> List[str]:
        """
        Alternative names for this command.
        """
        return ["wb"]
