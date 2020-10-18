import os
import argparse
import signal

from dt_shell import DTCommandAbs, dtslogger
from utils.cli_utils import ProgressBar
from utils.misc_utils import human_size

from dt_data_api import DataClient, TransferStatus


VALID_SPACES = ["public", "private"]


class DTCommand(DTCommandAbs):

    help = "Downloads a file from the Duckietown Cloud Storage space"

    usage = """
Usage:

    dts data get --space <space> <object> <file>
    
OR

    dts data get [<space>:]<object> <file>
    
Where <space> can be one of [public, private].
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
            help="Storage space the object should be downloaded from",
        )
        parser.add_argument(
            "-f",
            "--force",
            default=False,
            action="store_true",
            help="Overwrites local file if it exists"
        )
        parser.add_argument(
            "object",
            nargs=1,
            help="Destination path of the object"
        )
        parser.add_argument(
            "file",
            nargs=1,
            help="File to download"
        )
        parsed, _ = parser.parse_known_args(args=args)
        return parsed

    @staticmethod
    def command(shell, args, **kwargs):
        parsed = kwargs.get("parsed", None)
        if parsed is None:
            parsed = DTCommand._parse_args(args)
        # ---
        parsed.object = parsed.object[0]
        parsed.file = parsed.file[0]
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
        if space is not None and space not in ["public", "private"]:
            dtslogger.error("Storage space (short format) can be either 'public' or 'private'.")
            print(DTCommand.usage)
            exit(4)
        # sanitize object path (remove leading `/`)
        object_path = object_path[1:] if object_path.startswith('/') else object_path
        # converge args to parsed
        parsed.object = object_path
        if space:
            parsed.space = space
        # make sure that the input file does not exist
        if os.path.isfile(parsed.file) and not parsed.force:
            dtslogger.error(f"File '{parsed.file}' already exists! Must be forced.")
            exit(5)
        # sanitize file path
        parsed.file = os.path.abspath(parsed.file)
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
        # prepare progress bar
        pbar = ProgressBar()

        def check_status(h):
            if h.status == TransferStatus.STOPPED:
                print()
                dtslogger.info("Stopping download...")
                handler.abort(block=True)
                dtslogger.info("Download stopped!")
                exit(6)
            if h.status == TransferStatus.ERROR:
                dtslogger.error(h.reason)
                exit(7)

        def cb(h):
            speed = human_size(h.progress.speed)
            header = f"Downloading [{speed}/s] "
            header = header + " " * max(0, 28 - len(header))
            pbar.set_header(header)
            pbar.update(h.progress.percentage)
            # check status
            check_status(h)

        # download file
        dtslogger.info(f"Downloading [{parsed.space}]:{parsed.object} -> {parsed.file}")
        handler = storage.download(parsed.object, parsed.file)
        handler.register_callback(cb)

        # capture SIGINT and abort
        signal.signal(signal.SIGINT, lambda *_: handler.abort())

        # wait for the download to finish
        handler.join()

        # check status
        check_status(handler)

        # if we got here, the download is completed
        dtslogger.info("Download complete!")
