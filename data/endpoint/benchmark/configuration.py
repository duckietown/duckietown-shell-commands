import argparse
from typing import List, Optional

from dt_shell.commands import DTCommandConfigurationAbs

from utils.data_endpoint_utils import STORAGE_SPACES


def positive_integer(value: str) -> int:
    try:
        integer = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be a positive integer") from error
    if integer < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return integer


class DTCommandConfiguration(DTCommandConfigurationAbs):

    @classmethod
    def parser(cls, *args, **kwargs) -> Optional[argparse.ArgumentParser]:
        parser = argparse.ArgumentParser(prog="dts data endpoint benchmark")
        parser.add_argument(
            "-S",
            "--space",
            required=True,
            choices=STORAGE_SPACES,
            help="Storage space the object should be downloaded from",
        )
        parser.add_argument(
            "-r",
            "--runs",
            type=positive_integer,
            default=1,
            metavar="COUNT",
            help="Number of full downloads to perform (default: 1)",
        )
        parser.add_argument(
            "object",
            help="Object to download completely while measuring throughput",
        )
        return parser

    @classmethod
    def aliases(cls) -> List[str]:
        return []
