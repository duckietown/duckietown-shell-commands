import argparse
from typing import List, Optional

from dt_shell.commands import DTCommandConfigurationAbs

from utils.data_endpoint_utils import STORAGE_ENDPOINTS, STORAGE_SPACES


class DTCommandConfiguration(DTCommandConfigurationAbs):

    @classmethod
    def parser(cls, *args, **kwargs) -> Optional[argparse.ArgumentParser]:
        parser = argparse.ArgumentParser(prog="dts data endpoint switch")
        parser.add_argument(
            "-S",
            "--space",
            required=True,
            choices=STORAGE_SPACES,
            help="Storage space whose S3 endpoint should be switched",
        )
        parser.add_argument(
            "endpoint",
            nargs="?",
            choices=STORAGE_ENDPOINTS,
            default=None,
            help="S3 endpoint to use",
        )
        return parser

    @classmethod
    def aliases(cls) -> List[str]:
        return []
