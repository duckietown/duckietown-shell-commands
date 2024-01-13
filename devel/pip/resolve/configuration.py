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
            "-a",
            "--arch",
            default=None,
            help="Target architecture(s) for the image to build",
        )
        parser.add_argument(
            "-H",
            "--machine",
            default=None,
            help="Docker socket or hostname where to build the image",
        )
        parser.add_argument(
            "--no-pull",
            default=False,
            action="store_true",
            help="Whether to skip updating the base image from the registry",
        )
        parser.add_argument(
            "-i",
            "--in-place",
            default=False,
            action="store_true",
            help="Resolve dependencies files in place",
        )
        parser.add_argument(
            "--check",
            default=False,
            action="store_true",
            help="Make sure dependencies lists are pinned, fails otherwise",
        )
        parser.add_argument(
            "--strict",
            default=False,
            action="store_true",
            help="Make sure dependencies lists are stricly pinned (using ==), fails otherwise",
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
