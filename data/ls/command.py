import argparse
from typing import List

from dt_data_api import DataClient
from dt_shell import DTCommandAbs, dtslogger

VALID_SPACES = ["user", "public", "private"]


class DTCommand(DTCommandAbs):
    help = "Lists all the object contained in a given prefix in a Duckietown Cloud Storage space"

    usage = f"""
Usage:

    dts data ls --space <space> <prefix>

OR

    dts data ls [<space>:]<prefix>

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
            help="Storage space the objects should be listed from",
        )
        parser.add_argument("-d", "--depth", type=int, default=1, help="Depth of the list to generate")
        parser.add_argument("prefix", nargs=1, help="Prefix to list objects from")
        parsed, _ = parser.parse_known_args(args=args)
        return parsed

    @staticmethod
    def command(shell, args, **kwargs):
        parsed = kwargs.get("parsed", None)
        if parsed is None:
            parsed = DTCommand._parse_args(args)
        # ---
        parsed.prefix = parsed.prefix[0]
        # check arguments
        # use the format [space]:[prefix] as a short for
        #      --space [space] [prefix]
        arg1, arg2, *acc = (parsed.prefix + ":_").split(":")
        # handle invalid formats
        if len(acc) > 1:
            dtslogger.error("Invalid format for argument 'object'.")
            print(DTCommand.usage)
            exit(1)
        # parse args
        space, prefix = (arg1, arg2) if arg2 != "_" else (None, arg1)
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
        # sanitize object prefix (remove leading `/`)
        prefix = prefix.lstrip("/")
        # converge args to parsed
        parsed.prefix = prefix
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

        # list objects
        dtslogger.info(f"Fetching objects in [{parsed.space}]:{parsed.prefix.rstrip('/')}/")
        objects = storage.list_objects(parsed.prefix)

        # apply depth filter
        filtered_objects: List[str] = []
        if parsed.depth <= 0:
            filtered_objects = objects
        else:
            for obj in objects:
                if obj.count("/", len(parsed.prefix.rstrip("/"))) > parsed.depth:
                    continue
                filtered_objects.append(obj)

        # print objects
        print("Objects:\n")
        if filtered_objects:
            print("\n".join(filtered_objects))
        else:
            print("(none)")
        print()
