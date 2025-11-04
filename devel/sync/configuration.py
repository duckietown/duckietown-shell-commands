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
            help="Directory containing the project to run"
        )
        parser.add_argument(
            "-H",
            "--machine",
            default=None,
            help="Docker socket or hostname where to run the image",
        )
        parser.add_argument(
            "-M",
            "--mount",
            default=True,
            const=True,
            action="store",
            nargs="?",
            type=str,
            help="Whether to mount the current project into the container. "
                 "Pass a comma-separated list of paths to mount multiple projects",
        )
        parser.add_argument(
            "--monitor",
            default=False,
            action="store_true",
            help="After ensuring sessions, monitor sync activity (Ctrl-C to stop)",
        )
        parser.add_argument(
            "--flush-direction",
            default=None,
            choices=("alpha-to-beta", "beta-to-alpha"),
            help="After ensuring sessions, perform a one-shot flush in this direction",
        )
        # ---
        return parser
