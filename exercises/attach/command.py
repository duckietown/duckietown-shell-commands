import argparse
import json
import os
import shutil
import subprocess

from dt_shell import DTCommandAbs, dtslogger, UserError
from utils.cli_utils import check_program_dependency
from utils.docker_utils import DOCKER_INFO, get_endpoint_architecture, DEFAULT_MACHINE
from utils.dtproject_utils import CANONICAL_ARCH, BUILD_COMPATIBILITY_MAP
from utils.misc_utils import human_size, sanitize_hostname
from utils.multi_command_utils import MultiCommand

LAUNCHER_FMT = "dt-launcher-%s"
DEFAULT_MOUNTS = ["/var/run/avahi-daemon/socket", "/data"]
DEFAULT_NETWORK_MODE = "host"
DEFAULT_REMOTE_USER = "duckie"

class InvalidUserInput(UserError):
    pass

class DTCommand(DTCommandAbs):

    help = "Runs the current project"

    @staticmethod
    def command(shell, args: list):
        # configure arguments
        parser = argparse.ArgumentParser()
        
        parser.add_argument(
            "-H",
            "--machine",
            default=None,
            help="Docker socket or hostname where to run the image",
        )

        parser.add_argument("-n", "--name", default=None,
                            help="Name of the container")

        parser.add_argument(
            "--runtime", default="docker", type=str, help="Docker runtime to use to run the container"
        )

        # parse arguments
        parsed, _ = parser.parse_known_args(args=args)
        # ---
        # sanitize hostname
        if parsed.machine is not None:
            parsed.machine = sanitize_hostname(parsed.machine)
        else:
            parsed.machine = DEFAULT_MACHINE
        # check runtime
        if shutil.which(parsed.runtime) is None:
            raise ValueError(
                'Docker runtime binary "{}" not found!'.format(parsed.runtime))
        # ---

        working_dir = os.getcwd()
        if not os.path.exists(os.path.join(working_dir, "config.yaml")):
            msg = "You must run this command inside the exercise directory"
            raise InvalidUserInput(msg)

        dtslogger.info("Project workspace: {}".format(working_dir))

        # container name
        if not parsed.name:
            exercise_name = os.path.basename(working_dir)
            parsed.name = f"ex-{exercise_name}-agent"

        dtslogger.info(f"Attempting to attach to container {parsed.name}...")
        # run
        _run_cmd(
            [
                parsed.runtime,
                "-H=%s" % parsed.machine,
                "exec",
                "-it",
                parsed.name,
                "/entrypoint.sh",
                "bash",
            ],
            suppress_errors=True,
        )
        return

    @staticmethod
    def complete(shell, word, line):
        return []


def _run_cmd(
    cmd, get_output=False, print_output=False, suppress_errors=False, shell=False, return_exitcode=False
):
    if shell and isinstance(cmd, (list, tuple)):
        cmd = " ".join([str(s) for s in cmd])
    dtslogger.debug("$ %s" % cmd)
    if get_output:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, shell=shell)
        proc.wait()
        if proc.returncode != 0:
            if not suppress_errors:
                msg = "The command {} returned exit code {}".format(
                    cmd, proc.returncode)
                dtslogger.error(msg)
                raise RuntimeError(msg)
        out = proc.stdout.read().decode("utf-8").rstrip()
        if print_output:
            print(out)
        return out
    else:
        if return_exitcode:
            res = subprocess.run(cmd, shell=shell)
            return res.returncode
        else:
            try:
                subprocess.check_call(cmd, shell=shell)
            except subprocess.CalledProcessError as e:
                if not suppress_errors:
                    raise e
