import argparse

from dt_shell import DTCommandAbs, dtslogger

from dt_data_api import DataClient
from utils.cli_utils import ask_confirmation

VALID_SPACES = ["user", "public", "private"]


class DTCommand(DTCommandAbs):
    help = "Removes a file from the Duckietown Cloud Storage space"

    usage = f"""
Usage:

    dts data rm --space <space> <object>

OR

    dts data rm [<space>:]<object>

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
            help="Storage space the object should be removed from",
        )
        parser.add_argument(
            "-y", "--yes", default=False, action="store_true", help="Do not ask for confirmation"
        )
        parser.add_argument("object", nargs=1, help="Path of the object to remove")
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

        # make sure the object exists
        try:
            storage.head(parsed.object)
        except FileNotFoundError:
            dtslogger.error(f"Object [{parsed.space}]:{parsed.object} not found.")
            return False

        # ask for confirmation
        if not parsed.yes:
            confirmed = ask_confirmation("This operation cannot be undone", default="n")
            if not confirmed:
                dtslogger.info("I will not touch anything then, your object is safe.")
                return True

        # remove object
        dtslogger.info(f"Deleting [{parsed.space}]:{parsed.object}")
        success = storage.delete(parsed.object)

        if success:
            dtslogger.info(f"Object [{parsed.space}]:{parsed.object} deleted!")
            return True
        else:
            dtslogger.error(f"An error occurred while deleting the object [{parsed.space}]:{parsed.object}")
            return False
