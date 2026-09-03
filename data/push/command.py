import os
import atexit
import contextlib
import fnmatch
import gc
import signal
import tempfile
import zipfile

from dt_data_api import DataClient, TransferStatus
from dt_shell import DTCommandAbs, dtslogger
from utils.misc_utils import human_size
from utils.progress_bar import ProgressBar

VALID_SPACES = ["user", "public", "private"]


def _remove_file_on_exit(file_path: str) -> None:
    try:
        os.remove(file_path)
    except OSError:
        pass


def _is_excluded(relative_path: str, patterns) -> bool:
    normalized_path = relative_path.replace(os.path.sep, "/").lstrip("./")
    return any(
        fnmatch.fnmatch(normalized_path, pattern.lstrip("./"))
        or fnmatch.fnmatch(f"./{normalized_path}", pattern)
        for pattern in patterns
    )


def _create_zip_archive(source_path: str, archive_path: str, exclude_patterns=()) -> None:
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        if os.path.isfile(source_path):
            archive.write(source_path, arcname=os.path.basename(source_path))
            return

        for root, directory_names, file_names in os.walk(source_path):
            relative_root = os.path.relpath(root, source_path)
            relative_root = "" if relative_root == "." else relative_root.replace(os.path.sep, "/")

            directory_names[:] = [
                name for name in directory_names
                if not _is_excluded(
                    "/".join(filter(None, [relative_root, name])),
                    exclude_patterns,
                )
            ]

            if relative_root and not directory_names and not file_names:
                archive.writestr(f"{relative_root}/", "")

            for file_name in file_names:
                relative_path = "/".join(filter(None, [relative_root, file_name]))
                if not _is_excluded(relative_path, exclude_patterns):
                    archive.write(os.path.join(root, file_name), arcname=relative_path)


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
        try:
            os.remove(self.fpath)
        except OSError:
            dtslogger.warning(
                f"Temporary file '{self.fpath}' is still in use; deferring cleanup until exit."
            )
            atexit.register(_remove_file_on_exit, self.fpath)


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
    def command(shell, args, **kwargs):
        parsed = DTCommand._resolve_parsed(args, kwargs.get("parsed"))
        # ---
        parsed.file = parsed.file[0]
        parsed.object = parsed.object[0]
        parsed.token = parsed.token if hasattr(parsed, "token") else None
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
        token: str = parsed.token
        if token is None:
            token = shell.profile.secrets.dt_token
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
            dtslogger.info(f"Compressing '{parsed.file}' to temporary file '{object_fpath}'...")
            _create_zip_archive(parsed.file, object_fpath, exclude)

        # compress file
        if os.path.isfile(parsed.file) and parsed.compress:
            ctx_mgr = TempZipFile()
            object_fpath = ctx_mgr.fpath
            dtslogger.info(f"Compressing '{parsed.file}' to temporary file '{object_fpath}'...")
            _create_zip_archive(parsed.file, object_fpath)

        # upload file
        with ctx_mgr:
            dtslogger.info(f"Uploading {object_fpath} -> [{parsed.space}]:{parsed.object}")
            handler = storage.upload(object_fpath, parsed.object)
            handler.register_callback(cb)
            # capture SIGINT and abort
            signal.signal(signal.SIGINT, lambda *_: handler.abort())
            # wait for the upload to finish
            handler.join()
            check_status(handler)
            handler = None
            gc.collect()

        # if we got here, the upload is completed
        dtslogger.info("Upload completed!")
