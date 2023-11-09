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
            "-C", "--workdir", default=None, help="Directory containing the project to work on"
        )
        parser.add_argument(
            "-t", "--template", default=None, help="Template to use (default = project's template)"
        )
        parser.add_argument(
            "--brute", default=False, action="store_true", help="Replace everything"
        )
        parser.add_argument(
            "-v",
            "--version",
            default=None,
            type=str,
            help="Version of the template to use (default = project's template version)",
        )
        parser.add_argument("--apply", default=False, action="store_true", help="Whether to apply the diff")
        # ---
        return parser
