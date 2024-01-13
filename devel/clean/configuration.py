import os
import argparse
from typing import Optional

from dt_shell.commands import DTCommandConfigurationAbs
from utils.docker_utils import DEFAULT_MACHINE


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
            help="Directory containing the project to clean",
        )
        parser.add_argument(
            "-a",
            "--arch",
            default=None,
            help="Target architecture for the image to clean",
        )
        parser.add_argument(
            "-H",
            "--machine",
            default=DEFAULT_MACHINE,
            help="Docker socket or hostname where to clean the image",
        )
        parser.add_argument(
            "--tag", default=None, help="Overrides 'version' (usually taken to be branch name)"
        )
        # ---
        return parser
