import os
import argparse
from typing import Optional

from dt_shell.commands import DTCommandConfigurationAbs

DEFAULT_HOST: str = "127.0.0.1"
DEFAULT_PORT: int = 8888


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
            "--bind",
            default=DEFAULT_HOST,
            type=str,
            help="Address to bind to",
        )
        parser.add_argument(
            "-p",
            "--port",
            default=DEFAULT_PORT,
            type=int,
            help="Port to bind to. A random port will be assigned by default",
        )
        parser.add_argument(
            "--no-pull",
            default=False,
            action="store_true",
            help="Whether to skip updating the base image from the registry",
        )
        parser.add_argument(
            "-d",
            "--detach",
            default=False,
            action="store_true",
            help="Detach from container and let it run in the background",
        )
        parser.add_argument(
            "-v", "--verbose", default=False, action="store_true", help="Be verbose"
        )
        # ---
        return parser
