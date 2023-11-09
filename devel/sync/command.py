import argparse
import os
import subprocess

from dt_shell import DTCommandAbs, dtslogger
from utils.cli_utils import ensure_command_is_installed
from utils.docker_utils import DEFAULT_MACHINE
from utils.misc_utils import sanitize_hostname
from utils.multi_command_utils import MultiCommand

DEFAULT_REMOTE_USER = "duckie"
REMOTE_RSYNC_CODE_LOCATION = "/tmp/code"


class DTCommand(DTCommandAbs):
    help = "Syncs the current project with another machine"

    @staticmethod
    def command(shell, args: list, **kwargs):
        parser: argparse.ArgumentParser = DTCommand.parser
        # get pre-parsed or parse arguments
        parsed = kwargs.get("parsed", None)
        if not parsed:
            # try to interpret it as a multi-command
            multi = MultiCommand(DTCommand, shell, [("-H", "--machine")], args)
            if multi.is_multicommand:
                multi.execute()
                return
        if not parsed:
            parsed, _ = parser.parse_known_args(args=args)
        # ---
        parsed.workdir = os.path.abspath(parsed.workdir)
        # sanitize hostname
        if parsed.machine is not None:
            parsed.machine = sanitize_hostname(parsed.machine)
        else:
            parsed.machine = DEFAULT_MACHINE
        # ---
        # sync
        if parsed.machine == DEFAULT_MACHINE:
            # only allowed when mounting remotely
            dtslogger.error("The option -s/--sync can only be used together with -H/--machine")
            exit(2)
        # make sure rsync is installed
        ensure_command_is_installed("rsync")
        dtslogger.info(f"Syncing code with {parsed.machine.replace('.local', '')}...")
        remote_path = f"{DEFAULT_REMOTE_USER}@{parsed.machine}:{REMOTE_RSYNC_CODE_LOCATION}/"
        # get projects' locations
        projects_to_sync = [parsed.workdir] if parsed.mount is True else []
        # sync secondary projects
        if isinstance(parsed.mount, str):
            projects_to_sync.extend(
                [os.path.abspath(os.path.join(os.getcwd(), p.strip())) for p in parsed.mount.split(",")]
            )
        # run rsync
        for project_path in projects_to_sync:
            cmd = f"rsync --archive {project_path} {remote_path}"
            _run_cmd(cmd, shell=True)
        dtslogger.info(f"Code synced!")

    @staticmethod
    def complete(shell, word, line):
        return []


def _run_cmd(cmd, get_output=False, print_output=False, suppress_errors=False, shell=False):
    if shell and isinstance(cmd, (list, tuple)):
        cmd = " ".join([str(s) for s in cmd])
    dtslogger.debug("$ %s" % cmd)
    if get_output:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, shell=shell)
        proc.wait()
        if proc.returncode != 0:
            if not suppress_errors:
                msg = "The command {} returned exit code {}".format(cmd, proc.returncode)
                dtslogger.error(msg)
                raise RuntimeError(msg)
        out = proc.stdout.read().decode("utf-8").rstrip()
        if print_output:
            print(out)
        return out
    else:
        try:
            subprocess.check_call(cmd, shell=shell)
        except subprocess.CalledProcessError as e:
            if not suppress_errors:
                raise e
