import argparse
import yaml

from dt_shell import DTCommandAbs, dtslogger
from utils.misc_utils import indent_block

from dt_data_api import DataClient

VALID_SPACES = ["user", "public", "private"]


class DTCommand(DTCommandAbs):
    help = "Prints the metadata of an object from the Duckietown Cloud Storage space"

    usage = f"""
Usage:

    dts data head --space <space> <object>

OR

    dts data head [<space>:]<object>

Where <space> can be one of {str(VALID_SPACES)}.
"""

    @staticmethod
    def _parse_args(args):
        # configure arguments
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "-S",
            "--space",
            default=None,
            choices=VALID_SPACES,
            help="Storage space the object should be fetched from",
        )
        parser.add_argument("object", nargs=1, help="Object to read the metadata for")
        parsed, _ = parser.parse_known_args(args=args)
        return parsed

    @staticmethod
    def command(shell, args, **kwargs):
        parsed = kwargs.get("parsed", None)
        if parsed is None:
            parsed = DTCommand._parse_args(args)
        # ---
        parsed.object = parsed.object[0]
        # check arguments
        # use the format [space]:[object] as a short for
        #      --space [space] [object]
        arg1, arg2, *acc = (parsed.object + ":_").split(":")
        # handle invalid formats
        if len(acc) > 1:
            dtslogger.error("Invalid format for argument 'object'.")
            print(DTCommand.usage)
            exit(1)
        # parse args
        space, object_path = (arg1, arg2) if arg2 != "_" else (None, arg1)
        # make sure that the space is given in at least one form
        if space is None and parsed.space is None:
            dtslogger.error("You must specify a storage space for the object.")
            print(DTCommand.usage)
            exit(2)
        # make sure that at most one space is given
        if space is not None and parsed.space is not None:
            dtslogger.error("You can specify at most one storage space for the object.")
            print(DTCommand.usage)
            exit(3)
        # validate space
        if space is not None and space not in VALID_SPACES:
            dtslogger.error(f"Storage space (short format) can be one of {str(VALID_SPACES)}.")
            print(DTCommand.usage)
            exit(4)
        # sanitize object path (remove leading `/`)
        object_path = object_path[1:] if object_path.startswith("/") else object_path
        # converge args to parsed
        parsed.object = object_path
        if space:
            parsed.space = space

        # get the token if it is set
        token = None
        # noinspection PyBroadException
        try:
            token = shell.get_dt1_token()
        except Exception:
            pass

        # create storage client
        client = DataClient(token)
        storage = client.storage(parsed.space)

        # download file
        dtslogger.info(f"Inspecting [{parsed.space}]:{parsed.object}")
        metadata = storage.head(parsed.object)

        # if we got here, the download is completed
        json_str: str = yaml.dump(metadata, indent=4, sort_keys=True)
        dtslogger.info("Metadata:\n\n")
        print(indent_block(json_str), "\n")
