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
            help="Directory containing the project to be built"
        )
        parser.add_argument(
            "-H",
            "--machine",
            default=None,
            help="Docker socket or robot name to build the agent on"
        )
        parser.add_argument(
            "-u",
            "--username",
            default=get_user_login(),
            help="The docker registry username to use",
        )
        parser.add_argument(
            "--no-pull",
            default=False,
            action="store_true",
            help="Skip updating the base image from the registry",
        )
        parser.add_argument(
            "--no-cache",
            default=False,
            action="store_true",
            help="Ignore the Docker cache"
        )
        parser.add_argument(
            "--push",
            default=False,
            action="store_true",
            help="Push the resulting Docker image to the registry",
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
            "--registry",
            default=None,
            help="Docker registry to use",
        )
        parser.add_argument(
            "-L",
            "--launcher",
            default=None,
            help="The launcher to use as entrypoint to the built container",
        )
        parser.add_argument(
            "-b",
            "--base-tag",
            default=None,
            help="Docker tag for the base image. Use when the base image is also a development version",
        )
        parser.add_argument("-v", "--verbose", default=False, action="store_true", help="Be verbose")
        parser.add_argument("--quiet", default=False, action="store_true", help="Be quiet")
        # ---
        return parser

    @classmethod
    def aliases(cls) -> List[str]:
        """
        Alternative names for this command.
        """
        return ["wb"]
