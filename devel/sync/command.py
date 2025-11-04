import argparse
import os
import subprocess
from typing import List, Optional

from dt_shell import DTCommandAbs, dtslogger
from utils.cli_utils import ensure_command_is_installed
from utils.docker_utils import DEFAULT_MACHINE
from utils.misc_utils import sanitize_hostname
from utils.multi_command_utils import MultiCommand
from utils.mutagen_sync import MutagenSync, MutagenError, ensure_min_version, sanitize_session_name
from utils.ssh_setup import ensure_ssh_for_host
from devel.run.command import REMOTE_USER as DEFAULT_REMOTE_USER

# Default host path on the robot to mirror code into (bind-mount this in containers)
REMOTE_SYNC_CODE_LOCATION = "/code"

# Default ignore patterns for sync
DEFAULT_IGNORE: List[str] = [
    ".git/",
    ".cache/",
    "**/__pycache__/",
    "build/",
    "install/",
    "log/",
    ".vscode-server/",
]


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
            # only allowed when targeting a remote machine
            dtslogger.error("This command requires -H/--machine to specify the remote host")
            exit(2)
        # Ensure SSH key-based auth is configured for the target
        robot_name: Optional[str] = None
        # If the given machine is like NAME.local, derive NAME
        try:
            if parsed.machine.endswith('.local'):
                robot_name = parsed.machine.split('.', 1)[0]
            elif '.' not in parsed.machine:
                # likely MagicDNS short name
                robot_name = parsed.machine
        except Exception:
            pass
        try:
            ensure_ssh_for_host(parsed.machine, user=DEFAULT_REMOTE_USER, robot_name=robot_name)
        except Exception as e:
            # Non-fatal: we proceed; SSH may still prompt if needed
            dtslogger.warning(f"SSH setup encountered an issue: {e}")
        # make sure Mutagen is installed
        ensure_command_is_installed(
            "mutagen",
            dependant="dts devel run",
            custom_msg=(
                "Please install it with:\n"
                "    curl -sS https://webi.sh/mutagen | sh\n"
                "    source ~/.config/envman/PATH.env\n"
                "and try again."
            ),
        )
        # pre-flight version check
        try:
            ensure_min_version("0.17.0")
        except MutagenError as e:
            # Older Mutagen versions work with plain-text parsing; continue with a warning
            dtslogger.warning(str(e))
        dtslogger.info(f"Ensuring Mutagen sync to {parsed.machine.replace('.local', '')}...")
        # get projects' locations
        projects_to_sync = [parsed.workdir] if parsed.mount is True else []
        # sync secondary projects
        if isinstance(parsed.mount, str):
            projects_to_sync.extend(
                [os.path.abspath(os.path.join(os.getcwd(), p.strip())) for p in parsed.mount.split(",")]
            )
        # create or reuse sessions
        sessions = []
        for project_path in projects_to_sync:
            project_path = os.path.abspath(project_path)
            project_name = os.path.basename(project_path.rstrip("/"))
            session_name = sanitize_session_name(f"dts-sync-{project_name}-{parsed.machine}")
            # ensure remote directory exists
            remote_host_dir = os.path.join(REMOTE_SYNC_CODE_LOCATION, project_name)
            _run_cmd([
                "ssh",
                f"{DEFAULT_REMOTE_USER}@{parsed.machine}",
                f"mkdir -p '{remote_host_dir}'"
            ])
            # build Mutagen endpoints
            alpha = project_path
            beta = f"ssh://{DEFAULT_REMOTE_USER}@{parsed.machine}//{remote_host_dir.lstrip('/')}"
            try:
                sync = MutagenSync(name=session_name)
                session = sync.ensure_session(
                    alpha=alpha,
                    beta=beta,
                    ignore_paths=DEFAULT_IGNORE,
                    max_staging_file_size="64MiB",
                )
                dtslogger.info(f"Session ready: {session.name} ({session.identifier})")
                sessions.append((sync, session))
            except MutagenError as e:
                dtslogger.error(str(e))
                exit(2)
        # optional flush
        if parsed.flush_direction:
            for sync, _ in sessions:
                try:
                    sync.flush(parsed.flush_direction)
                except MutagenError as e:
                    dtslogger.warning(f"Flush failed for {sync.name}: {e}")
            dtslogger.info(f"One-shot flush requested: {parsed.flush_direction}")
        # optional monitor (monitor the first session)
        if parsed.monitor and sessions:
            dtslogger.info("Monitoring Mutagen session. Press Ctrl-C to stop...")
            sessions[0][0].monitor()
        else:
            dtslogger.info("Mutagen sync configured. Use 'mutagen sync monitor' to watch events.")

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
