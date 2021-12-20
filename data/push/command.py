import os
import contextlib
import argparse
import signal
import subprocess
import tempfile

from dt_data_api import DataClient, TransferStatus
from dt_shell import DTCommandAbs, dtslogger
from utils.misc_utils import human_size
from utils.progress_bar import ProgressBar

VALID_SPACES = ["user", "public", "private"]


class TempZipFile:

    def __init__(self):
        self._tmpfile = tempfile.NamedTemporaryFile()
        self.fpath = f"{self._tmpfile.name}.zip"
        dtslogger.debug(f"Creating temporary file {self.fpath}...")

    def __enter__(self):
        self._tmpfile.__enter__()

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._tmpfile.__exit__(exc_type, exc_val, exc_tb)
        dtslogger.debug(f"Removing temporary file {self.fpath}.")
        os.remove(self.fpath)


class DTCommand(DTCommandAbs):
    help = "Uploads a file to the Duckietown Cloud Storage space"

    usage = f"""
Usage:

    dts data push --space <space> <file> <object>

OR

    dts data push <file> [<space>:]<object>

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
            help="Storage space the object should be uploaded to",
        )
        parser.add_argument(
            "-t",
            "--token",
            default=None,
            help="(Optional) Duckietown token to use for the upload action",
        )
        parser.add_argument(
            "-z",
            "--compress",
            default=False,
            action="store_true",
            help="Compress directory (required when 'file' is a directory)",
        )
        parser.add_argument(
            "--exclude",
            default=None,
            help="(Optional) Files to exclude when compressing a directory",
        )
        parser.add_argument("file", nargs=1, help="File or directory to upload")
        parser.add_argument("object", nargs=1, help="Destination path of the object")
        parsed, _ = parser.parse_known_args(args=args)
        return parsed

    @staticmethod
    def command(shell, args, **kwargs):
        parsed = kwargs.get("parsed", None)
        if parsed is None:
            parsed = DTCommand._parse_args(args)
        # ---
        parsed.file = parsed.file[0]
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
        space, object_key = (arg1, arg2) if arg2 != "_" else (None, arg1)
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
        object_key = object_key.lstrip('/')
        # converge args to parsed
        parsed.object = object_key
        if space:
            parsed.space = space
        # make sure that the input file exists
        if not os.path.exists(parsed.file):
            dtslogger.error(f"File/directory '{parsed.file}' not found!")
            exit(5)
        # make sure we are compressing when sending a directory
        if os.path.isdir(parsed.file) and not parsed.compress:
            dtslogger.error(f"Argument -z/--compress is required when uploading a directory.")
            exit(8)
        # sanitize file path
        parsed.file = os.path.abspath(parsed.file)
        # get the token if it is not given
        token = None
        if parsed.token is None:
            # get the token if it is set
            # noinspection PyBroadException
            try:
                token = shell.get_dt1_token()
            except Exception:
                pass
        else:
            # the user provided a token, use that one
            token = parsed.token
        token_star = "*" * (len(token) - 3) + token[-3:]
        dtslogger.debug(f"Using token: {token_star}")
        # create storage client
        client = DataClient(token)
        storage = client.storage(parsed.space)
        # prepare progress bar
        pbar = ProgressBar()

        def check_status(h):
            if h.status == TransferStatus.STOPPED:
                print()
                dtslogger.info("Stopping upload...")
                handler.abort(block=True)
                dtslogger.info("Upload stopped!")
                exit(6)
            if h.status == TransferStatus.ERROR:
                dtslogger.error(h.reason)
                exit(7)

        def cb(h):
            speed = human_size(h.progress.speed)
            header = f"Uploading [{speed}/s] "
            header = header + " " * max(0, 26 - len(header))
            pbar.set_header(header)
            pbar.update(h.progress.percentage)
            # check status
            check_status(h)

        # upload (file or directory)
        ctx_mgr = contextlib.suppress()
        object_fpath = parsed.file

        # upload directory
        if os.path.isdir(parsed.file):
            ctx_mgr = TempZipFile()
            object_fpath = ctx_mgr.fpath
            exclude = parsed.exclude.split(",") if parsed.exclude else []
            zip_opts = (["-x"] + exclude) if len(exclude) else []
            dtslogger.info(f"Compressing '{parsed.file}' to temporary file '{object_fpath}'...")
            zip_cmd = ["zip"] + zip_opts + ["-r", object_fpath, "./"]
            dtslogger.debug(f"$ {zip_cmd}")
            subprocess.check_call(zip_cmd, cwd=parsed.file)

        # upload file
        with ctx_mgr:
            dtslogger.info(f"Uploading {object_fpath} -> [{parsed.space}]:{parsed.object}")
            handler = storage.upload(object_fpath, parsed.object)
            handler.register_callback(cb)
            # capture SIGINT and abort
            signal.signal(signal.SIGINT, lambda *_: handler.abort())
            # wait for the upload to finish
            handler.join()

        # check status
        check_status(handler)

        # if we got here, the upload is completed
        dtslogger.info("Upload completed!")
